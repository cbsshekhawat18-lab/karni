"""Achievements and missions: declared per game, counted from reports, unlocked by the server."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest import mock

import pytest
from django.utils import timezone
from karni.notify.models import Notification
from karni.testing import capture_events

from karni_game.models import (
    Achievement,
    Completion,
    Currency,
    Game,
    Mission,
    Reward,
    Unlock,
    Wallet,
)
from tests.conftest import Guest, signed_in

GAME = "/api/game/block-hopper/"


@pytest.fixture
def declared(game: Game) -> dict[str, Any]:
    coins = Currency.objects.create(game=game, key="coins", title="Coins")
    badge = Reward.objects.create(
        game=game, key="collector", title="Collector", kind="achievement", currency=coins, amount=50
    )
    daily = Reward.objects.create(
        game=game, key="three-levels", title="Three", kind="mission", currency=coins, amount=30
    )
    return {
        "collector": Achievement.objects.create(
            game=game,
            key="collector",
            title="Collector",
            counter="coins_collected",
            goal=300,
            reward=badge,
        ),
        "secret": Achievement.objects.create(
            game=game, key="secret", title="Secret door", counter="doors", goal=1, hidden=True
        ),
        "levels": Mission.objects.create(
            game=game,
            key="daily-levels",
            title="Three levels today",
            counter="levels_done",
            goal=3,
            period="daily",
            reward=daily,
        ),
    }


def report(guest: Guest, *events: tuple[str, int], intent: str = "") -> Any:
    body: dict[str, Any] = {"events": [{"counter": c, "amount": a} for c, a in events]}
    if intent:
        body["intent"] = intent
    return guest.post(f"{GAME}progress/", body)


def test_an_achievement_unlocks_at_its_goal_and_grants_its_reward(
    guest: Guest, declared: dict[str, Any]
) -> None:
    first = report(guest, ("coins_collected", 200))
    assert first.status_code == 200, first.content
    assert (first.data["counters"], first.data["unlocked"]) == ({"coins_collected": 200}, [])
    with capture_events() as published:
        second = report(guest, ("coins_collected", 112))
    assert second.data["unlocked"] == [
        {
            "key": "collector",
            "title": "Collector",
            "granted": {"currency": "coins", "amount": 50, "balance": 50},
        }
    ]
    published.assert_published("game.achievement.unlocked", achievement="collector")
    assert report(guest, ("coins_collected", 5)).data["unlocked"] == []
    listed = {row["key"]: row for row in guest.get(f"{GAME}achievements/").data["results"]}
    assert listed["collector"]["progress"] == 317
    assert listed["collector"]["unlocked_at"] is not None
    assert Unlock.objects.count() == 1


def test_a_hidden_achievement_shows_once_unlocked(guest: Guest, declared: dict[str, Any]) -> None:
    hidden = {r["key"]: r for r in guest.get(f"{GAME}achievements/").data["results"]}["secret"]
    assert (hidden["title"], hidden["description"]) == ("", "")
    report(guest, ("doors", 1))
    shown = {r["key"]: r for r in guest.get(f"{GAME}achievements/").data["results"]}["secret"]
    assert shown["title"] == "Secret door"


def test_a_daily_mission_is_done_once_a_day(guest: Guest, declared: dict[str, Any]) -> None:
    with capture_events() as published:
        answer = report(guest, ("levels_done", 3))
    assert answer.data["completed"][0]["key"] == "daily-levels"
    published.assert_published("game.mission.completed", mission="daily-levels")
    assert report(guest, ("levels_done", 3)).data["completed"] == []
    (mission,) = guest.get(f"{GAME}missions/").data["results"]
    assert (mission["progress"], mission["completed_at"] is not None) == (6, True)
    later = timezone.now() + timedelta(days=1)
    with mock.patch("django.utils.timezone.now", return_value=later):
        assert guest.get(f"{GAME}missions/").data["results"][0]["progress"] == 0
        assert report(guest, ("levels_done", 3)).data["completed"][0]["key"] == "daily-levels"
    assert Completion.objects.count() == 2
    assert Wallet.objects.get().balance == 60


def test_a_counter_nobody_counts_or_a_big_step_is_game024(
    guest: Guest, game: Game, declared: dict[str, Any]
) -> None:
    unknown = report(guest, ("gems", 1))
    assert (unknown.status_code, unknown.data["code"], unknown.data["index"]) == (400, "GAME024", 0)
    game.settings = {"max_progress_step": 100}
    game.save()
    big = report(guest, ("coins_collected", 50), ("coins_collected", 500))
    assert (big.data["code"], big.data["index"]) == ("GAME024", 1)
    assert report(guest, ("coins_collected", 0)).data["code"] == "GAME024"
    # Nothing of a refused report counted.
    assert guest.get(f"{GAME}achievements/").data["results"][0]["progress"] == 0


def test_a_report_counts_once_per_intent(guest: Guest, declared: dict[str, Any]) -> None:
    report(guest, ("coins_collected", 150), intent="level-7-done")
    again = report(guest, ("coins_collected", 150), intent="level-7-done")
    assert again.data["replayed"] is True
    assert guest.get(f"{GAME}achievements/").data["results"][0]["progress"] == 150


def test_an_account_finds_the_unlock_in_its_inbox(
    declared: dict[str, Any],
    make_account: Callable[..., Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    user = make_account("ines@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        signed_in(user).post(
            f"{GAME}progress/",
            {"events": [{"counter": "coins_collected", "amount": 300}]},
            format="json",
        )
    note = Notification.objects.get(recipient=user)
    assert note.kind == "game.achievement_unlocked"
    assert "Collector" in note.title


def test_another_player_has_their_own_progress(
    guest: Guest, other: Guest, declared: dict[str, Any]
) -> None:
    report(guest, ("coins_collected", 300))
    row = other.get(f"{GAME}achievements/").data["results"][0]
    assert (row["progress"], row["unlocked_at"]) == (0, None)
    assert report(other, ("coins_collected", 1)).data["counters"] == {"coins_collected": 1}


def test_a_guest_who_signs_in_adds_up_progress(
    guest: Guest, declared: dict[str, Any], make_account: Callable[..., Any]
) -> None:
    account = signed_in(make_account("ines@example.com"))
    account.post(
        f"{GAME}progress/",
        {"events": [{"counter": "coins_collected", "amount": 100}]},
        format="json",
    )
    report(guest, ("coins_collected", 120), ("doors", 1))
    answer = account.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
    assert answer.data["merged"]["unlocks"] == 1
    rows = {row["key"]: row for row in account.get(f"{GAME}achievements/").data["results"]}
    assert rows["collector"]["progress"] == 220
    assert rows["secret"]["unlocked_at"] is not None


def test_no_player_reports_progress(api: Any, declared: dict[str, Any]) -> None:
    answer = api.post(
        f"{GAME}progress/", {"events": [{"counter": "doors", "amount": 1}]}, format="json"
    )
    assert answer.data["code"] == "GAME002"
    assert api.get(f"{GAME}achievements/").data["results"][0]["progress"] == 0
