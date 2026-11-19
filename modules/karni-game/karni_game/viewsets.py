"""The staff's side of the games, auto-registered on ``/api/`` (docs/game-api.md, Staff resources).

Each resource answers the grants of the caller's roles
(``karni_game.<model>:<action>``): ``game-manager`` holds them all,
``game-moderator`` the players and the scores. A player never reaches these:
a player's own calls are the game API of :mod:`karni_game.api`.

What only the services may change (a balance, a save's version, a guest's
token, a score's status) is read-only here and changes through the actions,
which go through the services and their rules.

Override / escape hatch: subclass a viewset, set ``auto_register = False`` on
this one, and register yours.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from karni.api import Access, BaseViewSet, Budget, Can, Granted
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response

from karni_game import players, scores, wallet
from karni_game.models import (
    Achievement,
    Board,
    ConfigValue,
    Currency,
    Game,
    Item,
    LedgerEntry,
    Match,
    Mission,
    Player,
    Reward,
    Save,
    Score,
    Streak,
    Unlock,
    Wallet,
)

__all__ = [
    "AchievementViewSet",
    "BoardViewSet",
    "ConfigValueViewSet",
    "CurrencyViewSet",
    "ItemViewSet",
    "LedgerViewSet",
    "MatchViewSet",
    "MissionViewSet",
    "RewardViewSet",
    "WalletViewSet",
    "GameViewSet",
    "PlayerViewSet",
    "SaveViewSet",
    "StreakViewSet",
    "UnlockViewSet",
    "ScoreViewSet",
]


class ReadOnly:
    """The standard writes answer 405: these rows change only through the actions."""

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "POST")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT")

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PATCH")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "DELETE")


class BanSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class GameViewSet(BaseViewSet):
    """``/api/games/``: the games, their settings."""

    model = Game
    route = "games"
    access = Access(read=Granted(), write=Granted())


class PlayerViewSet(BaseViewSet):
    """``/api/game-players/``: the players with their person; ban, unban, revoke a token."""

    model = Player
    route = "game-players"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["person"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("POST")  # a player is made by its first call, never by hand

    @extend_schema(request=BanSerializer)
    @action(detail=True, methods=["post"], access=Can("karni_game.player:ban"))
    def ban(self, request: Request, pk: str | None = None) -> Response:
        """Keep the player off the boards and the realtime server."""
        player = self.get_object()
        body = BanSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        player.banned_at = timezone.now()
        player.ban_reason = body.validated_data["reason"]
        player.save(update_fields=["banned_at", "ban_reason", "updated_at"])
        return Response(self.get_serializer(player).data)

    @action(detail=True, methods=["post"], access=Can("karni_game.player:unban"))
    def unban(self, request: Request, pk: str | None = None) -> Response:
        player = self.get_object()
        player.banned_at = None
        player.ban_reason = ""
        player.save(update_fields=["banned_at", "ban_reason", "updated_at"])
        return Response(self.get_serializer(player).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="revoke-token",
        access=Can("karni_game.player:change"),
    )
    def revoke_token(self, request: Request, pk: str | None = None) -> Response:
        """The guest's token stops working (a lost or leaked device)."""
        player = self.get_object()
        players.revoke_token(player)
        return Response(self.get_serializer(player).data)


class SaveViewSet(ReadOnly, BaseViewSet):
    """``/api/game-saves/``: the saves, read only (support reads a player's progress)."""

    model = Save
    route = "game-saves"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game", "player"]


class BoardViewSet(BaseViewSet):
    """``/api/game-boards/``: the boards of the games."""

    model = Board
    route = "game-boards"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ScoreViewSet(ReadOnly, BaseViewSet):
    """``/api/game-scores/?status=flagged``: every score and its run; accept or reject one."""

    model = Score
    route = "game-scores"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["board", "player", "status"]
    ordering = ["-created_at"]
    query_budget = Budget(
        accept=None,
        reject=None,
        reason="accepting or rejecting a score rebuilds the player's bests on its board: a "
        "row per period for each of their accepted scores",
    )

    @action(detail=True, methods=["post"], access=Can("karni_game.score:accept"))
    def accept(self, request: Request, pk: str | None = None) -> Response:
        """Let the score count: it may be the player's new best."""
        return Response(self.get_serializer(scores.accept(self.get_object())).data)

    @extend_schema(request=ReviewSerializer)
    @action(detail=True, methods=["post"], access=Can("karni_game.score:reject"))
    def reject(self, request: Request, pk: str | None = None) -> Response:
        """Take the score off the boards; the player's bests are rebuilt without it."""
        body = ReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        done = scores.reject(self.get_object(), body.validated_data["note"])
        return Response(self.get_serializer(done).data)


class CurrencyViewSet(BaseViewSet):
    """``/api/game-currencies/``: the soft currencies of the games."""

    model = Currency
    route = "game-currencies"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class RewardViewSet(BaseViewSet):
    """``/api/game-rewards/``: the rewards the server grants."""

    model = Reward
    route = "game-rewards"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class ItemViewSet(BaseViewSet):
    """``/api/game-items/``: the cosmetics, their prices."""

    model = Item
    route = "game-items"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class GrantSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class WalletViewSet(ReadOnly, BaseViewSet):
    """``/api/game-wallets/``: the balances. ``POST {id}/grant/`` gives or takes some."""

    model = Wallet
    route = "game-wallets"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["player", "currency"]

    @extend_schema(request=GrantSerializer)
    @action(detail=True, methods=["post"], access=Can("karni_game.wallet:grant"))
    def grant(self, request: Request, pk: str | None = None) -> Response:
        """Staff give (or take, with a negative amount) currency, with a note."""
        row = self.get_object()
        body = GrantSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        wallet.change(
            row.player,
            row.currency,
            body.validated_data["amount"],
            reason="grant",
            actor=request.user,
            note=body.validated_data["note"],
        )
        row.refresh_from_db()
        return Response(self.get_serializer(row).data)


class LedgerViewSet(ReadOnly, BaseViewSet):
    """``/api/game-ledger/``: every ledger entry."""

    model = LedgerEntry
    route = "game-ledger"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["wallet"]


class StreakViewSet(ReadOnly, BaseViewSet):
    """``/api/game-streaks/``: the players' daily streaks, read only."""

    model = Streak
    route = "game-streaks"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game", "player"]


class AchievementViewSet(BaseViewSet):
    """``/api/game-achievements/``: the achievements the server unlocks."""

    model = Achievement
    route = "game-achievements"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class MissionViewSet(BaseViewSet):
    """``/api/game-missions/``: the missions, their periods and rewards."""

    model = Mission
    route = "game-missions"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class UnlockViewSet(ReadOnly, BaseViewSet):
    """``/api/game-unlocks/``: who unlocked what, read only."""

    model = Unlock
    route = "game-unlocks"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["achievement", "player"]


class ConfigValueViewSet(BaseViewSet):
    """``/api/game-config/``: the remote config values and feature flags of the games."""

    model = ConfigValue
    route = "game-config"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]


class MatchViewSet(ReadOnly, BaseViewSet):
    """``/api/game-matches/``: the matches realtime servers reported, read only."""

    model = Match
    route = "game-matches"
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["game"]
