"""Scores and leaderboards: bests per period, ranks, ranges, runs, flags and limits."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone
from karni import people, preferences
from karni.testing import capture_events

from karni_game import clock, hooks
from karni_game.daily import daily_seed
from karni_game.models import Best, Board, Game, Player, Score
from tests.conftest import Guest, signed_in

BOARD = "/api/game/block-hopper/boards/high/"


@pytest.fixture
def board(game: Game) -> Board:
    return Board.objects.create(
        game=game,
        key="high",
        title="High score",
        periods=["all", "daily", "weekly"],
        min_value=0,
        max_value=100_000,
    )


def send(guest: Guest, value: int, **extra: Any) -> Any:
    return guest.post(f"{BOARD}scores/", {"value": value, **extra})


def test_a_score_is_the_best_of_every_period(guest: Guest, board: Board) -> None:
    first = send(guest, 1200)
    assert first.status_code == 201, first.content
    assert first.data["score"]["status"] == "accepted"
    assert first.data["improved"] == ["all", "daily", "weekly"]
    assert first.data["best"]["all"] == {"value": 1200, "rank": 1}
    lower = send(guest, 900)
    assert lower.data["improved"] == []
    assert lower.data["best"]["daily"]["value"] == 1200
    assert Best.objects.filter(player_id=guest.player_id).count() == 3


def test_the_board_ranks_players_and_ties_go_to_the_earlier(
    make_guest: Callable[..., Guest], board: Board
) -> None:
    ana, ben, cai = make_guest("Ana"), make_guest("Ben"), make_guest("Cai")
    send(ana, 500)
    send(ben, 800)
    send(cai, 500)
    answer = ben.get(BOARD, period="all", limit=10)
    assert answer.status_code == 200
    assert [(row["rank"], row["handle"], row["me"]) for row in answer.data["entries"]] == [
        (1, "Ben", True),
        (2, "Ana", False),
        (3, "Cai", False),
    ]
    assert answer.data["me"] == {"rank": 1, "value": 800}
    assert cai.get(f"{BOARD}me/", around=1).data["rank"] == 3
    near = ana.get(f"{BOARD}me/", around=1).data
    assert [row["handle"] for row in near["entries"]] == ["Ben", "Ana", "Cai"]


def test_a_lower_is_better_board(guest: Guest, other: Guest, game: Game) -> None:
    Board.objects.create(game=game, key="speed", title="Fastest", order="asc")
    path = "/api/game/block-hopper/boards/speed/"
    guest.post(f"{path}scores/", {"value": 52_000})
    guest.post(f"{path}scores/", {"value": 48_000})
    other.post(f"{path}scores/", {"value": 50_000})
    entries = guest.get(path).data["entries"]
    assert [(row["handle"], row["value"]) for row in entries] == [
        ("Swift Fox", 48_000),
        ("Quiet Owl", 50_000),
    ]


def test_a_day_and_a_week_start_again(guest: Guest, board: Board) -> None:
    send(guest, 1000)
    later = timezone.now() + timedelta(days=8)
    with mock.patch("django.utils.timezone.now", return_value=later):
        again = send(guest, 400)
        assert again.data["improved"] == ["daily", "weekly"]
        assert guest.get(BOARD, period="daily").data["entries"][0]["value"] == 400
        assert guest.get(BOARD, period="all").data["entries"][0]["value"] == 1000
    assert guest.get(BOARD, period="monthly").status_code == 400


def test_periods_follow_the_games_clock(game: Game) -> None:
    game.settings = {"timezone": "Pacific/Auckland"}
    game.save()
    late = datetime(2026, 11, 19, 20, 0, tzinfo=clock.zone(Game(settings={})))
    assert clock.today(game, late).isoformat() == "2026-11-20"
    assert clock.week_start(clock.today(game, late)).isoformat() == "2026-11-16"


def test_the_plausible_range_refuses_a_score(guest: Guest, board: Board) -> None:
    for value in (-1, 100_001):
        answer = send(guest, value)
        assert (answer.status_code, answer.data["code"]) == (400, "GAME013")
    assert not Score.objects.exists()


def test_a_board_that_needs_runs(guest: Guest, board: Board) -> None:
    board.requires_run = True
    board.save()
    assert send(guest, 10).data["code"] == "GAME014"
    run = {"seed": "42", "inputs": [[0, "jump"], [400, "left"]], "duration_ms": 30_000}
    answer = send(guest, 10, run=run)
    assert answer.status_code == 201
    assert Score.objects.get().run["inputs"] == [[0, "jump"], [400, "left"]]
    with override_settings(KARNI_GAME_MAX_RUN_BYTES=20):
        assert send(guest, 10, run=run).data["code"] == "GAME014"


def test_a_board_that_keeps_no_runs(guest: Guest, board: Board) -> None:
    board.keep_runs = False
    board.save()
    send(guest, 10, run={"seed": "1", "inputs": [1, 2]})
    assert Score.objects.get().run is None


def test_a_daily_board_takes_the_days_seed(guest: Guest, game: Game) -> None:
    Board.objects.create(game=game, key="daily", title="Daily", periods=["daily"], daily_seed=True)
    path = "/api/game/block-hopper/boards/daily/scores/"
    wrong = guest.post(path, {"value": 10, "run": {"seed": "1"}})
    assert wrong.data["code"] == "GAME014"
    seed = daily_seed(game, clock.today(game))
    assert guest.post(path, {"value": 10, "run": {"seed": str(seed)}}).status_code == 201


def test_a_score_beyond_review_waits_for_staff(
    guest: Guest, board: Board, make_account: Callable[..., Any]
) -> None:
    board.review_beyond = 50_000
    board.save()
    with capture_events() as published:
        held = send(guest, 60_000)
    assert held.data["score"]["status"] == "flagged"
    assert held.data["best"] == {}
    assert guest.get(BOARD).data["entries"] == []
    published.assert_published("game.score.flagged", value=60_000)
    moderator = signed_in(make_account("mod@example.com", "game-moderator"))
    flagged = moderator.get("/api/game-scores/", {"status": "flagged"}).data["results"]
    assert len(flagged) == 1
    accepted = moderator.post(f"/api/game-scores/{flagged[0]['id']}/accept/", {}, format="json")
    assert accepted.status_code == 200
    assert guest.get(BOARD).data["entries"][0]["value"] == 60_000


def test_staff_reject_a_score_and_the_best_is_rebuilt(
    guest: Guest, board: Board, make_account: Callable[..., Any]
) -> None:
    send(guest, 500)
    cheat = send(guest, 90_000).data["score"]["id"]
    moderator = signed_in(make_account("mod@example.com", "game-moderator"))
    answer = moderator.post(f"/api/game-scores/{cheat}/reject/", {"note": "No"}, format="json")
    assert answer.status_code == 200
    assert Score.objects.get(pk=cheat).status == "rejected"
    assert guest.get(BOARD).data["entries"][0]["value"] == 500


def test_a_run_check_flags_or_rejects(guest: Guest, board: Board) -> None:
    @hooks.run_check("block-hopper", "high")
    def check(value: int, run: dict[str, Any] | None) -> str:
        return "reject" if value == 13 else "flag" if value == 7 else "accept"

    assert send(guest, 13).data["code"] == "GAME014"
    assert send(guest, 7).data["score"]["status"] == "flagged"
    assert send(guest, 8).data["score"]["status"] == "accepted"


def test_an_intent_counts_once(guest: Guest, board: Board) -> None:
    first = send(guest, 300, intent="run-0001-abc")
    again = send(guest, 300, intent="run-0001-abc")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.data["replayed"] is True
    assert again.data["score"]["id"] == first.data["score"]["id"]
    assert Score.objects.count() == 1
    other_body = send(guest, 301, intent="run-0001-abc")
    assert (other_body.status_code, other_body.data["code"]) == (409, "GAME033")
    assert send(guest, 1, intent="bad").status_code == 400


def test_a_refused_score_leaves_its_intent_free(guest: Guest, board: Board) -> None:
    assert send(guest, -5, intent="run-0002-abc").data["code"] == "GAME013"
    assert send(guest, 5, intent="run-0002-abc").status_code == 201


def test_a_banned_player_sends_no_score_and_leaves_the_board(
    guest: Guest, other: Guest, board: Board
) -> None:
    send(guest, 900)
    send(other, 100)
    Player.objects.filter(pk=guest.player_id).update(banned_at=timezone.now())
    answer = send(guest, 1000)
    assert (answer.status_code, answer.data["code"]) == (403, "GAME029")
    entries = other.get(BOARD).data["entries"]
    assert [row["handle"] for row in entries] == ["Quiet Owl"]
    assert other.get(f"{BOARD}me/").data["rank"] == 1


def test_an_erased_person_leaves_the_board(guest: Guest, other: Guest, board: Board) -> None:
    send(guest, 900)
    send(other, 100)
    people.erase(Player.objects.get(pk=guest.player_id).person)
    assert [row["handle"] for row in other.get(BOARD).data["entries"]] == ["Quiet Owl"]


def test_scores_are_limited_per_player(guest: Guest, other: Guest, board: Board) -> None:
    with override_settings(KARNI_GAME_RATES={"score": "2/min"}):
        send(guest, 1)
        send(guest, 2)
        refused = send(guest, 3)
        assert (refused.status_code, refused.data["code"]) == (429, "GAME015")
        assert send(other, 3).status_code == 201


def test_boards_and_games_are_apart(guest: Guest, board: Board) -> None:
    send(guest, 100)
    tile = Game.objects.create(slug="tile-match", title="Tile Match")
    Board.objects.create(game=tile, key="high", title="High")
    assert guest.get("/api/game/tile-match/boards/high/").data["entries"] == []
    assert guest.get("/api/game/block-hopper/boards/nope/").data["code"] == "GAME012"


def test_boards_may_be_for_players_only(api: Any, guest: Guest, board: Board) -> None:
    send(guest, 100)
    assert api.get(BOARD).status_code == 200
    with preferences.override(game={"public_boards": False}):
        assert api.get(BOARD).data["code"] == "GAME002"
        assert guest.get(BOARD).status_code == 200


def test_another_player_never_changes_a_best(guest: Guest, other: Guest, board: Board) -> None:
    send(guest, 900)
    send(other, 50)
    assert Best.objects.get(player_id=guest.player_id, period="all").value == 900
    assert other.get(f"{BOARD}me/").data["value"] == 50
    assert other.get(BOARD).data["me"] == {"rank": 2, "value": 50}


def test_the_boot_call_lists_the_boards(api: Any, board: Board) -> None:
    (listed,) = api.get("/api/game/block-hopper/").data["boards"]
    assert listed["key"] == "high" and listed["periods"] == ["all", "daily", "weekly"]


def test_a_board_checks_its_periods_and_range(game: Game) -> None:
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        Board.objects.create(game=game, key="x", title="X", periods=["monthly"])
    with pytest.raises(ValidationError):
        Board.objects.create(game=game, key="y", title="Y", min_value=10, max_value=1)


def test_a_guest_who_signs_in_keeps_the_better_best(
    guest: Guest, board: Board, make_account: Callable[..., Any]
) -> None:
    account = signed_in(make_account("ines@example.com"))
    account.post(f"{BOARD}scores/", {"value": 400}, format="json")
    send(guest, 700)
    answer = account.post("/api/game/upgrade/", {"guest_token": guest.token}, format="json")
    assert answer.data["merged"]["scores"] == 1
    entries = account.get(BOARD).data["entries"]
    assert [(row["value"], row["me"]) for row in entries] == [(700, True)]
    assert Score.objects.filter(player__person__user__isnull=False).count() == 2


def test_old_intents_are_pruned(guest: Guest, board: Board) -> None:
    from karni_game.models import Intent
    from karni_game.tasks import prune_intents

    send(guest, 1, intent="run-0003-abc")
    Intent.objects.update(created_at=timezone.now() - timedelta(days=8))
    send(guest, 2, intent="run-0004-abc")
    assert prune_intents() == 1
    assert list(Intent.objects.values_list("key", flat=True)) == ["run-0004-abc"]


def test_a_score_played_before_midnight_lands_on_that_days_board(guest: Guest, game: Game) -> None:
    Board.objects.create(
        game=game, key="today", title="Today", periods=["daily", "weekly"], daily_seed=True
    )
    path = "/api/game/block-hopper/boards/today/"
    yesterday = clock.today(game) - timedelta(days=1)
    played = timezone.now() - timedelta(hours=20)
    played_day = clock.today(game, played)
    seed = daily_seed(game, played_day)
    answer = guest.post(
        f"{path}scores/",
        {"value": 70, "played_at": played.isoformat(), "run": {"seed": str(seed)}},
    )
    assert answer.status_code == 201, answer.content
    score = Score.objects.get()
    assert (score.day, score.played_at) == (played_day, played)
    best = Best.objects.get(player_id=guest.player_id, period="daily")
    assert (best.period_start, best.achieved_at) == (played_day, played)
    if played_day == yesterday:  # the run's seed is the day it was played, not today's
        assert guest.get(path, period="daily").data["entries"] == []


def test_a_played_at_outside_the_window_is_game036(guest: Guest, board: Board) -> None:
    old = timezone.now() - timedelta(days=2)
    answer = send(guest, 10, played_at=old.isoformat())
    assert (answer.status_code, answer.data["code"], answer.data["window"]) == (
        400,
        "GAME036",
        86400,
    )
    ahead = timezone.now() + timedelta(minutes=5)
    assert send(guest, 10, played_at=ahead.isoformat()).data["code"] == "GAME036"
    with override_settings(KARNI_GAME_PLAYED_AT_WINDOW=3 * 86400):
        assert send(guest, 10, played_at=old.isoformat()).status_code == 201
    assert not Score.objects.filter(day__gt=clock.today(board.game)).exists()
