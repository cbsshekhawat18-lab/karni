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

from django.db.models import F
from django.utils.module_loading import import_string

from karni_game import conf
from karni_game.models import (
    Claim,
    Completion,
    Ownership,
    Player,
    Progress,
    Save,
    Score,
    Streak,
    Unlock,
    Wallet,
)

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

    def merge_scores(self, keep: Player, drop: Player) -> int:
        """Every score moves, and each board keeps the better best of the two."""
        from karni_game import scores
        from karni_game.models import Best, Board

        boards = list(Board.objects.filter(scores__player__in=[keep, drop]).distinct())
        moved = Score.objects.filter(player=drop).update(player=keep)
        Best.objects.filter(player=drop).delete()
        scores.rebuild(keep, boards)
        return int(moved)

    def merge_currencies(self, keep: Player, drop: Player) -> dict[str, int]:
        """Each currency's balances add up, capped. The ledger records both moves."""
        from karni_game import wallet

        moved: dict[str, int] = {}
        for theirs in Wallet.objects.filter(player=drop).select_related("currency"):
            if theirs.balance:
                wallet.change(
                    drop,
                    theirs.currency,
                    -theirs.balance,
                    reason="merge",
                    reference=str(keep.pk),
                )
                done = wallet.change(
                    keep,
                    theirs.currency,
                    theirs.balance,
                    reason="merge",
                    reference=str(drop.pk),
                )
                moved[theirs.currency.key] = done.amount
        return moved

    def merge_items(self, keep: Player, drop: Player) -> int:
        """The kept player owns every item either owned. What it equipped stays equipped,
        and the dropped player's choice fills a slot it left empty."""
        mine = {row.item_id: row for row in Ownership.objects.filter(player=keep)}
        worn = set(
            Ownership.objects.filter(player=keep, equipped=True).values_list("slot", flat=True)
        )
        moved = 0
        for theirs in Ownership.objects.filter(player=drop):
            if theirs.item_id in mine:
                continue
            equipped = theirs.equipped and theirs.slot not in worn
            Ownership.objects.filter(pk=theirs.pk).update(player=keep, equipped=equipped)
            if equipped:
                worn.add(theirs.slot)
            moved += 1
        return moved

    def merge_unlocks(self, keep: Player, drop: Player) -> int:
        """The progress of each counter adds up. An unlock or a completed mission of either
        stays, with the earlier time."""
        for theirs in Progress.objects.filter(player=drop):
            mine = Progress.objects.filter(
                player=keep,
                game=theirs.game_id,
                counter=theirs.counter,
                period=theirs.period,
                period_start=theirs.period_start,
            ).first()
            if mine is None:
                Progress.objects.filter(pk=theirs.pk).update(player=keep)
            else:
                Progress.objects.filter(pk=mine.pk).update(value=F("value") + theirs.value)
                theirs.delete()
        moved = 0
        for unlock in Unlock.objects.filter(player=drop):
            mine_unlock = Unlock.objects.filter(player=keep, achievement=unlock.achievement_id)
            kept = mine_unlock.first()
            if kept is None:
                Unlock.objects.filter(pk=unlock.pk).update(player=keep)
                moved += 1
            else:
                if unlock.created_at < kept.created_at:
                    mine_unlock.update(created_at=unlock.created_at)
                unlock.delete()
        for done in Completion.objects.filter(player=drop):
            twin = Completion.objects.filter(
                player=keep, mission=done.mission_id, period_start=done.period_start
            )
            if twin.exists():
                done.delete()
            else:
                Completion.objects.filter(pk=done.pk).update(player=keep)
        return moved

    def merge_streaks(self, keep: Player, drop: Player) -> int:
        """The longer streak stays, and the best of the two."""
        merged = 0
        for theirs in Streak.objects.filter(player=drop):
            mine = Streak.objects.filter(player=keep, game=theirs.game_id).first()
            if mine is None:
                Streak.objects.filter(pk=theirs.pk).update(player=keep)
            else:
                if theirs.current > mine.current:
                    mine.current, mine.last_day = theirs.current, theirs.last_day
                mine.best = max(mine.best, theirs.best, mine.current)
                mine.save(update_fields=["current", "best", "last_day", "updated_at"])
                theirs.delete()
            merged += 1
        return merged

    def merge_claims(self, keep: Player, drop: Player) -> int:
        """Both histories stay, so a daily reward is not claimed twice on one day."""
        return int(Claim.objects.filter(player=drop).update(player=keep))

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
