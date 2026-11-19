"""Experimental. How two players become one: a guest who signs in, or two people merged.

The people contract calls the merge hook of :class:`~karni_game.models.Player`
(:mod:`karni_game.people`) inside ``people.merge``. When only the dropped
person has a player, the player simply moves to the kept person. When both
have one, :class:`Merger` folds the dropped player into the kept one, part
by part, and soft-deletes it. docs/game-api.md (``POST upgrade/``) lists the
rules.

Override / escape hatch: subclass :class:`Merger`, override the part whose
rule your game wants otherwise (``merge_saves`` to keep only the newest, say),
and name it in ``KARNI_GAME_MERGER``. Each part returns what it reports in
the upgrade's ``merged`` summary.
"""

from __future__ import annotations

from typing import Any

from django.utils.module_loading import import_string

from karni_game import conf
from karni_game.models import Player

__all__ = ["Merger", "get_merger"]


class Merger:
    """The merge rules, one method per part of a player's progress."""

    #: The parts, in the order they merge. A subclass may drop or add one.
    parts: tuple[str, ...] = (
        "saves",
        "scores",
        "currencies",
        "items",
        "unlocks",
        "streaks",
        "claims",
    )

    def merge(self, keep: Player, drop: Player) -> dict[str, Any]:
        """Fold ``drop`` into ``keep``; returns the summary, by part."""
        summary: dict[str, Any] = {}
        for part in self.parts:
            method = getattr(self, f"merge_{part}", None)
            if method is not None:
                summary[part] = method(keep, drop)
        Player.objects.filter(pk=drop.pk).update(token_hash="")
        drop.token_hash = ""
        drop.delete()
        return summary


def get_merger() -> Merger:
    """The :class:`Merger` ``KARNI_GAME_MERGER`` names (a class or a dotted path)."""
    value = conf.get("KARNI_GAME_MERGER") or "karni_game.merge.Merger"
    found = import_string(value) if isinstance(value, str) else value
    return found() if isinstance(found, type) else found
