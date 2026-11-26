"""Scores and leaderboards: one best per player, board and period.

:func:`submit` checks a score before it counts: the player is not banned
(``GAME029``), the value is in the board's plausible range (``GAME013``), the
run is there when the board needs one, small enough, and on the day's seed on
a daily board (``GAME014``), and the project's run check
(:func:`karni_game.hooks.run_check`) accepts it. A score better than the
board's ``review_beyond``, or one the check flags, waits for staff
(``flagged``) and counts nowhere until :func:`accept`. :func:`reject` takes a
score off and rebuilds the player's bests.

Periods are the game's own days and weeks (:mod:`karni_game.clock`). A tie
goes to the earlier score. A banned player, an erased person and a deleted
player are on no board.

Override / escape hatch: a run check per board in ``<app>/game.py``,
:func:`rebuild` for a project that edits scores by hand, and the querysets of
:func:`ranked` for a board page of your own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, router, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from karni.events import publish

from karni_game import clock, conf, hooks
from karni_game.daily import seed_of
from karni_game.errors import game_error
from karni_game.models import Best, Board, Player, Score

__all__ = [
    "Submitted",
    "accept",
    "board_data",
    "entry",
    "find_board",
    "rank_of",
    "ranked",
    "rebuild",
    "reject",
    "submit",
    "visible",
]


def find_board(game: Any, key: str) -> Board:
    """The game's active board ``key`` (``GAME012``, 404)."""
    found = Board.objects.filter(game=game, key=key, is_active=True).first()
    if found is None:
        raise game_error(
            "GAME012", f"{game.slug} has no active board with the key {key!r}.", status=404
        )
    found.game = game
    return found


def board_data(board: Board) -> dict[str, Any]:
    return {
        "key": board.key,
        "title": board.title,
        "order": board.order,
        "periods": list(board.periods),
        "requires_run": board.requires_run,
        "daily_seed": board.daily_seed,
    }


def visible(rows: QuerySet[Best]) -> QuerySet[Best]:
    """The bests a board shows: no banned player, no erased person, no deleted player."""
    return rows.filter(
        player__banned_at__isnull=True,
        player__deleted_at__isnull=True,
        player__person__erased_at__isnull=True,
    )


def _ordering(board: Board) -> tuple[str, str]:
    return ("value" if board.order == "asc" else "-value", "achieved_at")


def ranked(board: Board, period: str, start: Any) -> QuerySet[Best]:
    """The board's bests of one period, best first."""
    rows = Best.objects.filter(board=board, period=period, period_start=start)
    return visible(rows).select_related("player").order_by(*_ordering(board), "player_id")


def rank_of(board: Board, best: Best) -> int:
    """1 plus how many visible bests of the same period rank above ``best``."""
    better = Q(value__lt=best.value) if board.order == "asc" else Q(value__gt=best.value)
    tied = Q(value=best.value, achieved_at__lt=best.achieved_at)
    rows = Best.objects.filter(board=board, period=best.period, period_start=best.period_start)
    return visible(rows).filter(better | tied).count() + 1


def entry(rank: int, best: Best, player: Player | None) -> dict[str, Any]:
    return {
        "rank": rank,
        "handle": best.player.handle,
        "value": best.value,
        "achieved_at": best.achieved_at,
        "me": player is not None and best.player_id == player.pk,
    }


#: How far ahead of the server's clock a played_at may be (two clocks never agree).
AHEAD = timedelta(seconds=60)


def played_time(played_at: datetime | None) -> datetime:
    """When the score was played: ``played_at`` inside ``KARNI_GAME_PLAYED_AT_WINDOW``, else
    ``GAME036``. Without one, now."""
    now = timezone.now()
    if played_at is None:
        return now
    window = int(conf.get("KARNI_GAME_PLAYED_AT_WINDOW"))
    if played_at > now + AHEAD or played_at < now - timedelta(seconds=window):
        raise game_error(
            "GAME036",
            f"played_at {played_at.isoformat()} is outside the {window} seconds the server "
            "trusts. Send the score without it, or sooner.",
            window=window,
        )
    return played_at


def _check_run(board: Board, run: dict[str, Any] | None, day: Any) -> None:
    if run is None:
        if board.requires_run:
            raise game_error(
                "GAME014", f"Board {board.key} needs the run with every score (seed, inputs)."
            )
        return
    size = len(json.dumps(run, separators=(",", ":")).encode("utf-8"))
    limit = int(conf.get("KARNI_GAME_MAX_RUN_BYTES"))
    if size > limit:
        raise game_error("GAME014", f"The run is {size} bytes, and a run may be {limit}.")
    if board.daily_seed:
        seed = seed_of(board.game, day)
        if str(run.get("seed", "")) != str(seed):
            raise game_error(
                "GAME014",
                f"Board {board.key} is a daily board: a run uses the seed of the day it was "
                "played (GET daily/).",
            )


def _verdict(board: Board, value: int, run: dict[str, Any] | None) -> str:
    if board.review_beyond is not None and board.better(value, board.review_beyond):
        return "flag"
    check = hooks.run_check_for(board.game.slug, board.key)
    if check is None:
        return "accept"
    verdict = str(check(value, run))
    if verdict not in hooks.RUN_VERDICTS:
        verdict = "flag"  # a check that answers something else holds the score for staff
    return verdict


def _start(period: str, day: Any) -> Any:
    if period == "daily":
        return day
    if period == "weekly":
        return clock.week_start(day)
    return clock.ALL_TIME


def _offer_period(score: Score, period: str) -> bool:
    board = score.board
    start = _start(period, score.day)
    row = (
        Best.objects.select_for_update()
        .filter(board=board, player=score.player, period=period, period_start=start)
        .first()
    )
    if row is None:
        Best.objects.create(
            board=board,
            player=score.player,
            period=period,
            period_start=start,
            value=score.value,
            achieved_at=score.played_at or score.created_at,
            score=score,
        )
        return True
    if board.better(score.value, row.value):
        row.value, row.achieved_at, row.score = (
            score.value,
            score.played_at or score.created_at,
            score,
        )
        row.save(update_fields=["value", "achieved_at", "score", "updated_at"])
        return True
    return False


def _offer(score: Score) -> list[str]:
    """Make ``score`` the player's best where it beats it. Returns the periods it improved."""
    improved: list[str] = []
    for period in score.board.periods:
        try:
            with transaction.atomic(using=router.db_for_write(Best)):
                if _offer_period(score, period):
                    improved.append(period)
        except IntegrityError:  # another score of the player made the row first
            with transaction.atomic(using=router.db_for_write(Best)):
                if _offer_period(score, period):
                    improved.append(period)
    return improved


def _bests_now(board: Board, player: Player) -> dict[str, dict[str, Any]]:
    now = timezone.now()
    found: dict[str, dict[str, Any]] = {}
    for period in board.periods:
        start = clock.period_start(board.game, period, now)
        row = Best.objects.filter(
            board=board, player=player, period=period, period_start=start
        ).first()
        if row is not None:
            found[period] = {"value": row.value, "rank": rank_of(board, row)}
    return found


@dataclass(frozen=True)
class Submitted:
    """A stored score, the player's bests now, and the periods it improved."""

    score: Score
    best: dict[str, dict[str, Any]]
    improved: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": {
                "id": str(self.score.pk),
                "value": self.score.value,
                "status": self.score.status,
                "created_at": self.score.created_at,
            },
            "best": self.best,
            "improved": self.improved,
        }


def submit(
    player: Player,
    board: Board,
    value: int,
    run: dict[str, Any] | None = None,
    *,
    source: str = "client",
    played_at: datetime | None = None,
) -> Submitted:
    """Check and store a score. Accepted, it may be the player's new best.

    ``played_at`` (the client's, for a score played offline) is trusted inside
    ``KARNI_GAME_PLAYED_AT_WINDOW``: the score is on the boards of that day and week.
    """
    if player.is_banned:
        raise game_error(
            "GAME029", "This player is banned from the boards: no score counts.", status=403
        )
    if board.min_value is not None and value < board.min_value:
        raise game_error(
            "GAME013",
            f"{value} is below the lowest score board {board.key} takes ({board.min_value}).",
        )
    if board.max_value is not None and value > board.max_value:
        raise game_error(
            "GAME013",
            f"{value} is above the highest score board {board.key} takes ({board.max_value}).",
        )
    when = played_time(played_at)
    day = clock.today(board.game, when)
    if source == "client":
        _check_run(board, run, day)
    verdict = _verdict(board, value, run) if source == "client" else "accept"
    if verdict == "reject":
        raise game_error("GAME014", f"The run does not check out on board {board.key}.")
    with transaction.atomic(using=router.db_for_write(Score)):
        score = Score.objects.create(
            board=board,
            player=player,
            value=value,
            status="flagged" if verdict == "flag" else "accepted",
            day=day,
            played_at=when,
            run=run if board.keep_runs else None,
            source=source,
        )
        improved: list[str] = []
        if score.status == "accepted":
            improved = _offer(score)
        else:
            publish(
                "game.score.flagged",
                subject=score,
                person=player.person_id,
                game=board.game.slug,
                player=str(player.pk),
                board=board.key,
                score=str(score.pk),
                value=value,
            )
    return Submitted(score=score, best=_bests_now(board, player), improved=improved)


def rebuild(player: Player, boards: list[Board] | None = None) -> int:
    """The player's bests made again from their accepted scores; returns how many rows."""
    if boards is None:
        boards = list(Board.objects.filter(scores__player=player).distinct())
    count = 0
    with transaction.atomic(using=router.db_for_write(Best)):
        for board in boards:
            Best.objects.filter(board=board, player=player).delete()
            rows = Score.objects.filter(board=board, player=player, status="accepted")
            for score in rows.order_by("created_at"):
                score.board = board
                _offer(score)
            count += Best.objects.filter(board=board, player=player).count()
    return count


def accept(score: Score) -> Score:
    """Staff let a flagged (or rejected) score count."""
    with transaction.atomic(using=router.db_for_write(Score)):
        Score.objects.filter(pk=score.pk).update(status="accepted", reviewed_at=timezone.now())
        score.refresh_from_db()
        _offer(score)
    return score


def reject(score: Score, note: str = "") -> Score:
    """Staff take a score off the boards; the player's bests are rebuilt without it."""
    with transaction.atomic(using=router.db_for_write(Score)):
        Score.objects.filter(pk=score.pk).update(
            status="rejected", reviewed_at=timezone.now(), note=note[:200]
        )
        score.refresh_from_db()
        rebuild(score.player, [score.board])
    return score
