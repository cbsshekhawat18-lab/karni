"""The contract with a realtime game server of the project's own.

Karni runs no realtime server: a match server is a separate service (any
language), and two calls join it to the player and the boards:

* :func:`issue_token`: a short-lived JSON Web Token (HS256, signed with
  ``KARNI_GAME_SERVER_SECRET``) that names the player (``sub``), the game
  (``aud`` ``game:<slug>``) and the handle. The client hands it to the game
  server when it connects. The game server verifies it with any JWT library
  and the shared secret, and trusts ``sub`` as the player's id.
* :func:`report`: the game server's signed report of a finished match
  (:mod:`karni_game.signatures`). It records the scores (each checked against
  its board's range) and grants the ``match`` rewards it names, all or
  nothing, and records each ``match`` once.

docs/game-api.md (Multiplayer) is the contract for the game server's side.

Override / escape hatch: ``KARNI_GAME_TOKEN_SECONDS`` and
``KARNI_GAME_TOKEN_ISSUER`` change the token, :func:`claims` is what it holds
(subclass nothing: call :func:`issue_token` with ``extra`` claims from your
own view), and a project that wants keys instead of a shared secret signs its
own token from :func:`claims`.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from django.db import IntegrityError, router, transaction
from django.utils import timezone
from karni.events import publish

from karni_game import conf, rewards, scores
from karni_game.errors import game_error
from karni_game.models import Board, Game, Match, Player, Reward
from karni_game.signatures import HmacVerifier

__all__ = ["claims", "issue_token", "report", "secret", "verifier", "verify_token"]


def secret() -> str:
    """``KARNI_GAME_SERVER_SECRET``, or ``503 GAME027`` when the project has none."""
    value = str(conf.get("KARNI_GAME_SERVER_SECRET") or "")
    if not value:
        raise game_error(
            "GAME027",
            "Multiplayer is not set up: KARNI_GAME_SERVER_SECRET is blank, so no game server "
            "could verify a token.",
            status=503,
        )
    return value


def verifier() -> HmacVerifier:
    """The verifier of the game server's signed reports."""
    return HmacVerifier(secret())


def claims(player: Player, game: Game, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the player token holds (docs/game-api.md, the claims table)."""
    now = timezone.now()
    seconds = int(conf.get("KARNI_GAME_TOKEN_SECONDS"))
    return {
        "iss": str(conf.get("KARNI_GAME_TOKEN_ISSUER")),
        "aud": f"game:{game.slug}",
        "sub": str(player.pk),
        "name": player.handle,
        "guest": player.is_guest,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=seconds)).timestamp()),
        "jti": secrets.token_hex(12),
        **(extra or {}),
    }


def issue_token(
    player: Player, game: Game, *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A signed player token for the game server (``GAME029`` for a banned player)."""
    if player.is_banned:
        raise game_error(
            "GAME029", "This player is banned from the boards and from matches.", status=403
        )
    body = claims(player, game, extra=extra)
    token = jwt.encode(body, secret(), algorithm="HS256")
    return {
        "token": token,
        "expires_at": datetime.fromtimestamp(body["exp"], tz=UTC),
        "player": {"id": str(player.pk), "handle": player.handle},
    }


def verify_token(token: str, game: Game) -> dict[str, Any]:
    """What a game server does with the token, in Python: the claims, or ``jwt`` errors."""
    return dict(
        jwt.decode(
            token,
            secret(),
            algorithms=["HS256"],
            audience=f"game:{game.slug}",
            issuer=str(conf.get("KARNI_GAME_TOKEN_ISSUER")),
        )
    )


def _bad(index: int, message: str) -> Exception:
    return game_error("GAME035", message, index=index)


def report(game: Game, match_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Record a match's results once: scores and ``match`` rewards, all or nothing."""
    if Match.objects.filter(game=game, match_id=match_id).exists():
        return {"match": match_id, "recorded": 0, "duplicate": True}
    boards = {row.key: row for row in Board.objects.filter(game=game, is_active=True)}
    prizes = {
        row.key: row
        for row in Reward.objects.filter(game=game, kind="match", is_active=True).select_related(
            "currency"
        )
    }
    checked: list[tuple[Player, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        player = Player.objects.select_related("person").filter(pk=row.get("player")).first()
        if player is None:
            raise _bad(index, f"No player has the id {row.get('player')!r}.")
        board = row.get("board")
        if board and board not in boards:
            raise _bad(index, f"{game.slug} has no active board {board!r}.")
        if board and not isinstance(row.get("value"), int):
            raise _bad(index, "A row with a board has a whole-number value.")
        for key in row.get("rewards", []) or []:
            if key not in prizes:
                raise _bad(index, f"{game.slug} has no active match reward {key!r}.")
        checked.append((player, row))
    recorded = 0
    try:
        with transaction.atomic(using=router.db_for_write(Match)):
            Match.objects.create(
                game=game,
                match_id=match_id,
                players=[str(player.pk) for player, _ in checked],
                results=rows,
            )
            for player, row in checked:
                board = boards.get(row.get("board") or "")
                if board is not None and not player.is_banned:
                    board.game = game
                    scores.submit(player, board, int(row["value"]), source="match")
                for key in row.get("rewards", []) or []:
                    prize = prizes[key]
                    prize.game = game
                    rewards.grant(player, prize, source="match", reference=match_id)
                recorded += 1
            publish(
                "game.match.reported",
                subject=game,
                game=game.slug,
                match=match_id,
                players=[str(player.pk) for player, _ in checked],
            )
    except IntegrityError:  # the same match, reported twice at once
        return {"match": match_id, "recorded": 0, "duplicate": True}
    return {"match": match_id, "recorded": recorded, "duplicate": False}
