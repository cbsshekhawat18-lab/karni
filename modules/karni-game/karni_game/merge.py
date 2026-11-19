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
from karni_game.models import Player, Save

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

    def merge_saves(self, keep: Player, drop: Player) -> dict[str, Any]:
        """A slot only ``drop`` has moves. A slot both have: the copy written last keeps it,
        the other moves to ``<slot>-merged`` (``-merged-2`` and on), so nothing is lost."""
        moved = 0
        kept_both: list[str] = []
        for theirs in Save.objects.filter(player=drop).order_by("game_id", "slot"):
            mine = Save.objects.filter(player=keep, game=theirs.game_id, slot=theirs.slot).first()
            if mine is None:
                Save.objects.filter(pk=theirs.pk).update(player=keep)
                moved += 1
                continue
            older, newer = (mine, theirs) if mine.updated_at < theirs.updated_at else (theirs, mine)
            taken = set(
                Save.objects.filter(player=keep, game=theirs.game_id).values_list("slot", flat=True)
            )
            name = self.free_slot(theirs.slot, taken)
            # The older copy steps aside first, so the newer one may take the slot.
            Save.objects.filter(pk=older.pk).update(player=keep, slot=name)
            Save.objects.filter(pk=newer.pk).update(player=keep, slot=theirs.slot)
            kept_both.append(theirs.slot)
        return {"moved": moved, "kept_both": kept_both}

    @staticmethod
    def free_slot(slot: str, taken: set[str]) -> str:
        """``<slot>-merged``, or ``-merged-2`` and on, that ``taken`` does not hold."""
        base = f"{slot[:33]}-merged"
        name, number = base, 1
        while name in taken:
            number += 1
            name = f"{base}-{number}"
        return name


def get_merger() -> Merger:
    """The :class:`Merger` ``KARNI_GAME_MERGER`` names (a class or a dotted path)."""
    value = conf.get("KARNI_GAME_MERGER") or "karni_game.merge.Merger"
    found = import_string(value) if isinstance(value, str) else value
    return found() if isinstance(found, type) else found
