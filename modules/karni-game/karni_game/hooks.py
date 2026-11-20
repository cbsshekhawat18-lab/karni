"""Experimental. What a project's code adds to a game: save migrations and run checks.

Each installed app's ``game.py`` is imported at startup (``KarniGameConfig.ready``),
the place for these registrations::

    # games/game.py
    from karni_game import hooks


    @hooks.save_migration("block-hopper", 1)
    def levels_become_a_list(data):
        # schema version 1 to 2: {"level": 3} becomes {"levels": [1, 2, 3]}
        return {**data, "levels": list(range(1, data.pop("level", 0) + 1))}


    @hooks.run_check("block-hopper", "high")
    def replay(score, run):
        # "accept", "flag" (held for staff) or "reject" (GAME014)
        return "accept" if run and run.get("duration_ms", 0) > 1000 else "flag"

A save migration takes the ``data`` of schema version ``n`` and returns the
data of ``n + 1``. When the game's ``save_schema_version`` is newer than a
save, the server runs each step in order. A run check sees a score before it
is stored, with its run record, and says whether it counts.

Override / escape hatch: ``KARNI_GAME_AUTODISCOVER = False`` stops the
import; call the same functions from your own ``AppConfig.ready()``.
``replace=True`` swaps a registration on purpose, :func:`clear` empties the
registries (tests).
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from django.apps import apps
from django.utils.module_loading import module_has_submodule
from karni.exceptions import KarniImproperlyConfigured

from karni_game import conf

__all__ = [
    "RUN_VERDICTS",
    "autodiscover",
    "clear",
    "run_check",
    "run_check_for",
    "save_migration",
    "save_migrations",
]

#: What a run check may answer.
RUN_VERDICTS = ("accept", "flag", "reject")

Migration = Callable[[dict[str, Any]], dict[str, Any]]
RunCheck = Callable[[Any, dict[str, Any] | None], str]

_MIGRATIONS: dict[tuple[str, int], Migration] = {}
_RUN_CHECKS: dict[tuple[str, str], RunCheck] = {}

#: A registration the server cannot use.
HOOK_CODE = "GAME032"


def save_migration(
    game: str, from_version: int, *, replace: bool = False
) -> Callable[[Migration], Migration]:
    """Register the step from schema version ``from_version`` to the next of ``game``'s saves."""
    if not isinstance(from_version, int) or from_version < 1:
        raise KarniImproperlyConfigured(
            f"save_migration({game!r}, {from_version!r}): the version a step starts from is a "
            "whole number from 1.",
            code=HOOK_CODE,
        )

    def decorate(function: Migration) -> Migration:
        key = (game, from_version)
        if key in _MIGRATIONS and not replace and _MIGRATIONS[key] is not function:
            raise KarniImproperlyConfigured(
                f"{game!r} has a save migration from version {from_version} already "
                f"({_MIGRATIONS[key].__module__}.{_MIGRATIONS[key].__qualname__}). Pass "
                "replace=True to swap it.",
                code=HOOK_CODE,
            )
        _MIGRATIONS[key] = function
        return function

    return decorate


def save_migrations(game: str) -> dict[int, Migration]:
    """``game``'s save migrations, by the version each starts from."""
    return {version: fn for (slug, version), fn in _MIGRATIONS.items() if slug == game}


def run_check(game: str, board: str, *, replace: bool = False) -> Callable[[RunCheck], RunCheck]:
    """Register ``check(score, run) -> "accept" | "flag" | "reject"`` for a board of a game.

    ``board`` ``"*"`` checks every board of the game that has no check of its own.
    """

    def decorate(function: RunCheck) -> RunCheck:
        key = (game, board)
        if key in _RUN_CHECKS and not replace and _RUN_CHECKS[key] is not function:
            raise KarniImproperlyConfigured(
                f"Board {board!r} of {game!r} has a run check already "
                f"({_RUN_CHECKS[key].__module__}.{_RUN_CHECKS[key].__qualname__}). Pass "
                "replace=True to swap it.",
                code=HOOK_CODE,
            )
        _RUN_CHECKS[key] = function
        return function

    return decorate


def run_check_for(game: str, board: str) -> RunCheck | None:
    """The run check of a board: its own, else the game's ``"*"``, else ``None``."""
    return _RUN_CHECKS.get((game, board)) or _RUN_CHECKS.get((game, "*"))


def clear() -> None:
    """Empty both registries (for tests that register their own)."""
    _MIGRATIONS.clear()
    _RUN_CHECKS.clear()


def autodiscover() -> list[str]:
    """Import ``<app>/game.py`` of every installed app; returns the modules imported."""
    if not conf.get("KARNI_GAME_AUTODISCOVER"):
        return []
    imported: list[str] = []
    for config in apps.get_app_configs():
        if config.name == "karni_game" or config.module is None:
            continue
        if module_has_submodule(config.module, "game"):
            name = f"{config.name}.game"
            import_module(name)
            imported.append(name)
    return imported
