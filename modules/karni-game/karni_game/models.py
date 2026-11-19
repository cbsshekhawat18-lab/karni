"""The game's records: the games a project hosts, their players and each player's progress.

A :class:`Player` is the game profile of a :class:`karni.people.models.Person`
(one to one), so a guest and the account they upgrade to are one person in
every part of the project. Everything a player does in a game (a save, a
score, a balance) points at the player and at the :class:`Game`, so a project
that hosts several games keeps them apart.

What a game declares (its boards, currencies, rewards, items, achievements,
missions and config) are rows staff edit in the admin, or a content file
loads (``karni load``): each is found by its game and its ``key``.

Override / escape hatch: these are plain :class:`karni.models.BaseModel`
models. Read them in reports, extend them with tables of your own that point
at them. ``APIMeta`` keeps what only the services may write (balances,
versions, tokens) read-only in the staff API.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from karni.fields import LiveUniqueConstraint
from karni.models import BaseModel, TimestampedModel, UUIDModel
from pydantic import ValidationError as PydanticError

from karni_game import conf
from karni_game.gamesettings import GameSettings

#: A game's settings, or its slug, that the server cannot use.
SETTINGS_CODE = "GAME026"

__all__ = [
    "ORDERS",
    "RESERVED_SLUGS",
    "Best",
    "Board",
    "Game",
    "Intent",
    "Player",
    "Save",
    "Score",
]

#: Game slugs the API's own paths take (``/api/game/guest/`` is not a game).
RESERVED_SLUGS: frozenset[str] = frozenset({"guest", "me", "upgrade", "callbacks"})


class Game(BaseModel):
    """A game the project hosts: its slug in every path, its title and its settings."""

    slug = models.SlugField(max_length=50, help_text="The game's name in every API path.")
    title = models.CharField(max_length=120)
    is_active = models.BooleanField(
        default=True, help_text="Off: the game's API answers 404, as if it did not exist."
    )
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="The game's settings (karni_game.gamesettings.GameSettings): timezone, "
        "save_schema_version, max_save_bytes, max_slots, streak_grace_days, "
        "max_progress_step, analytics.",
    )

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["slug"], name="karni_game_game_slug")
        ]

    class Karni:
        natural_key = "slug"

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "slug", "is_active", "created_at"]
        search_fields: ClassVar[list[str]] = ["title", "slug"]

    def __str__(self) -> str:
        return self.title or self.slug

    def options(self) -> GameSettings:
        """The settings as :class:`GameSettings`, with every default filled in."""
        return GameSettings.model_validate(self.settings or {})

    def clean(self) -> None:
        super().clean()
        if self.slug in RESERVED_SLUGS:
            raise ValidationError(
                {
                    "slug": f"{SETTINGS_CODE}: {self.slug!r} is a path of the game API. Pick "
                    "another slug."
                }
            )
        try:
            options = GameSettings.model_validate(self.settings or {})
        except PydanticError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ValidationError({"settings": f"{SETTINGS_CODE}: {problems}"}) from exc
        ceiling = int(conf.get("KARNI_GAME_MAX_SAVE_BYTES"))
        if options.max_save_bytes > ceiling:
            raise ValidationError(
                {
                    "settings": f"{SETTINGS_CODE}: max_save_bytes {options.max_save_bytes} is "
                    f"above KARNI_GAME_MAX_SAVE_BYTES ({ceiling})."
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)


class Player(BaseModel):
    """A person's game profile: the handle the boards show, and a guest's token.

    A guest's person has no account. ``token_hash`` is the SHA-256 of the guest's
    token, never the token itself. Upgrading to an account clears it.
    ``banned_at`` keeps the player off the boards and the realtime server.
    """

    person = models.OneToOneField(
        "people.Person", on_delete=models.CASCADE, related_name="game_player"
    )
    handle = models.CharField(max_length=32, help_text="The name the boards show.")
    token_hash = models.CharField(max_length=64, blank=True, default="", editable=False)
    token_issued_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    banned_at = models.DateTimeField(null=True, blank=True, editable=False)
    ban_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(
                fields=["token_hash"], condition=~Q(token_hash=""), name="karni_game_player_token"
            )
        ]

    class Karni:
        owner_field = "person__user"
        actions: ClassVar[list[str]] = ["ban", "unban"]
        cascade: ClassVar[dict[str, str]] = {
            "person": "a game profile is part of its person, and goes with it"
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = ["person", "banned_at"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["handle", "person", "last_seen_at", "banned_at"]
        search_fields: ClassVar[list[str]] = ["handle", "person__display_name", "person__email"]

    def __str__(self) -> str:
        return self.handle

    @property
    def is_guest(self) -> bool:
        """Whether the player's person has no account."""
        return getattr(self.person, "user_id", None) is None

    @property
    def is_banned(self) -> bool:
        return self.banned_at is not None


class Save(BaseModel):
    """One save slot of a player in a game: its JSON, the shape of it, the server's version.

    ``version`` counts the writes: each write names the version it started from
    (:func:`karni_game.saves.write`), so a stale write never wins.
    ``schema_version`` is the game's own number for the shape of ``data``.
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="saves")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="saves")
    slot = models.CharField(max_length=40)
    data = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveIntegerField(default=1)
    version = models.PositiveIntegerField(default=1)
    size = models.PositiveIntegerField(default=0, help_text="Bytes of the data's JSON.")

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["player", "game", "slot"], name="karni_game_save_slot")
        ]

    class Karni:
        owner_field = "player__person__user"
        cascade: ClassVar[dict[str, str]] = {
            "player": "a save is its player's, and goes with it",
            "game": "a save is of its game, and goes with it",
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = [
            "player",
            "game",
            "slot",
            "data",
            "schema_version",
            "version",
            "size",
        ]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["slot", "player", "game", "version", "size"]
        list_filter: ClassVar[list[str]] = ["game"]
        search_fields: ClassVar[list[str]] = ["slot", "player__handle"]

    def __str__(self) -> str:
        return f"{self.slot} ({self.version})"


#: How a board ranks: ``desc``, higher is better (points), ``asc``, lower is better (a time).
ORDERS = (("desc", "Higher is better"), ("asc", "Lower is better"))


def _periods_default() -> list[str]:
    return ["all"]


class Board(BaseModel):
    """A leaderboard of a game: its order, the periods it keeps, its plausible range.

    A score outside ``min_value`` to ``max_value`` is refused. A score better
    than ``review_beyond`` is held for staff (``flagged``). ``requires_run``
    asks every score for its run (a seed and an input log), ``keep_runs``
    stores the runs for review, and ``daily_seed`` makes it a daily board:
    a run must use the day's seed.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="boards")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    order = models.CharField(max_length=4, choices=ORDERS, default="desc")
    periods = models.JSONField(
        default=_periods_default, blank=True, help_text='Any of "all", "daily" and "weekly".'
    )
    min_value = models.BigIntegerField(null=True, blank=True)
    max_value = models.BigIntegerField(null=True, blank=True)
    review_beyond = models.BigIntegerField(
        null=True, blank=True, help_text="A score better than this waits for staff."
    )
    requires_run = models.BooleanField(default=False)
    keep_runs = models.BooleanField(default=True)
    daily_seed = models.BooleanField(
        default=False, help_text="A daily board: a run must use the day's seed."
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_board_key")
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "a board is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "game", "order", "is_active"]
        list_filter: ClassVar[list[str]] = ["game"]
        inline_on = "game"

    def __str__(self) -> str:
        return f"{self.game_id and self.game.slug}/{self.key}"

    def better(self, value: int, than: int) -> bool:
        """Whether ``value`` ranks above ``than`` on this board."""
        return value < than if self.order == "asc" else value > than

    def clean(self) -> None:
        super().clean()
        from karni_game.clock import PERIODS

        periods = self.periods or []
        if (
            not isinstance(periods, list)
            or not periods
            or any(period not in PERIODS for period in periods)
        ):
            raise ValidationError(
                {"periods": f'{SETTINGS_CODE}: a list of "all", "daily" and "weekly".'}
            )
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValidationError(
                    {"max_value": f"{SETTINGS_CODE}: max_value is below min_value."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.periods = list(dict.fromkeys(self.periods or ["all"]))
        self.clean()
        super().save(*args, **kwargs)


#: What became of a score: it counts, it waits for staff, or staff took it off.
SCORE_STATUSES = (
    ("accepted", "Counts on the boards"),
    ("flagged", "Waits for staff"),
    ("rejected", "Taken off by staff"),
)


class Score(BaseModel):
    """One score a player sent (or a realtime server reported), with its run when kept."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="scores")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="scores")
    value = models.BigIntegerField()
    status = models.CharField(max_length=10, choices=SCORE_STATUSES, default="accepted")
    day = models.DateField(help_text="The game's day the score was sent on.")
    run = models.JSONField(null=True, blank=True, help_text="seed, inputs, duration_ms, meta")
    source = models.CharField(max_length=10, default="client", help_text="client or match")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        indexes: ClassVar[list[Any]] = [
            models.Index(fields=["board", "status"], name="karni_game_score_status"),
            models.Index(fields=["player", "board", "day"], name="karni_game_score_player"),
        ]

    class Karni:
        owner_field = "player__person__user"
        actions: ClassVar[list[str]] = ["accept", "reject"]
        cascade: ClassVar[dict[str, str]] = {
            "board": "a score is on its board",
            "player": "a score is its player's",
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = [
            "board",
            "player",
            "value",
            "status",
            "day",
            "run",
            "source",
            "reviewed_at",
        ]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["value", "board", "player", "status", "created_at"]
        list_filter: ClassVar[list[str]] = ["status", "board"]
        search_fields: ClassVar[list[str]] = ["player__handle"]

    def __str__(self) -> str:
        return f"{self.value} on {self.board_id}"


class Best(UUIDModel, TimestampedModel):
    """A player's best on a board in one period (``period_start``: the day, the Monday, or
    1970-01-01 for all time). Derived from the accepted scores, so it is rebuilt, never
    edited."""

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="bests")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="bests")
    period = models.CharField(max_length=6)
    period_start = models.DateField()
    value = models.BigIntegerField()
    achieved_at = models.DateTimeField()
    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(
                fields=["board", "player", "period", "period_start"], name="karni_game_best_one"
            )
        ]
        indexes: ClassVar[list[Any]] = [
            models.Index(
                fields=["board", "period", "period_start", "value"], name="karni_game_best_rank"
            )
        ]

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"{self.value} ({self.period})"


class Intent(UUIDModel, TimestampedModel):
    """A write's retry key (``intent``): the first answer, given again to a retry."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=20)
    key = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    status = models.PositiveSmallIntegerField(default=0)
    response = models.JSONField(default=dict)

    class Meta:
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(fields=["player", "kind", "key"], name="karni_game_intent")
        ]

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"
