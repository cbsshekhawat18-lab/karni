"""Cloud saves: versioned JSON per player, game and slot.

* :func:`write` stores a save only when the client's ``base_version`` is the
  server's version (``0`` for an empty slot), and makes the version one
  higher. Another version is ``409 GAME008`` with the server's copy, so a
  stale write from another device never wins, whatever the device clocks say.
* A save is a JSON object of at most the game's ``max_save_bytes``
  (``GAME007``), in at most ``max_slots`` slots (``GAME011``).
* ``schema_version`` is the shape of the data. When the game's
  ``save_schema_version`` is newer, the game's migrations
  (:func:`karni_game.hooks.save_migration`) bring an older save up to it, when
  it is read and when it is written. A newer one than the game's is
  ``GAME009``. A step nobody registered is ``GAME010``.

Every function takes the player the API found from the request, so a player
reaches only their own saves.

Override / escape hatch: register the migrations in ``<app>/game.py``; call
these functions from your own code with the player you hold.
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.db import IntegrityError, router, transaction
from django.db.models import F
from django.utils import timezone
from karni.exceptions import KarniImproperlyConfigured

from karni_game import hooks
from karni_game.errors import game_error
from karni_game.models import Game, Player, Save

__all__ = ["SLOT_RE", "as_data", "delete", "empty", "migrate", "read", "slots", "write"]

#: What a slot is called: a lowercase letter or digit, then up to 39 more (and _ -).
SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def as_data(save: Save | None, *, data: bool = True) -> dict[str, Any] | None:
    """A save as the API answers it."""
    if save is None:
        return None
    found: dict[str, Any] = {
        "slot": save.slot,
        "version": save.version,
        "schema_version": save.schema_version,
        "size": save.size,
        "updated_at": save.updated_at,
    }
    if data:
        found["data"] = save.data
    return found


def empty(slot: str) -> Exception:
    """``404 GAME037``: the player has no save in ``slot`` (not an unknown path)."""
    return game_error("GAME037", f"The player has no save in slot {slot!r}.", status=404)


def _slot(slot: str) -> str:
    if not SLOT_RE.match(slot or ""):
        raise game_error(
            "GAME011",
            f"{slot!r} is not a slot name: a lowercase letter or digit, then up to 39 more "
            "of those, _ or -.",
        )
    return slot


def migrate(game: Game, data: dict[str, Any], schema_version: int) -> tuple[dict[str, Any], int]:
    """``data`` of ``schema_version`` brought up to the game's ``save_schema_version``."""
    target = game.options().save_schema_version
    if schema_version < 1 or schema_version > target:
        raise game_error(
            "GAME009",
            f"schema_version {schema_version} is not one the server knows for {game.slug}: "
            f"from 1 to {target}.",
        )
    steps = hooks.save_migrations(game.slug)
    for version in range(schema_version, target):
        step = steps.get(version)
        if step is None:
            raise KarniImproperlyConfigured(
                f"Game {game.slug!r} saves schema version {target}, and no save migration "
                f"takes version {version} to {version + 1}. Register one in <app>/game.py: "
                f"@hooks.save_migration({game.slug!r}, {version}).",
                code="GAME010",
            )
        data = step(dict(data))
        if not isinstance(data, dict):
            raise KarniImproperlyConfigured(
                f"The save migration of {game.slug!r} from version {version} returned "
                f"{type(data).__name__}, not the save's data (a dict).",
                code="GAME010",
            )
    return data, target


def _size(game: Game, data: dict[str, Any]) -> int:
    size = len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    limit = game.options().max_save_bytes
    if size > limit:
        raise game_error(
            "GAME007",
            f"The save is {size} bytes, and {game.slug} keeps saves of up to {limit}.",
            status=413,
            size=size,
            max_bytes=limit,
        )
    return size


def _stale(game: Game, current: Save | None, base_version: int) -> Exception:
    server = current.version if current is not None else 0
    return game_error(
        "GAME008",
        f"The save changed on the server since version {base_version}: the server has "
        f"version {server}. Read it, choose, and write again with base_version {server}.",
        status=409,
        save=as_data(current),
    )


def slots(player: Player, game: Game) -> list[Save]:
    """The player's saves in the game, by slot."""
    return list(Save.objects.filter(player=player, game=game).order_by("slot"))


def read(player: Player, game: Game, slot: str) -> Save | None:
    """The player's save in ``slot``, brought up to the game's schema, or ``None``."""
    found = Save.objects.filter(player=player, game=game, slot=_slot(slot)).first()
    if found is None or found.schema_version >= game.options().save_schema_version:
        return found
    data, version = migrate(game, dict(found.data or {}), found.schema_version)
    updated = Save.objects.filter(pk=found.pk, version=found.version).update(
        data=data,
        schema_version=version,
        size=_size(game, data),
        version=F("version") + 1,
        updated_at=timezone.now(),
    )
    if not updated:  # written meanwhile: read the new one
        return read(player, game, slot)
    found.refresh_from_db()
    return found


def write(
    player: Player,
    game: Game,
    slot: str,
    data: Any,
    *,
    schema_version: int,
    base_version: int,
) -> Save:
    """Store ``data`` in the slot when ``base_version`` is the server's version (``0``: empty)."""
    _slot(slot)
    if not isinstance(data, dict):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"data": ["A save's data is a JSON object."]})
    data, version = migrate(game, data, schema_version)
    size = _size(game, data)
    with transaction.atomic(using=router.db_for_write(Save)):
        current = (
            Save.objects.select_for_update().filter(player=player, game=game, slot=slot).first()
        )
        if current is None:
            if base_version != 0:
                raise _stale(game, None, base_version)
            if Save.objects.filter(player=player, game=game).count() >= game.options().max_slots:
                raise game_error(
                    "GAME011",
                    f"The player has {game.options().max_slots} save slots in {game.slug} "
                    "already, the most it keeps. Write to one of them, or delete one.",
                )
            try:
                with transaction.atomic(using=router.db_for_write(Save)):
                    return Save.objects.create(
                        player=player,
                        game=game,
                        slot=slot,
                        data=data,
                        schema_version=version,
                        version=1,
                        size=size,
                    )
            except IntegrityError:  # another device made the slot first
                first = Save.objects.filter(player=player, game=game, slot=slot).first()
                raise _stale(game, first, base_version) from None
        if current.version != base_version:
            raise _stale(game, current, base_version)
        updated = Save.objects.filter(pk=current.pk, version=base_version).update(
            data=data,
            schema_version=version,
            size=size,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )
        if not updated:  # pragma: no cover - the row lock makes this a database without locks
            raise _stale(game, Save.objects.filter(pk=current.pk).first(), base_version)
    current.refresh_from_db()
    return current


def delete(player: Player, game: Game, slot: str, *, base_version: int | None = None) -> bool:
    """Delete the save in ``slot`` (at ``base_version`` when given). ``False``: none there."""
    with transaction.atomic(using=router.db_for_write(Save)):
        current = (
            Save.objects.select_for_update()
            .filter(player=player, game=game, slot=_slot(slot))
            .first()
        )
        if current is None:
            return False
        if base_version is not None and current.version != base_version:
            raise _stale(game, current, base_version)
        current.delete()
    return True
