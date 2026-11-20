"""Daily content on the server's date: the seed, the streak with its grace, the daily rewards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from karni_game import clock
from karni_game.daily import daily_seed
from karni_game.models import Board, Currency, Game, Reward, Streak, Wallet
from tests.conftest import Guest, signed_in

DAILY = "/api/game/block-hopper/daily/"


@pytest.fixture
def daily_coins(game: Game) -> Reward:
    coins = Currency.objects.create(game=game, key="coins", title="Coins")
    return Reward.objects.create(
        game=game, key="daily-coins", title="Daily", kind="daily", currency=coins, amount=10
    )


def on(days: int) -> Any:
    return mock.patch(
        "django.utils.timezone.now", return_value=timezone.now() + timedelta(days=days)
    )


def test_the_day_its_seed_and_board(api: Any, game: Game) -> None:
    Board.objects.create(game=game, key="daily", title="Daily", periods=["daily"], daily_seed=True)
    answer = api.get(DAILY)
    assert answer.status_code == 200
    today = clock.today(game)
    assert answer.data["date"] == today.isoformat()
    assert answer.data["seed"] == daily_seed(game, today)
    assert answer.data["board"] == "daily"
    assert answer.data["streak"] is None
    with on(1):
        assert api.get(DAILY).data["seed"] != answer.data["seed"]


def test_the_seed_is_the_same_for_everyone_and_per_game(game: Game) -> None:
    other = Game.objects.create(slug="tile-match", title="Tile Match")
    day = clock.today(game)
    assert daily_seed(game, day) == daily_seed(game, day)
    assert daily_seed(game, day) != daily_seed(other, day)
    seed = daily_seed(game, day)
    assert 0 <= seed < 2**31
    # Derived from the project's secret: unknown to anyone who does not hold it.
    with override_settings(SECRET_KEY="another-project-secret-key-for-the-test"):
        assert daily_seed(game, day) != seed


def test_a_project_swaps_the_seed(api: Any, game: Game) -> None:
    with override_settings(KARNI_GAME_DAILY_SEED="tests.test_daily.fixed_seed"):
        assert api.get(DAILY).data["seed"] == 7


def fixed_seed(game: Game, day: Any) -> int:
    return 7


def test_a_check_in_is_once_a_day_and_grants_the_daily_reward(
    guest: Guest, daily_coins: Reward
) -> None:
    first = guest.post(f"{DAILY}check-in/")
    assert first.status_code == 200, first.content
    assert first.data["new_day"] is True
    assert first.data["streak"]["current"] == 1
    assert first.data["granted"] == [
        {"reward": "daily-coins", "currency": "coins", "amount": 10, "balance": 10}
    ]
    again = guest.post(f"{DAILY}check-in/")
    assert (again.data["new_day"], again.data["granted"]) == (False, [])
    assert Wallet.objects.get().balance == 10
    assert guest.get(DAILY).data["streak"]["checked_in"] is True


def test_a_streak_goes_on_with_its_grace_and_starts_again(guest: Guest, game: Game) -> None:
    guest.post(f"{DAILY}check-in/")
    with on(1):
        assert guest.post(f"{DAILY}check-in/").data["streak"]["current"] == 2
    with on(3):  # one day missed: the grace keeps it
        assert guest.post(f"{DAILY}check-in/").data["streak"]["current"] == 3
    with on(6):  # two days missed: it starts again
        streak = guest.post(f"{DAILY}check-in/").data["streak"]
    assert (streak["current"], streak["best"]) == (1, 3)


def test_no_grace_breaks_a_streak_after_one_missed_day(guest: Guest, game: Game) -> None:
    game.settings = {"streak_grace_days": 0}
    game.save()
    guest.post(f"{DAILY}check-in/")
    with on(2):
        assert guest.post(f"{DAILY}check-in/").data["streak"]["current"] == 1


def test_the_day_is_the_games_not_the_devices(guest: Guest, game: Game) -> None:
    game.settings = {"timezone": "Pacific/Kiritimati"}  # UTC+14
    game.save()
    answer = guest.get(DAILY)
    assert answer.data["date"] == clock.today(game).isoformat()
    assert answer.data["resets_at"] > timezone.now()


def test_another_player_has_their_own_streak(
    guest: Guest, other: Guest, daily_coins: Reward
) -> None:
    guest.post(f"{DAILY}check-in/")
    assert other.get(DAILY).data["streak"]["current"] == 0
    assert other.post(f"{DAILY}check-in/").data["granted"][0]["balance"] == 10
    assert Streak.objects.count() == 2


def test_a_guest_who_signs_in_keeps_the_longer_streak(
    guest: Guest, game: Game, daily_coins: Reward, make_account: Callable[..., Any]
) -> None:
    account = signed_in(make_account("ines@example.com"))
    guest.post(f"{DAILY}check-in/")
    with on(1):
        guest.post(f"{DAILY}check-in/")
        account.post(f"{DAILY}check-in/", {}, format="json")
        answer = account.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
        assert answer.status_code == 200
        streak = account.get(DAILY).data["streak"]
        assert (streak["current"], streak["best"]) == (2, 2)
        # Both claimed today: the merge keeps both claims, so nothing more today.
        assert account.post(f"{DAILY}check-in/", {}, format="json").data["new_day"] is False


def test_no_player_checks_in(api: Any, game: Game) -> None:
    assert api.post(f"{DAILY}check-in/", {}, format="json").data["code"] == "GAME002"
