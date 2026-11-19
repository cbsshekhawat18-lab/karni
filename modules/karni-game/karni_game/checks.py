"""Checks of karni-game: the system check ``karni.GAME001`` and ``karni check``'s ``GAME030``."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from karni.exceptions import check_error

__all__ = ["people_installed", "run_checks"]

#: The code of the urls check.
URLS_CODE = "GAME030"


def people_installed(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """``karni.GAME001``: a player is the game profile of a person (``karni.people``)."""
    if apps.is_installed("karni.people"):
        return []
    return [
        check_error(
            "GAME001",
            "karni-game is installed without the people contract: a player is the game "
            "profile of a person (karni.people).",
            hint="Set KARNI_PEOPLE = True above karni_settings(globals()) in your settings, "
            "then run migrate.",
        )
    ]


def run_checks() -> list[str]:
    """``karni check``: the game API is mounted (``GAME030``)."""
    from django.urls import NoReverseMatch, reverse

    try:
        reverse("karni_game:guest")
    except NoReverseMatch:
        return [
            f"{URLS_CODE}: karni_game.urls is not included, so the game API answers 404. Add "
            'path("api/game/", include("karni_game.urls")) to config/urls.py.'
        ]
    return []
