"""Checks of karni-game: the system check ``karni.GAME001`` and ``karni check``'s ``GAME030``."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from karni.exceptions import check_error

__all__ = ["people_installed", "run_checks"]

#: The code of the urls check.
URLS_CODE = "GAME030"
#: The code of the cross-origin check.
CORS_CODE = "GAME038"


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
    """``karni check``: the game API is mounted (``GAME030``). Nothing for a project that
    has karni-game installed in its interpreter without the app in ``INSTALLED_APPS``."""
    from django.urls import NoReverseMatch, reverse

    if not apps.is_installed("karni_game"):
        return []
    failures = _cors()
    try:
        reverse("karni_game:guest")
    except NoReverseMatch:
        failures.append(
            f"{URLS_CODE}: karni_game.urls is not included, so the game API answers 404. Add "
            'path("api/game/", include("karni_game.urls")) to config/urls.py.'
        )
    return failures


def _cors() -> list[str]:
    """``GAME038``: other origins may call the game API, and the browser may not send the
    guest token's header. Cookies never sign in across origins: the game views drop the
    session for such a call, whatever ``CORS_ALLOW_CREDENTIALS`` says."""
    from django.conf import settings

    from karni_game import conf

    if not conf.get("KARNI_GAME_CORS_ORIGINS") or not apps.is_installed("corsheaders"):
        return []
    from corsheaders.defaults import default_headers

    header = str(conf.get("KARNI_GAME_TOKEN_HEADER")).lower()
    allowed = [
        str(name).lower() for name in getattr(settings, "CORS_ALLOW_HEADERS", default_headers)
    ]
    failures = []
    if header not in allowed:
        failures.append(
            f"{CORS_CODE}: KARNI_GAME_CORS_ORIGINS lets other origins call the game API, and "
            f"CORS_ALLOW_HEADERS leaves out {header}, so a guest's calls fail there. Set "
            f'CORS_ALLOW_HEADERS = (*default_headers, "{header}") (corsheaders.defaults).'
        )
    return failures
