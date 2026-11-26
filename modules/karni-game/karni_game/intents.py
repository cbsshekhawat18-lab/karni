"""Retries that never count twice: a write's ``intent``.

A client makes one ``intent`` per action (a score, a claim, a purchase, a
progress report) and sends it again on every retry. :func:`once` runs the
work the first time and keeps its answer. A retry with the same body gets
that answer again (``replayed``), and the same intent with another body is
``409 GAME033``. The work and the mark commit together, so a refused or
failed first try leaves the intent free.

Override / escape hatch: ``KARNI_GAME_INTENT_DAYS`` keeps them longer or
shorter, and :func:`prune` (the task ``karni_game.tasks.prune_intents``)
deletes the old ones.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, router, transaction
from django.utils import timezone

from karni_game import conf
from karni_game.errors import game_error
from karni_game.models import Intent, Player

__all__ = ["INTENT_RE", "Outcome", "check_key", "digest_of", "once", "prune", "used"]

#: What an intent may be.
INTENT_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

Outcome = tuple[int, dict[str, Any], bool]


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def digest_of(body: Any) -> str:
    """The digest an intent keeps of its request's body."""
    return _digest(body)


def _digest(body: Any) -> str:
    text = json.dumps(body, sort_keys=True, cls=DjangoJSONEncoder, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_key(key: str) -> str:
    """``key`` when it is an intent, else a 400 on the field."""
    if not INTENT_RE.match(key):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"intent": ["8 to 64 letters, digits, _ or -."]})
    return key


def used(key: str) -> Exception:
    return game_error(
        "GAME033",
        f"The intent {key!r} was used already with another request. Make a new intent for a "
        "new action, and send the same body when you retry one.",
        status=409,
    )


def once(
    player: Player | None,
    kind: str,
    key: str | None,
    body: Any,
    work: Callable[[], tuple[int, dict[str, Any]]],
) -> Outcome:
    """``(status, answer, replayed)``: the work's answer, or the first one for a retry.

    ``player`` ``None`` keys the intent among the calls without a player.
    """
    if not key:
        status, answer = work()
        return status, answer, False
    check_key(key)
    digest = _digest(body)
    with transaction.atomic(using=router.db_for_write(Intent)):
        try:
            with transaction.atomic(using=router.db_for_write(Intent)):
                row = Intent.objects.create(player=player, kind=kind, key=key, digest=digest)
        except IntegrityError:
            row = Intent.objects.select_for_update().get(player=player, kind=kind, key=key)
            if row.digest != digest:
                raise used(key) from None
            return row.status, dict(row.response), True
        status, answer = work()
        row.status = status
        row.response = _plain(answer)
        row.save(update_fields=["status", "response", "updated_at"])
    return status, answer, False


def prune(days: int | None = None) -> int:
    """Delete the intents older than ``days`` (``KARNI_GAME_INTENT_DAYS``); returns how many."""
    keep = int(days if days is not None else conf.get("KARNI_GAME_INTENT_DAYS"))
    deleted, _ = Intent.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=keep)
    ).delete()
    return int(deleted)
