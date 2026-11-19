"""Experimental. What karni-game tells the people contract: a person's player.

``karni.people`` imports this module at startup (``<app>/people.py``):

* **Merge.** Two people merged (a guest who signed in, or staff merging two
  people) keep one player. When only the dropped person has one, it moves to
  the kept person. When both have one, :class:`karni_game.merge.Merger` folds
  the dropped player's progress into the kept one's.
* **Erase.** A person who asks for their data to be erased is on no board
  any more, and loses the handle (it reads "Erased player"), the guest
  token, their saves, their run records and their ledger notes. The scores,
  the balances and the amounts in the ledger stay, so the books still add up.
* **A fact.** ``game_last_seen``: when the person last played.

Override / escape hatch: ``people.merge_hook(Player, replace=True)`` and
``people.erase_hook("karni_game.erase", replace=True)`` swap these, and
``KARNI_GAME_MERGER`` changes only the rules of the merge.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.utils import timezone
from karni import people

from karni_game.merge import get_merger
from karni_game.models import Player

__all__ = ["ERASED_HANDLE", "erase_player", "merge_players"]

#: What the boards show for a person whose data was erased.
ERASED_HANDLE = "Erased player"


@people.merge_hook(Player)
def merge_players(keep: Any, drop: Any) -> None:
    """Both people have a player: fold the dropped one in. Else the move does it."""
    from karni_game.players import remember_merge

    kept = Player.objects.filter(person=keep).first()
    dropped = Player.objects.filter(person=drop).first()
    if dropped is None:
        remember_merge({})
        return
    if kept is None:
        # The guest's player becomes the account's: the people merge moves it.
        Player.objects.filter(pk=dropped.pk).update(token_hash="")
        remember_merge({})
        return
    remember_merge(get_merger().merge(kept, dropped))


@people.erase_hook("karni_game.erase")
def erase_player(person: Any) -> None:
    """Anonymise the person's player and drop what only identified them."""
    from karni.people.services import redact_history

    players = list(Player._base_manager.filter(person=person).values_list("pk", flat=True))
    if not players:
        return
    Player._base_manager.filter(pk__in=players).update(
        handle=ERASED_HANDLE, token_hash="", ban_reason=""
    )
    redact_history(Player, players, fields=["handle", "ban_reason"])
    for label, fields in _ERASED_ROWS:
        if not apps.is_installed("karni_game"):  # pragma: no cover
            return
        model = apps.get_model("karni_game", label)
        rows = model._base_manager.filter(player__in=players)
        rows.update(**fields)
        if label == "Save":
            rows.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
    ledger = apps.get_model("karni_game", "LedgerEntry")
    ledger.objects.filter(wallet__player__in=players).update(note="")


#: Rows of a player's that an erase rewrites: (model, the values written). Saves lose
#: their data and are deleted.
_ERASED_ROWS: list[tuple[str, dict[str, Any]]] = [
    ("Save", {"data": {}, "size": 0}),
    ("Score", {"run": None, "note": ""}),
]


people.register_fact(
    "game_last_seen",
    people.latest_of(Player, "last_seen_at"),
    label="Last played",
    kind="datetime",
    description="When the person last played a game of the project.",
    replace=True,
)
