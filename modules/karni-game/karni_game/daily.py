"""Experimental. A game's daily content on the server's date: the seed, the streak, the rewards.

:func:`daily_seed` is the seed of a game's day: the same number for every
player of the game that day, and unknown before it (it is derived from the
project's ``SECRET_KEY``). A daily level generator and a daily board use it,
so nobody plays tomorrow's level today by changing the device clock.

:func:`check_in` is once a day: the streak goes on when the last check-in was
yesterday or up to ``streak_grace_days`` before, starts again at 1 otherwise,
and the game's ``daily`` rewards are granted. A second check-in on the same
day changes nothing.

Override / escape hatch: ``KARNI_GAME_DAILY_SEED`` names another
``seed(game, day) -> int`` (a seed list staff curate, say), and a game's
``streak_grace_days`` its grace.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import IntegrityError, router, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.module_loading import import_string

from karni_game import clock, conf
from karni_game.models import Board, Game, Player, Reward, Streak

__all__ = ["check_in", "daily_board", "daily_data", "daily_seed", "seed_of", "streak_data"]


def daily_seed(game: Game, day: date) -> int:
    """A whole number from 0 to 2**31 - 1 for ``game`` on ``day``."""
    digest = salted_hmac("karni_game.daily_seed", f"{game.slug}:{day.isoformat()}").digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def seed_of(game: Game, day: date) -> int:
    """The seed of ``day``, from the function ``KARNI_GAME_DAILY_SEED`` names."""
    value = conf.get("KARNI_GAME_DAILY_SEED") or "karni_game.daily.daily_seed"
    function = import_string(value) if isinstance(value, str) else value
    return int(function(game, day))


def daily_board(game: Game) -> Board | None:
    """The game's daily board: its first active board with ``daily_seed``."""
    return Board.objects.filter(game=game, is_active=True, daily_seed=True).first()


def _streak(player: Player, game: Game, *, lock: bool = False) -> Streak:
    rows = Streak.objects.select_for_update() if lock else Streak.objects
    found = rows.filter(player=player, game=game).first()
    if found is not None:
        return found
    try:
        with transaction.atomic(using=router.db_for_write(Streak)):
            Streak.objects.create(player=player, game=game)
    except IntegrityError:  # another request made it first
        pass
    return rows.get(player=player, game=game)


def streak_data(streak: Streak, today: date) -> dict[str, Any]:
    return {
        "current": streak.current,
        "best": streak.best,
        "last_day": streak.last_day.isoformat() if streak.last_day else None,
        "checked_in": streak.last_day == today,
    }


def _rewards(game: Game) -> list[Reward]:
    return list(
        Reward.objects.filter(game=game, kind="daily", is_active=True).select_related("currency")
    )


def daily_data(game: Game, player: Player | None) -> dict[str, Any]:
    """``GET daily/``: the day, its seed, the daily board, the player's streak."""
    now = timezone.now()
    today = clock.today(game, now)
    board = daily_board(game)
    streak = None
    if player is not None:
        found = Streak.objects.filter(player=player, game=game).first()
        streak = streak_data(found or Streak(player=player, game=game), today)
    return {
        "date": today.isoformat(),
        "seed": seed_of(game, today),
        "server_time": now,
        "resets_at": clock.resets_at(game, now),
        "board": board.key if board is not None else None,
        "streak": streak,
        "rewards": [
            {"key": row.key, "currency": row.currency.key, "amount": row.amount}
            for row in _rewards(game)
        ],
    }


def check_in(player: Player, game: Game) -> dict[str, Any]:
    """Once a day: the streak moves on and the game's daily rewards are granted."""
    from karni_game import rewards

    today = clock.today(game)
    grace = game.options().streak_grace_days
    granted: list[dict[str, Any]] = []
    with transaction.atomic(using=router.db_for_write(Streak)):
        streak = _streak(player, game, lock=True)
        if streak.last_day == today:
            return {"new_day": False, "streak": streak_data(streak, today), "granted": []}
        on_time = streak.last_day is not None and streak.last_day >= today - timedelta(
            days=1 + grace
        )
        streak.current = streak.current + 1 if on_time else 1
        streak.best = max(streak.best, streak.current)
        streak.last_day = today
        streak.save(update_fields=["current", "best", "last_day", "updated_at"])
        for reward in _rewards(game):
            reward.game = game
            if not rewards.availability(player, reward)["available"]:
                continue  # a merge brought today's claim along
            done = rewards.grant(player, reward, source="daily")
            granted.append({"reward": reward.key, **done.change.as_dict()})
    return {"new_day": True, "streak": streak_data(streak, today), "granted": granted}
