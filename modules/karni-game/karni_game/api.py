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

from karni_game import (
    clock,
    conf,
    daily,
    intents,
    multiplayer,
    players,
    progress,
    rewards,
    saves,
    scores,
    shop,
    wallet,
)
from karni_game import config as remote
from karni_game.errors import GameError, game_error
from karni_game.models import (
    Board,
    Currency,
    Game,
    Item,
    LedgerEntry,
    Player,
    Reward,
    Save,
    Score,
    Wallet,
)
from karni_game.throttling import PlayerRateThrottle

__all__ = [
    "GameDetailView",
    "GameView",
    "GuestView",
    "MeView",
    "PlayerSerializer",
    "AchievementsView",
    "BoardMeView",
    "BoardView",
    "BuyView",
    "CallbackView",
    "CheckInView",
    "ClaimView",
    "DailyView",
    "EventsView",
    "EquipView",
    "IntentView",
    "LedgerView",
    "MissionsView",
    "ProgressView",
    "ResultsView",
    "RewardsView",
    "ShopView",
    "UnequipView",
    "WalletView",
    "PlayerTokenView",
    "SaveView",
    "SavesView",
    "ScoresView",
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


class GuestSerializer(HandleSerializer):
    intent = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


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

    @extend_schema(request=GuestSerializer, responses={201: PlayerSerializer})
    def post(self, request: Request) -> Response:
        if not preferences.value("game.allow_guests", True):
            raise game_error(
                "GAME005", "Guest play is off for this project: sign in to play.", status=403
            )
        body = GuestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        issued = players.issue_guest(data["handle"], intent=data["intent"])
        answer = {"token": issued.token, "player": player_data(issued.player)}
        if issued.replayed:
            return Response({**answer, "replayed": True}, status=200)
        return Response(answer, status=201)


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
        """The body: the game, the server's clock, its config and flags, saves, boards."""
        options = game.options()
        values, flags = remote.values(game, player)
        return {
            "game": {"slug": game.slug, "title": game.title},
            "server": server_data(game),
            "config": values,
            "flags": flags,
            "save": {
                "schema_version": options.save_schema_version,
                "max_bytes": options.max_save_bytes,
                "max_slots": options.max_slots,
            },
            "boards": [
                scores.board_data(board)
                for board in Board.objects.filter(game=game, is_active=True)
            ],
            "currencies": [
                {"key": row.key, "title": row.title, "cap": row.cap}
                for row in Currency.objects.filter(game=game)
            ],
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
            raise saves.empty(slot)
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
            raise saves.empty(slot)
        return Response(status=204)


# -- scores and boards -------------------------------------------------------------


class RunSerializer(serializers.Serializer):
    seed = serializers.CharField(max_length=64, required=False, allow_blank=True)
    inputs = serializers.JSONField(required=False)
    duration_ms = serializers.IntegerField(min_value=0, required=False)
    build = serializers.CharField(max_length=40, required=False, allow_blank=True)
    meta = serializers.JSONField(required=False)


class ScoreSerializer(serializers.Serializer):
    value = serializers.IntegerField(min_value=-(2**62), max_value=2**62)
    intent = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    run = RunSerializer(required=False, allow_null=True, default=None)
    played_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


def _period(request: Request, board: Board) -> str:
    period = str(request.query_params.get("period", "") or board.periods[0])
    if period not in board.periods:
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"period": [f"One of {', '.join(board.periods)}."]})
    return period


def _number(request: Request, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(str(request.query_params.get(name, default)))
    except ValueError:
        value = default
    return max(low, min(high, value))


class BoardsMixin(GameView):
    def board(self) -> Board:
        return scores.find_board(self.game, str(self.kwargs.get("board", "")))

    def reader(self) -> Player | None:
        """The player reading the board, or ``None``. Off ``public_boards``: a player only."""
        found = self.player_or_none()
        if found is None and not preferences.value("game.public_boards", True):
            return self.player
        return found


class ScoresView(BoardsMixin):
    """``POST <game>/boards/<board>/scores/``: a score, checked, maybe a new best."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "score"}

    @extend_schema(request=ScoreSerializer)
    def post(self, request: Request, game: str, board: str) -> Response:
        player = self.player
        target = self.board()
        self.guard("create", Score, "karni_game.score:add")
        body = ScoreSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        run = dict(data["run"]) if data["run"] else None

        played_at = data["played_at"]

        def work() -> tuple[int, dict[str, Any]]:
            found = scores.submit(player, target, data["value"], run, played_at=played_at)
            return 201, found.as_dict()

        status, answer, replayed = intents.once(
            player,
            f"score:{target.pk}",
            data["intent"],
            {"value": data["value"], "run": run, "played_at": played_at},
            work,
        )
        if replayed:
            return Response({**answer, "replayed": True}, status=200)
        return Response(answer, status=status)


class BoardView(BoardsMixin):
    """``GET <game>/boards/<board>/?period=&limit=``: the top of a board."""

    def get(self, request: Request, game: str, board: str) -> Response:
        target = self.board()
        player = self.reader()
        period = _period(request, target)
        start = clock.period_start(target.game, period)
        limit = _number(request, "limit", 10, 1, 100)
        rows = list(scores.ranked(target, period, start)[:limit])
        mine = None
        if player is not None:
            own = scores.ranked(target, period, start).filter(player=player).first()
            if own is not None:
                mine = {"rank": scores.rank_of(target, own), "value": own.value}
        return Response(
            {
                "board": scores.board_data(target),
                "period": period,
                "period_start": None if period == "all" else start.isoformat(),
                "entries": [scores.entry(index + 1, row, player) for index, row in enumerate(rows)],
                "me": mine,
            }
        )


class BoardMeView(BoardsMixin):
    """``GET <game>/boards/<board>/me/?period=&around=``: the player's rank and neighbours."""

    def get(self, request: Request, game: str, board: str) -> Response:
        player = self.player
        target = self.board()
        period = _period(request, target)
        start = clock.period_start(target.game, period)
        around = _number(request, "around", 3, 0, 25)
        rows = scores.ranked(target, period, start)
        own = rows.filter(player=player).first()
        body: dict[str, Any] = {
            "period": period,
            "period_start": None if period == "all" else start.isoformat(),
            "rank": None,
            "value": None,
            "entries": [],
        }
        if own is not None:
            rank = scores.rank_of(target, own)
            first = max(1, rank - around)
            near = list(rows[first - 1 : rank + around])
            body.update(
                rank=rank,
                value=own.value,
                entries=[
                    scores.entry(first + index, row, player) for index, row in enumerate(near)
                ],
            )
        return Response(body)


# -- wallet, rewards and the shop ------------------------------------------------------


class IntentOnlySerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class CallbackSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=2000)
    event_id = serializers.CharField(max_length=100)


def _once(
    view: GameView, kind: str, body: dict[str, Any], work: Any, *, status: int = 200
) -> Response:
    """Run ``work`` once per ``intent`` of the body: a retry answers the first answer."""
    intent = str(body.get("intent", "") or "")

    def run() -> tuple[int, dict[str, Any]]:
        return status, work()

    code, answer, replayed = intents.once(view.player, kind, intent, body, run)
    if replayed:
        return Response({**answer, "replayed": True}, status=200)
    return Response(answer, status=code)


class WalletView(GameView):
    """``GET <game>/wallet/``: the player's balances and items in the game."""

    def get(self, request: Request, game: str) -> Response:
        player = self.player
        items = [
            {
                "item": row.item.key,
                "title": row.item.title,
                "slot": row.slot,
                "equipped": row.equipped,
                "acquired_at": row.created_at,
            }
            for row in shop.owned(player, self.game).values()
        ]
        return Response({"balances": wallet.balances(player, self.game), "items": items})


class LedgerView(GameView):
    """``GET <game>/wallet/ledger/?currency=&page=``: the player's own entries, newest first."""

    page_size = 50

    def get(self, request: Request, game: str) -> Response:
        rows = LedgerEntry.objects.filter(
            wallet__player=self.player, wallet__currency__game=self.game
        ).select_related("wallet__currency")
        currency = str(request.query_params.get("currency", "") or "")
        if currency:
            rows = rows.filter(wallet__currency__key=currency)
        rows = rows.order_by("-created_at", "-id")
        page = _number(request, "page", 1, 1, 10_000)
        count = rows.count()
        start = (page - 1) * self.page_size
        found = rows[start : start + self.page_size]
        return Response(
            {
                "count": count,
                "next": page + 1 if start + self.page_size < count else None,
                "results": [
                    {
                        "id": str(row.pk),
                        "currency": row.wallet.currency.key,
                        "amount": row.amount,
                        "balance_after": row.balance_after,
                        "reason": row.reason,
                        "reference": row.reference,
                        "created_at": row.created_at,
                    }
                    for row in found
                ],
            }
        )


class RewardsView(GameView):
    """``GET <game>/rewards/``: the rewards, and when the player may have each."""

    def get(self, request: Request, game: str) -> Response:
        player = self.player_or_none()
        rows = Reward.objects.filter(game=self.game, is_active=True).select_related("currency")
        for row in rows:
            row.game = self.game
        return Response({"results": [rewards.reward_data(row, player) for row in rows]})


class ClaimView(GameView):
    """``POST <game>/rewards/<reward>/claim/``: an ad reward the client claims."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "claim"}

    @extend_schema(request=IntentOnlySerializer)
    def post(self, request: Request, game: str, reward: str) -> Response:
        player = self.player
        found = rewards.find_reward(self.game, reward)
        found.game = self.game
        self.guard("create", Wallet, "karni_game.wallet:change")
        body = IntentOnlySerializer(data=request.data)
        body.is_valid(raise_exception=True)

        def work() -> dict[str, Any]:
            done = rewards.claim(player, found)
            return {**done.as_dict(), "next_at": rewards.availability(player, found)["next_at"]}

        return _once(self, f"claim:{found.pk}", dict(body.validated_data), work)


class IntentView(GameView):
    """``POST <game>/rewards/<reward>/intent/``: the intent a portal sends back when it calls."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "claim"}

    def post(self, request: Request, game: str, reward: str) -> Response:
        player = self.player
        found = rewards.find_reward(self.game, reward)
        return Response(rewards.intent_for(player, found), status=201)


class CallbackView(GameView):
    """``POST callbacks/<portal>/``: a portal's server, signed, after an ad was watched."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "callback"}
    authentication_classes: ClassVar[list[type]] = []

    def throttle_ident(self, request: Request, scope: str) -> str | None:
        return f"portal:{self.kwargs.get('portal', '')}"

    @extend_schema(request=CallbackSerializer)
    def post(self, request: Request, portal: str) -> Response:
        # The signature covers the raw body: verify it before the body is parsed.
        rewards.verifier_for(portal).verify(request)
        body = CallbackSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        return Response(rewards.from_callback(portal, data["intent"], data["event_id"]))


class ShopView(GameView):
    """``GET <game>/shop/``: the items, their prices, which the player owns and wears."""

    def get(self, request: Request, game: str) -> Response:
        player = self.player_or_none()
        mine = shop.owned(player, self.game) if player is not None else {}
        rows = Item.objects.filter(game=self.game, is_active=True).select_related("currency")
        return Response({"results": [shop.item_data(row, mine.get(row.key)) for row in rows]})


class BuyView(GameView):
    """``POST <game>/shop/<item>/buy/``: spend the price, own the item."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "buy"}

    @extend_schema(request=IntentOnlySerializer)
    def post(self, request: Request, game: str, item: str) -> Response:
        player = self.player
        found = shop.find_item(self.game, item)
        found.game = self.game
        self.guard("create", Wallet, "karni_game.wallet:change")
        body = IntentOnlySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return _once(
            self,
            f"buy:{found.pk}",
            dict(body.validated_data),
            lambda: shop.buy(player, found),
            status=201,
        )


class EquipView(GameView):
    """``POST <game>/items/<item>/equip/``: wear an item the player owns."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "buy"}
    wear = True

    def post(self, request: Request, game: str, item: str) -> Response:
        player = self.player
        found = shop.find_item(self.game, item)
        if self.wear:
            return Response(shop.equip(player, found))
        return Response(shop.unequip(player, found))


class UnequipView(EquipView):
    """``POST <game>/items/<item>/unequip/``."""

    wear = False


# -- daily -----------------------------------------------------------------------------


class DailyView(GameView):
    """``GET <game>/daily/``: the server's day, its seed, the daily board, the streak."""

    def get(self, request: Request, game: str) -> Response:
        return Response(daily.daily_data(self.game, self.player_or_none()))


class CheckInView(GameView):
    """``POST <game>/daily/check-in/``: once a day, the streak and the daily rewards."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "claim"}

    def post(self, request: Request, game: str) -> Response:
        player = self.player
        self.guard("create", Wallet, "karni_game.wallet:change")
        return Response(daily.check_in(player, self.game))


# -- achievements and missions ---------------------------------------------------------


class ProgressEventSerializer(serializers.Serializer):
    counter = serializers.SlugField(max_length=50)
    amount = serializers.IntegerField()


class ProgressSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    events = ProgressEventSerializer(many=True, allow_empty=False, max_length=20)


class ProgressView(GameView):
    """``POST <game>/progress/``: counters the game reports; the server unlocks and grants."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "progress"}

    @extend_schema(request=ProgressSerializer)
    def post(self, request: Request, game: str) -> Response:
        player = self.player
        self.guard("create", Wallet, "karni_game.wallet:change")
        body = ProgressSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        events = [dict(event) for event in body.validated_data["events"]]
        target = self.game
        return _once(
            self,
            "progress",
            {"intent": body.validated_data["intent"], "events": events},
            lambda: progress.report(player, target, events),
        )


class AchievementsView(GameView):
    """``GET <game>/achievements/``: the achievements, the player's progress and unlocks."""

    def get(self, request: Request, game: str) -> Response:
        return Response({"results": progress.achievements(self.player_or_none(), self.game)})


class MissionsView(GameView):
    """``GET <game>/missions/``: the missions, the player's progress in each one's period."""

    def get(self, request: Request, game: str) -> Response:
        return Response({"results": progress.missions(self.player_or_none(), self.game)})


# -- analytics -------------------------------------------------------------------------


class EventsSerializer(serializers.Serializer):
    events = serializers.ListField(child=serializers.JSONField(), allow_empty=False, max_length=20)
    intent = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class EventsView(GameView):
    """``POST <game>/events/``: analytics events the game declares, published as family events."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "events"}

    @extend_schema(request=EventsSerializer)
    def post(self, request: Request, game: str) -> Response:
        player = self.player_or_none()
        body = EventsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        events = list(body.validated_data["events"])
        target = self.game

        def work() -> tuple[int, dict[str, Any]]:
            return 202, remote.track(target, player, events)

        # Keyed by the player, or among the calls without one: a retry publishes nothing twice.
        status, answer, replayed = intents.once(
            player, f"events:{target.pk}", body.validated_data["intent"], {"events": events}, work
        )
        if replayed:
            return Response({**answer, "replayed": True}, status=200)
        return Response(answer, status=status)


# -- multiplayer -----------------------------------------------------------------------


class ResultRowSerializer(serializers.Serializer):
    player = serializers.CharField(max_length=64)
    board = serializers.SlugField(max_length=50, required=False, allow_blank=True, default="")
    value = serializers.IntegerField(required=False, allow_null=True, default=None)
    rewards = serializers.ListField(
        child=serializers.SlugField(max_length=50), required=False, default=list, max_length=10
    )


class ResultsSerializer(serializers.Serializer):
    match = serializers.CharField(max_length=100)
    results = ResultRowSerializer(many=True, allow_empty=False, max_length=100)


class PlayerTokenView(GameView):
    """``POST <game>/multiplayer/token/``: a short-lived token for the realtime server."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "token"}

    def post(self, request: Request, game: str) -> Response:
        return Response(multiplayer.issue_token(self.player, self.game), status=201)


class ResultsView(GameView):
    """``POST <game>/multiplayer/results/``: the realtime server's signed report of a match."""

    throttle_scopes: ClassVar[dict[str, str]] = {"POST": "results"}
    authentication_classes: ClassVar[list[type]] = []

    def throttle_ident(self, request: Request, scope: str) -> str | None:
        return f"server:{self.kwargs.get('game', '')}"

    @extend_schema(request=ResultsSerializer)
    def post(self, request: Request, game: str) -> Response:
        target = self.game
        # The signature covers the raw body: verify it before the body is parsed.
        multiplayer.verifier().verify(request)
        body = ResultsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        rows = [dict(row) for row in body.validated_data["results"]]
        return Response(multiplayer.report(target, body.validated_data["match"], rows))
