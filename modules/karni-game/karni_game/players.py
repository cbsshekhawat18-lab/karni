"""Experimental. Who is playing: guests, accounts, and a guest who signs in.

* :func:`issue_guest` makes a person with no account, its player and a token.
  The token is returned once and kept as its SHA-256.
* :func:`player_for_user` is the player of a signed-in account: the player
  of the person linked to it, made on first use. An account is linked to a
  person only once its email is verified (``GAME004`` before).
* :func:`player_for_token` is the guest a token was issued to (``GAME003``).
* :func:`upgrade` keeps a guest's progress on the account: the guest's person
  is merged into the account's person (``people.merge``), and the merge hook
  of :class:`~karni_game.models.Player` (:mod:`karni_game.people`) merges the
  two players by the rules of :class:`karni_game.merge.Merger`.

No function here takes a player's id from a client: the API finds the player
from the request alone.

Override / escape hatch: ``KARNI_GAME_MERGER`` names the merge rules,
``KARNI_GAME_TOKEN_HEADER`` the guest's header, and :func:`default_handle`
is what a new player is called.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, router, transaction
from django.utils import timezone
from karni import people
from karni.events import publish
from karni.people.models import Person

from karni_game.errors import game_error
from karni_game.models import Player

__all__ = [
    "HANDLE_RE",
    "GuestIssued",
    "Upgraded",
    "default_handle",
    "issue_guest",
    "player_for_person",
    "player_for_token",
    "player_for_user",
    "revoke_token",
    "token_hash",
    "upgrade",
]

#: What a handle may hold: letters, digits, spaces, _, - and ., 2 to 32 characters.
HANDLE_RE = re.compile(r"^[\w .\-]{2,32}$")
#: How stale ``last_seen_at`` may be before a call writes it again.
SEEN_EVERY = timedelta(minutes=5)
TOKEN_PREFIX = "gt_"
SOURCE = "karni_game"

#: What the last merge of two players did (read by :func:`upgrade`).
_merged: ContextVar[dict[str, Any] | None] = ContextVar("karni_game_merged", default=None)


def token_hash(token: str) -> str:
    """The SHA-256 of a guest token, as stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_handle() -> str:
    """A new player's handle: ``Player`` and four digits. The player changes it."""
    return f"Player {secrets.randbelow(9000) + 1000}"


def clean_handle(value: str) -> str:
    """``value`` stripped, or ``400`` when it is not a handle (:data:`HANDLE_RE`)."""
    handle = " ".join(str(value or "").split())
    if not HANDLE_RE.match(handle):
        from rest_framework.exceptions import ValidationError

        raise ValidationError(
            {"handle": ["2 to 32 letters, digits, spaces, _, - or ."]}, code="invalid"
        )
    return handle


@dataclass(frozen=True)
class GuestIssued:
    """A new guest: its token (shown once) and its player. ``replayed`` for a retry."""

    token: str
    player: Player
    replayed: bool = False


#: How long a guest's intent gives the same guest again, in seconds (then GAME033).
GUEST_INTENT_SECONDS = 3600


def _new_token(player: Player) -> str:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    Player.objects.filter(pk=player.pk).update(
        token_hash=token_hash(token), token_issued_at=timezone.now()
    )
    player.token_hash = token_hash(token)
    return token


def issue_guest(handle: str = "", *, intent: str = "") -> GuestIssued:
    """Make a guest: a person with no account, its player and a token.

    With ``intent``, a retry within an hour gives the same guest, with a new
    token (the server never keeps a token, and the first answer was lost): a
    lost answer never makes a second guest.
    """
    if intent:
        return _issue_once(handle, intent)
    return _issue(handle)


def _issue_once(handle: str, key: str) -> GuestIssued:
    from karni_game import intents
    from karni_game.models import Intent

    intents.check_key(key)
    digest = intents.digest_of({"handle": handle})
    with transaction.atomic(using=router.db_for_write(Intent)):
        try:
            with transaction.atomic(using=router.db_for_write(Intent)):
                row = Intent.objects.create(player=None, kind="guest", key=key, digest=digest)
        except IntegrityError:
            row = Intent.objects.select_for_update().get(player=None, kind="guest", key=key)
            fresh = timezone.now() - row.created_at < timedelta(seconds=GUEST_INTENT_SECONDS)
            found = (
                Player.objects.select_related("person")
                .filter(pk=row.response.get("player"), person__user__isnull=True)
                .first()
            )
            if row.digest != digest or not fresh or found is None:
                raise intents.used(key) from None
            return GuestIssued(token=_new_token(found), player=found, replayed=True)
        issued = _issue(handle)
        row.status = 201
        row.response = {"player": str(issued.player.pk)}  # never the token
        row.save(update_fields=["status", "response", "updated_at"])
    return issued


def _issue(handle: str) -> GuestIssued:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    name = clean_handle(handle) if handle else default_handle()
    with transaction.atomic(using=router.db_for_write(Player)):
        person = Person.objects.create(display_name=f"Guest: {name}"[:300], source=SOURCE)
        player = Player.objects.create(
            person=person,
            handle=name,
            token_hash=token_hash(token),
            token_issued_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        publish(
            "game.player.joined",
            subject=player,
            person=person,
            player=str(player.pk),
            game="",
            guest=True,
        )
    return GuestIssued(token=token, player=player)


def _seen(player: Player) -> Player:
    now = timezone.now()
    if player.last_seen_at is None or now - player.last_seen_at > SEEN_EVERY:
        Player.objects.filter(pk=player.pk).update(last_seen_at=now)
        player.last_seen_at = now
    return player


def player_for_token(token: str) -> Player:
    """The guest ``token`` was issued to. ``GAME003`` (401) when there is none."""
    found = None
    if token and token.startswith(TOKEN_PREFIX):
        found = (
            Player.objects.select_related("person")
            .filter(token_hash=token_hash(token), person__user__isnull=True)
            .first()
        )
    if found is None:
        raise game_error(
            "GAME003",
            "This guest token is unknown or was revoked (the guest was upgraded to an "
            "account, or staff revoked it).",
            status=401,
        )
    return _seen(found)


def player_for_person(person: Person, *, create: bool = True) -> Player | None:
    """``person``'s player, made when it has none and ``create``."""
    found = Player.objects.select_related("person").filter(person=person).first()
    if found is not None or not create:
        return found
    try:
        with transaction.atomic(using=router.db_for_write(Player)):
            found = Player.objects.create(
                person=person, handle=default_handle(), last_seen_at=timezone.now()
            )
            publish(
                "game.player.joined",
                subject=found,
                person=person,
                player=str(found.pk),
                game="",
                guest=person.user_id is None,
            )
    except IntegrityError:  # another request made it first
        found = Player.objects.select_related("person").get(person=person)
    return found


def _person_of(user: Any) -> Person:
    person = Person.objects.filter(user=user).first()
    if person is None:
        person = people.link_account(user, strict=False)
    if person is None:
        raise game_error(
            "GAME004",
            "This account's email is not verified, so no person is linked to it yet, and a "
            "player belongs to a person. Verify the email, then call again.",
            status=403,
        )
    return person


def player_for_user(user: Any) -> Player:
    """The player of a signed-in account (made on first use). ``GAME004`` when unverified."""
    player = player_for_person(_person_of(user))
    if player is None:  # pragma: no cover - create=True always gives one
        raise game_error("GAME004", "No player for this account.", status=403)
    return _seen(player)


def revoke_token(player: Player) -> None:
    """The guest's token no longer works."""
    Player.objects.filter(pk=player.pk).update(token_hash="")
    player.token_hash = ""


@dataclass
class Upgraded:
    """What :func:`upgrade` did: the account's player now, and what moved."""

    player: Player
    merged: dict[str, Any] = field(default_factory=dict)


def remember_merge(summary: dict[str, Any]) -> None:
    """Called by the Player merge hook: what the merge of two players did."""
    _merged.set(summary)


def upgrade(user: Any, token: str) -> Upgraded:
    """Keep the guest of ``token`` on ``user``'s account (``GAME002``, ``GAME004``, ``GAME028``)."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise game_error(
            "GAME002", "An upgrade needs the account: sign in first, then upgrade.", status=401
        )
    if not token:
        raise game_error(
            "GAME028",
            "Name the guest to keep: its token in X-Player-Token or as guest_token.",
            status=409,
        )
    guest = player_for_token(token)
    if not guest.is_guest:  # pragma: no cover - player_for_token finds guests only
        raise game_error("GAME028", "This token's player is an account already.", status=409)
    account = _person_of(user)
    if account.pk == guest.person_id:  # pragma: no cover - a guest's person has no account
        raise game_error("GAME028", "The guest is this account already.", status=409)
    using = router.db_for_write(Player)
    with transaction.atomic(using=using):
        had_player = Player.objects.filter(person=account).exists()
        _merged.set(None)
        try:
            people.merge(account, guest.person)
        except people.MergeRefused as exc:
            raise game_error(
                "GAME028",
                f"The guest's person cannot be merged into the account's: {exc.message}",
                status=409,
            ) from exc
        player = Player.objects.select_related("person").get(person=account)
        revoke_token(player)
        summary = dict(_merged.get() or {})
        summary["adopted"] = not had_player
        publish(
            "game.player.upgraded",
            subject=player,
            person=account,
            player=str(player.pk),
            user=str(user.pk),
            adopted=not had_player,
        )
    return Upgraded(player=player, merged=summary)
