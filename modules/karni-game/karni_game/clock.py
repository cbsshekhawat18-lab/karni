"""The server's clock of a game: its day, its week, when the day resets.

A game's day is a date on the game's own time zone (``timezone`` in its
settings, UTC by default), never the device's. A week starts on Monday.
Every daily and weekly thing (a daily board, a streak, a daily mission, a
reward's daily cap) reads its day here.

Override / escape hatch: tests freeze time as for any Django code
(``timezone.now`` is what this reads); a game with another day boundary
sets its ``timezone``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from karni_game.models import Game

__all__ = ["ALL_TIME", "PERIODS", "period_start", "resets_at", "today", "week_start", "zone"]

#: The periods a board or a mission keeps.
PERIODS = ("all", "daily", "weekly")
#: The bucket of all time (a date, so one column holds every period's start).
ALL_TIME = date(1970, 1, 1)


def zone(game: Game) -> ZoneInfo:
    return ZoneInfo(game.options().timezone)


def today(game: Game, at: datetime | None = None) -> date:
    """The game's date now (or at ``at``)."""
    return (at or timezone.now()).astimezone(zone(game)).date()


def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


def period_start(game: Game, period: str, at: datetime | None = None) -> date:
    """The first day of ``period`` now: :data:`ALL_TIME`, today, or this week's Monday."""
    if period == "daily":
        return today(game, at)
    if period == "weekly":
        return week_start(today(game, at))
    return ALL_TIME


def resets_at(game: Game, at: datetime | None = None) -> datetime:
    """When the game's next day starts, in UTC."""
    local = zone(game)
    tomorrow = today(game, at) + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=local).astimezone(
        ZoneInfo("UTC")
    )
