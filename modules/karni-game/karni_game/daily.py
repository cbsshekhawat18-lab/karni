"""Experimental. A game's daily content on the server's date: the seed, the streak.

:func:`daily_seed` is the seed of a game's day: the same number for every
player of the game that day, and unknown before it (it is derived from the
project's ``SECRET_KEY``). A daily level generator and a daily board use it,
so nobody plays tomorrow's level today by changing the device clock.

Override / escape hatch: ``KARNI_GAME_DAILY_SEED`` names another
``seed(game, day) -> int`` (a seed list staff curate, say).
"""

from __future__ import annotations

from datetime import date

from django.utils.crypto import salted_hmac
from django.utils.module_loading import import_string

from karni_game import conf
from karni_game.models import Game

__all__ = ["daily_seed", "seed_of"]


def daily_seed(game: Game, day: date) -> int:
    """A whole number from 0 to 2**31 - 1 for ``game`` on ``day``."""
    digest = salted_hmac("karni_game.daily_seed", f"{game.slug}:{day.isoformat()}").digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def seed_of(game: Game, day: date) -> int:
    """The seed of ``day``, from the function ``KARNI_GAME_DAILY_SEED`` names."""
    value = conf.get("KARNI_GAME_DAILY_SEED") or "karni_game.daily.daily_seed"
    function = import_string(value) if isinstance(value, str) else value
    return int(function(game, day))
