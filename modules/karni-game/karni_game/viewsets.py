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
from karni.api import Access, BaseViewSet, Can, Granted
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response

from karni_game import players
from karni_game.models import Game, Player

__all__ = ["GameViewSet", "PlayerViewSet"]


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
    search_fields = ["title", "slug"]


class PlayerViewSet(BaseViewSet):
    """``/api/game-players/``: the players with their person; ban, unban, revoke a token."""

    model = Player
    route = "game-players"
    access = Access(read=Granted(), write=Granted())
    search_fields = ["handle", "person__display_name", "person__email"]
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
