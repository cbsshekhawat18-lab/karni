"""Experimental. Rewards the server declares and grants: daily, ad, mission, match, staff.

A client never names an amount: it asks for a reward by its key, and
:func:`claim` checks what the reward allows. A client claims only an ``ad``
reward without ``callback`` (``GAME018`` for the rest), within its
``per_day`` cap and ``cooldown`` (``409 GAME017`` with ``next_at``). An ``ad``
reward with ``callback`` is granted when the portal's server calls back,
signed (:func:`from_callback`), once per portal event. Missions,
achievements, matches and the daily check-in call :func:`grant`.

Every grant is a :class:`~karni_game.models.Claim` (on the game's day) and a
ledger entry (:func:`karni_game.wallet.change`, reason ``reward`` or the
kind's).

Override / escape hatch: a reward is a row staff edit; :func:`grant` from your
own code for a reward of your game's own kind.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.core import signing
from django.db import IntegrityError, router, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from karni_game import clock, conf, wallet
from karni_game.errors import game_error
from karni_game.models import Claim, Game, Player, Reward
from karni_game.signatures import HmacVerifier

__all__ = [
    "Granted",
    "availability",
    "claim",
    "find_reward",
    "from_callback",
    "grant",
    "intent_for",
    "reward_data",
]

#: The ledger reason of each kind.
REASONS = {"mission": "mission", "achievement": "achievement", "match": "match", "grant": "grant"}
INTENT_SALT = "karni_game.rewards.ad_intent"


def find_reward(game: Game, key: str) -> Reward:
    found = (
        Reward.objects.select_related("currency").filter(game=game, key=key, is_active=True).first()
    )
    if found is None:
        from rest_framework.exceptions import NotFound

        raise NotFound(f"{game.slug} has no active reward {key!r}.")
    return found


def availability(player: Player, reward: Reward, at: datetime | None = None) -> dict[str, Any]:
    """Whether the player may have ``reward`` now: ``available``, ``claimed_today``, ``next_at``."""
    now = at or timezone.now()
    game = reward.game
    today = clock.today(game, now)
    rows = Claim.objects.filter(player=player, reward=reward)
    claimed_today = rows.filter(day=today).count()
    per_day = 1 if reward.kind == "daily" else reward.per_day
    next_at: datetime | None = None
    if per_day is not None and claimed_today >= per_day:
        next_at = clock.resets_at(game, now)
    if reward.cooldown:
        last = rows.order_by("-created_at").values_list("created_at", flat=True).first()
        if last is not None and last + timedelta(seconds=reward.cooldown) > now:
            ready = last + timedelta(seconds=reward.cooldown)
            next_at = max(next_at, ready) if next_at else ready
    return {"available": next_at is None, "claimed_today": claimed_today, "next_at": next_at}


def reward_data(reward: Reward, player: Player | None) -> dict[str, Any]:
    found: dict[str, Any] = {
        "key": reward.key,
        "title": reward.title,
        "kind": reward.kind,
        "currency": reward.currency.key,
        "amount": reward.amount,
        "callback": reward.callback,
        "per_day": 1 if reward.kind == "daily" else reward.per_day,
    }
    if player is not None:
        found.update(availability(player, reward))
    return found


@dataclass(frozen=True)
class Granted:
    """A reward granted: the claim, and the ledger's change."""

    claim: Claim
    change: wallet.Change

    def as_dict(self) -> dict[str, Any]:
        return {
            "granted": self.change.as_dict(),
            "capped": self.change.capped,
        }


def grant(
    player: Player,
    reward: Reward,
    *,
    source: str = "server",
    external_id: str = "",
    reference: str = "",
    actor: Any = None,
) -> Granted:
    """Grant ``reward`` to the player: a claim on the game's day and a ledger entry."""
    with transaction.atomic(using=router.db_for_write(Claim)):
        change = wallet.change(
            player,
            reward.currency,
            int(reward.amount),
            reason=REASONS.get(reward.kind, "reward"),
            reference=reference or reward.key,
            intent=external_id,
            actor=actor,
        )
        row = Claim.objects.create(
            player=player,
            reward=reward,
            day=clock.today(reward.game),
            amount=change.amount,
            source=source,
            external_id=external_id[:128],
        )
    return Granted(claim=row, change=change)


def _wait(reward: Reward, next_at: Any) -> Exception:
    return game_error(
        "GAME017",
        f"The reward {reward.key} is not available now.",
        status=409,
        next_at=next_at,
    )


def claim(player: Player, reward: Reward) -> Granted:
    """A client's claim of an ``ad`` reward without ``callback``."""
    if reward.kind != "ad" or reward.callback:
        how = (
            "the portal's signed callback grants it"
            if reward.callback
            else f"a {reward.kind} reward is granted by the server"
        )
        raise game_error(
            "GAME018", f"The reward {reward.key} is not claimed by the client: {how}.", status=403
        )
    with transaction.atomic(using=router.db_for_write(Claim)):
        # One claim at a time per player: the wallet row is the lock.
        wallet.Wallet.objects.select_for_update().filter(
            pk=wallet.wallet_of(player, reward.currency).pk
        ).first()
        state = availability(player, reward)
        if not state["available"]:
            raise _wait(reward, state["next_at"])
        return grant(player, reward, source="client")


def intent_for(player: Player, reward: Reward) -> dict[str, Any]:
    """A signed intent the portal sends back in its callback (``ad`` rewards with ``callback``)."""
    if reward.kind != "ad" or not reward.callback:
        raise game_error(
            "GAME018",
            f"The reward {reward.key} has no portal callback: claim it with POST claim/.",
            status=403,
        )
    seconds = int(conf.get("KARNI_GAME_AD_INTENT_SECONDS"))
    token = signing.dumps(
        {"p": str(player.pk), "r": str(reward.pk), "n": secrets.token_hex(8)},
        salt=INTENT_SALT,
        compress=True,
    )
    return {"intent": token, "expires_at": timezone.now() + timedelta(seconds=seconds)}


def verifier_for(portal: str) -> HmacVerifier:
    """The verifier of a portal named in ``KARNI_GAME_PORTALS`` (``GAME019`` for another)."""
    portals = dict(conf.get("KARNI_GAME_PORTALS") or {})
    found = portals.get(portal)
    if not isinstance(found, dict):
        raise game_error(
            "GAME019", f"No portal {portal!r} is set up (KARNI_GAME_PORTALS).", status=403
        )
    path = found.get("verifier") or "karni_game.signatures.HmacVerifier"
    cls = import_string(path) if isinstance(path, str) else path
    return cls(str(found.get("secret") or ""))


def from_callback(portal: str, intent: str, event_id: str) -> dict[str, Any]:
    """A portal's callback, its signature verified: grant the intent's reward once per event."""
    seconds = int(conf.get("KARNI_GAME_AD_INTENT_SECONDS"))
    try:
        payload = signing.loads(intent, salt=INTENT_SALT, max_age=seconds)
    except signing.BadSignature as exc:  # SignatureExpired is one
        raise game_error(
            "GAME020", "The intent is not one this server made, or it has expired."
        ) from exc
    player = Player.objects.select_related("person").filter(pk=payload.get("p")).first()
    reward = (
        Reward.objects.select_related("currency", "game")
        .filter(pk=payload.get("r"), is_active=True)
        .first()
    )
    if player is None or reward is None:
        raise game_error("GAME020", "The intent's player or reward is gone.")
    external = f"{portal}:{event_id}"[:128]
    if Claim.objects.filter(reward=reward, external_id=external).exists():
        return {"granted": False, "duplicate": True}
    try:
        with transaction.atomic(using=router.db_for_write(Claim)):
            state = availability(player, reward)
            if not state["available"]:
                raise _wait(reward, state["next_at"])
            grant(player, reward, source="callback", external_id=external)
    except IntegrityError:
        return {"granted": False, "duplicate": True}
    return {"granted": True, "duplicate": False}
