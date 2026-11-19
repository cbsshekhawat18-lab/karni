"""Experimental. The game API a client calls (docs/game-api.md), mounted by ``karni_game.urls``.

Every view finds its player from the request alone (:class:`GameView`): a
signed-in account, else the guest token in ``X-Player-Token``. None takes a
player's id from the client. A refusal is a
:class:`~karni_game.errors.GameError`, answered as ``{"detail", "code", ...}``.

Override / escape hatch: subclass a view and mount it yourself in place of
the include, or subclass :class:`GameView` for a view of your own game that
needs the same player and errors.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from karni import preferences
from karni.vetoes import VetoContext, check_vetoes
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni_game import clock, conf, players, saves
from karni_game.errors import GameError, game_error
from karni_game.models import Game, Player, Save
from karni_game.throttling import PlayerRateThrottle

__all__ = [
    "GameDetailView",
    "GameView",
    "GuestView",
    "MeView",
    "PlayerSerializer",
    "SaveView",
    "SavesView",
    "UpgradeView",
]


class PlayerSerializer(serializers.Serializer):
    """A player as the player sees itself."""

    id = serializers.UUIDField(read_only=True)
    handle = serializers.CharField(read_only=True)
    guest = serializers.BooleanField(source="is_guest", read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class HandleSerializer(serializers.Serializer):
    handle = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class UpgradeSerializer(serializers.Serializer):
    guest_token = serializers.CharField(max_length=200, required=False, default="")


def player_data(player: Player) -> dict[str, Any]:
    return dict(PlayerSerializer(player).data)


class GameView(APIView):
    """The base of every game view: its player, its game, its limits, its errors.

    ``throttle_scopes`` maps a method to its scope of ``KARNI_GAME_RATES``.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_scopes: ClassVar[dict[str, str]] = {}
    throttle_class: ClassVar[type[PlayerRateThrottle]] = PlayerRateThrottle

    # -- the player ---------------------------------------------------------------------

    def _resolve(self) -> Player | None:
        user = getattr(self.request, "user", None)
        if user is not None and user.is_authenticated:
            return players.player_for_user(user)
        header = str(conf.get("KARNI_GAME_TOKEN_HEADER"))
        token = self.request.headers.get(header, "")
        if token:
            return players.player_for_token(token)
        return None

    def player_or_none(self) -> Player | None:
        """The calling player, or ``None`` (an anonymous call, or one refused)."""
        if not hasattr(self, "_player"):
            self._player_error: GameError | None = None
            try:
                self._player: Player | None = self._resolve()
            except GameError as exc:
                self._player = None
                self._player_error = exc
        return self._player

    @property
    def player(self) -> Player:
        """The calling player: ``GAME002``, ``GAME003`` or ``GAME004`` when there is none."""
        found = self.player_or_none()
        if found is None:
            raise self._player_error or game_error(
                "GAME002",
                "This call needs a player: sign in, or send a guest token in "
                f"{conf.get('KARNI_GAME_TOKEN_HEADER')}.",
                status=401,
            )
        return found

    # -- the game -----------------------------------------------------------------------

    @property
    def game(self) -> Game:
        """The active game the path names (``GAME006``, 404)."""
        if not hasattr(self, "_game"):
            slug = str(self.kwargs.get("game", ""))
            found = Game.objects.filter(slug=slug, is_active=True).first()
            if found is None:
                raise game_error("GAME006", f"No active game has the slug {slug!r}.", status=404)
            self._game = found
        return self._game

    # -- gates --------------------------------------------------------------------------

    def guard(self, action: str, model: type[Any], permission: str | None = None) -> None:
        """Refuse when a registered veto refuses (an impersonated session, say)."""
        reason = check_vetoes(
            VetoContext(
                request=self.request,
                kind="api",
                action=action,
                model=model,
                permission=permission,
                view=self,
            )
        )
        if reason:
            raise PermissionDenied(reason)

    def get_throttles(self) -> list[Any]:
        scope = self.throttle_scopes.get(str(getattr(self.request, "method", "")))
        return [self.throttle_class(scope)] if scope else []

    def throttle_ident(self, request: Request, scope: str) -> str | None:
        """Who a limit counts: the player (else the client's address)."""
        found = self.player_or_none()
        return f"player:{found.pk}" if found is not None else None

    def throttled(self, request: Request, wait: float | None) -> None:
        seconds = max(1, math.ceil(wait or 1))
        raise game_error(
            "GAME015",
            f"Too many requests of this kind. Try again in {seconds} seconds.",
            status=429,
            retry_after=seconds,
        )

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, GameError):
            response = Response(exc.payload(), status=exc.status_code)
            if "retry_after" in exc.extra:
                response["Retry-After"] = str(exc.extra["retry_after"])
            return response
        return super().handle_exception(exc)


# -- players ---------------------------------------------------------------------------


class GuestView(GameView):
    """``POST guest/``: a guest's token and player, with no account."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "guest"}

    def throttle_ident(self, request: Request, scope: str) -> str | None:
        return None  # per client address: a guest has no player yet

    @extend_schema(request=HandleSerializer, responses={201: PlayerSerializer})
    def post(self, request: Request) -> Response:
        if not preferences.value("game.allow_guests", True):
            raise game_error(
                "GAME005", "Guest play is off for this project: sign in to play.", status=403
            )
        body = HandleSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        issued = players.issue_guest(body.validated_data["handle"])
        return Response({"token": issued.token, "player": player_data(issued.player)}, status=201)


class MeView(GameView):
    """``GET me/`` and ``PATCH me/``: the calling player, and its handle."""

    @extend_schema(responses=PlayerSerializer)
    def get(self, request: Request) -> Response:
        return Response(player_data(self.player))

    @extend_schema(request=HandleSerializer, responses=PlayerSerializer)
    def patch(self, request: Request) -> Response:
        player = self.player
        self.guard("partial_update", Player, "karni_game.player:change")
        body = HandleSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if body.validated_data["handle"]:
            player.handle = players.clean_handle(body.validated_data["handle"])
            player.save(update_fields=["handle", "updated_at"])
        return Response(player_data(player))


class UpgradeView(GameView):
    """``POST upgrade/``: the signed-in account keeps the guest's progress."""

    @extend_schema(request=UpgradeSerializer)
    def post(self, request: Request) -> Response:
        body = UpgradeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        header = str(conf.get("KARNI_GAME_TOKEN_HEADER"))
        token = body.validated_data["guest_token"] or request.headers.get(header, "")
        self.guard("upgrade", Player, "karni_game.player:change")
        done = players.upgrade(request.user, token)
        return Response({"player": player_data(done.player), "merged": done.merged})


# -- a game ----------------------------------------------------------------------------


def server_data(game: Game) -> dict[str, Any]:
    now = timezone.now()
    return {
        "time": now,
        "date": clock.today(game, now).isoformat(),
        "timezone": game.options().timezone,
        "resets_at": clock.resets_at(game, now),
    }


class GameDetailView(GameView):
    """``GET <game>/``: the one call at boot: the game, the server's clock, its config."""

    def describe(self, game: Game, player: Player | None) -> dict[str, Any]:
        """The body. Each part of the game adds its own key (boards, currencies, config)."""
        options = game.options()
        return {
            "game": {"slug": game.slug, "title": game.title},
            "server": server_data(game),
            "save": {
                "schema_version": options.save_schema_version,
                "max_bytes": options.max_save_bytes,
                "max_slots": options.max_slots,
            },
            "analytics": options.analytics,
        }

    def get(self, request: Request, game: str) -> Response:
        return Response(self.describe(self.game, self.player_or_none()))


# -- saves -----------------------------------------------------------------------------


class SaveWriteSerializer(serializers.Serializer):
    data = serializers.JSONField()
    schema_version = serializers.IntegerField(min_value=0)
    base_version = serializers.IntegerField(min_value=0)


class SavesView(GameView):
    """``GET <game>/saves/``: the player's slots in the game, without their data."""

    def get(self, request: Request, game: str) -> Response:
        options = self.game.options()
        rows = saves.slots(self.player, self.game)
        return Response(
            {
                "results": [saves.as_data(row, data=False) for row in rows],
                "max_slots": options.max_slots,
                "max_bytes": options.max_save_bytes,
            }
        )


class SaveView(GameView):
    """``GET``, ``PUT`` and ``DELETE <game>/saves/<slot>/``: one slot of the player."""

    throttle_scopes: ClassVar[dict[str, str]] = {"PUT": "save", "DELETE": "save"}

    def get(self, request: Request, game: str, slot: str) -> Response:
        found = saves.read(self.player, self.game, slot)
        if found is None:
            from rest_framework.exceptions import NotFound

            raise NotFound(f"No save in slot {slot!r}.")
        return Response(saves.as_data(found))

    @extend_schema(request=SaveWriteSerializer)
    def put(self, request: Request, game: str, slot: str) -> Response:
        player = self.player
        self.guard("update", Save, "karni_game.save:change")
        body = SaveWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        stored = saves.write(
            player,
            self.game,
            slot,
            body.validated_data["data"],
            schema_version=body.validated_data["schema_version"],
            base_version=body.validated_data["base_version"],
        )
        return Response(saves.as_data(stored))

    def delete(self, request: Request, game: str, slot: str) -> Response:
        player = self.player
        self.guard("destroy", Save, "karni_game.save:delete")
        raw = request.query_params.get("base_version")
        base = None
        if raw not in (None, ""):
            try:
                base = int(str(raw))
            except ValueError:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"base_version": ["A whole number."]}) from None
        if not saves.delete(player, self.game, slot, base_version=base):
            from rest_framework.exceptions import NotFound

            raise NotFound(f"No save in slot {slot!r}.")
        return Response(status=204)
