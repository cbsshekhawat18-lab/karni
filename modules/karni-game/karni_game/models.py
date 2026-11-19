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

from django.conf import settings
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
    "LEDGER_REASONS",
    "MISSION_PERIODS",
    "ORDERS",
    "RESERVED_SLUGS",
    "REWARD_KINDS",
    "Achievement",
    "Best",
    "Board",
    "Claim",
    "Completion",
    "ConfigValue",
    "Currency",
    "Game",
    "Intent",
    "Item",
    "LedgerEntry",
    "Mission",
    "Ownership",
    "Player",
    "Progress",
    "Reward",
    "Save",
    "Score",
    "Streak",
    "Unlock",
    "Wallet",
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
            models.Index(fields=["status", "created_at"], name="karni_game_score_review"),
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
            models.UniqueConstraint(fields=["player", "kind", "key"], name="karni_game_intent_one")
        ]

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"


class Currency(BaseModel):
    """A soft currency of a game (coins, gems): earned by play, spent in the shop.

    ``cap`` is the most a wallet holds: a reward past it credits up to it.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="currencies")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    cap = models.BigIntegerField(null=True, blank=True, help_text="Blank: no cap.")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_currency_key"),
            models.CheckConstraint(
                condition=Q(cap__isnull=True) | Q(cap__gte=0), name="karni_game_currency_cap"
            ),
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "a currency is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "game", "cap"]
        inline_on = "game"

    def __str__(self) -> str:
        return self.title


class Wallet(BaseModel):
    """A player's balance in one currency. Only :mod:`karni_game.wallet` changes it."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="wallets")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="wallets")
    balance = models.BigIntegerField(default=0)

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["player", "currency"], name="karni_game_wallet_one"),
            models.CheckConstraint(
                condition=Q(balance__gte=0), name="karni_game_wallet_balance_gte_0"
            ),
        ]

    class Karni:
        owner_field = "player__person__user"
        actions: ClassVar[list[str]] = ["grant"]
        cascade: ClassVar[dict[str, str]] = {"player": "a wallet is its player's"}

    class APIMeta:
        read_only: ClassVar[list[str]] = ["player", "currency", "balance"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["player", "currency", "balance", "updated_at"]
        list_filter: ClassVar[list[str]] = ["currency"]
        search_fields: ClassVar[list[str]] = ["player__handle"]
        read_only: ClassVar[list[str]] = ["player", "currency", "balance"]

    def __str__(self) -> str:
        return f"{self.balance} {self.currency_id and self.currency.key}"


#: Why a balance moved.
LEDGER_REASONS = (
    ("reward", "A reward"),
    ("purchase", "A purchase"),
    ("mission", "A mission"),
    ("achievement", "An achievement"),
    ("match", "A match result"),
    ("grant", "Staff"),
    ("merge", "Two players merged"),
    ("refund", "A refund"),
)


class LedgerEntry(UUIDModel, TimestampedModel):
    """One change of a balance: how much, the balance after it, and why. Never edited."""

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    amount = models.BigIntegerField()
    balance_after = models.BigIntegerField()
    reason = models.CharField(max_length=12, choices=LEDGER_REASONS)
    reference = models.CharField(max_length=64, blank=True, default="")
    intent = models.CharField(max_length=64, blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "ledger entries"
        indexes: ClassVar[list[Any]] = [
            models.Index(fields=["wallet", "created_at"], name="karni_game_ledger_wallet")
        ]

    class Karni:
        owner_field = "wallet__player__person__user"
        append_only = True

    class APIMeta:
        read_only: ClassVar[list[str]] = [
            "wallet",
            "amount",
            "balance_after",
            "reason",
            "reference",
            "intent",
            "actor",
            "note",
        ]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["wallet", "amount", "balance_after", "reason"]
        list_filter: ClassVar[list[str]] = ["reason"]

    def __str__(self) -> str:
        return f"{self.amount:+d} ({self.reason})"


#: How a reward is granted (docs/game-api.md, Rewards).
REWARD_KINDS = (
    ("daily", "The daily check-in"),
    ("ad", "After an ad"),
    ("mission", "A completed mission"),
    ("achievement", "An unlocked achievement"),
    ("match", "A realtime match result"),
    ("grant", "Staff only"),
)


class Reward(BaseModel):
    """A reward the server grants: its kind, its currency and amount, how often.

    ``per_day`` caps the claims of a player in one of the game's days (blank:
    no cap, a daily reward is once a day whatever it says). ``cooldown`` is the
    seconds between two claims. An ``ad`` reward with ``callback`` is granted
    only by the portal's signed callback.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rewards")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=REWARD_KINDS)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="rewards")
    amount = models.PositiveBigIntegerField()
    per_day = models.PositiveIntegerField(null=True, blank=True)
    cooldown = models.PositiveIntegerField(default=0, help_text="Seconds between two claims.")
    callback = models.BooleanField(
        default=False, help_text="An ad reward granted only by the portal's signed callback."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_reward_key")
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "a reward is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "kind", "currency", "amount"]
        list_filter: ClassVar[list[str]] = ["game", "kind"]

    def __str__(self) -> str:
        return self.title


class Claim(UUIDModel, TimestampedModel):
    """A reward granted to a player: on which of the game's days, and from where."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="claims")
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE, related_name="claims")
    day = models.DateField()
    amount = models.BigIntegerField(default=0)
    source = models.CharField(max_length=12, default="client")
    external_id = models.CharField(
        max_length=128, blank=True, default="", help_text="The portal's id of a callback."
    )

    class Meta:
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(
                fields=["reward", "external_id"],
                condition=~Q(external_id=""),
                name="karni_game_claim_external",
            )
        ]
        indexes: ClassVar[list[Any]] = [
            models.Index(fields=["player", "reward", "day"], name="karni_game_claim_day")
        ]

    class Karni:
        owner_field = "player__person__user"

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["reward", "player", "day", "amount", "source"]

    def __str__(self) -> str:
        return f"{self.reward_id} on {self.day}"


class Item(BaseModel):
    """A cosmetic of a game (a skin, a hat, a theme): sold for a currency, or for real money.

    ``slot`` is where it is worn: one equipped item per slot. ``price`` in
    ``currency`` sells it in the shop. ``real_money`` sells it through the cart
    of karni-commerce instead, at ``money_price`` (the sellable kind ``game_item``).
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="items")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    slot = models.SlugField(max_length=30, help_text="Where it is worn: hat, skin, trail.")
    currency = models.ForeignKey(
        Currency, null=True, blank=True, on_delete=models.PROTECT, related_name="items"
    )
    price = models.PositiveBigIntegerField(null=True, blank=True)
    real_money = models.BooleanField(default=False)
    money_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_item_key")
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "an item is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "slot", "price", "real_money"]
        list_filter: ClassVar[list[str]] = ["game", "slot"]

    def __str__(self) -> str:
        return self.title

    @property
    def for_sale(self) -> bool:
        """Sold in the shop for a currency."""
        return (
            self.is_active
            and not self.real_money
            and self.currency_id is not None
            and self.price is not None
        )


class Ownership(BaseModel):
    """An item a player owns, and whether it is equipped in its slot."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="owners")
    slot = models.SlugField(max_length=30)
    equipped = models.BooleanField(default=False)
    source = models.CharField(max_length=12, default="purchase")

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["player", "item"], name="karni_game_owned_once"),
            LiveUniqueConstraint(
                fields=["player", "slot"],
                condition=Q(equipped=True),
                name="karni_game_equipped_once",
            ),
        ]

    class Karni:
        owner_field = "player__person__user"
        cascade: ClassVar[dict[str, str]] = {"player": "an item owned is its player's"}

    class APIMeta:
        read_only: ClassVar[list[str]] = ["player", "item", "slot", "equipped", "source"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["item", "player", "equipped", "source"]

    def __str__(self) -> str:
        return f"{self.item_id} of {self.player_id}"


class Streak(BaseModel):
    """A player's daily streak in a game: days in a row they checked in, on the game's clock."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="streaks")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="streaks")
    current = models.PositiveIntegerField(default=0)
    best = models.PositiveIntegerField(default=0)
    last_day = models.DateField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["player", "game"], name="karni_game_streak_one")
        ]

    class Karni:
        owner_field = "player__person__user"
        cascade: ClassVar[dict[str, str]] = {
            "player": "a streak is its player's",
            "game": "a streak is of its game",
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = ["player", "game", "current", "best", "last_day"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["player", "game", "current", "best", "last_day"]

    def __str__(self) -> str:
        return f"{self.current} days"


class Achievement(BaseModel):
    """An achievement: unlocked by the server once its counter reaches its goal, over all time.

    ``reward`` (a reward of kind ``achievement``) is granted when it unlocks. A
    ``hidden`` one shows its title and description only once unlocked.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="achievements")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    counter = models.SlugField(max_length=50, help_text="The counter the game reports.")
    goal = models.PositiveBigIntegerField(default=1)
    hidden = models.BooleanField(default=False)
    reward = models.ForeignKey(
        Reward, null=True, blank=True, on_delete=models.SET_NULL, related_name="achievements"
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_achievement_key")
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "an achievement is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "counter", "goal", "game"]
        list_filter: ClassVar[list[str]] = ["game"]

    def __str__(self) -> str:
        return self.title


#: How often a mission may be completed.
MISSION_PERIODS = (("once", "Once"), ("daily", "Each day"), ("weekly", "Each week"))


class Mission(BaseModel):
    """A mission: its counter reaches its goal within its period; ``reward`` each time."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="missions")
    key = models.SlugField(max_length=50)
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    counter = models.SlugField(max_length=50)
    goal = models.PositiveBigIntegerField(default=1)
    period = models.CharField(max_length=6, choices=MISSION_PERIODS, default="daily")
    reward = models.ForeignKey(
        Reward, null=True, blank=True, on_delete=models.SET_NULL, related_name="missions"
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "key")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_mission_key")
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "a mission is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["title", "key", "counter", "goal", "period"]
        list_filter: ClassVar[list[str]] = ["game", "period"]

    def __str__(self) -> str:
        return self.title


class Progress(UUIDModel, TimestampedModel):
    """A player's count of one counter in a game, over all time or in one day or week."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="progress")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="+")
    counter = models.SlugField(max_length=50)
    period = models.CharField(max_length=6, default="all")
    period_start = models.DateField()
    value = models.BigIntegerField(default=0)

    class Meta:
        verbose_name_plural = "progress"
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(
                fields=["player", "game", "counter", "period", "period_start"],
                name="karni_game_progress_one",
            )
        ]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["player", "counter", "period", "value"]

    def __str__(self) -> str:
        return f"{self.counter}: {self.value}"


class Unlock(UUIDModel, TimestampedModel):
    """An achievement the server unlocked for a player (``created_at`` is when)."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="unlocks")
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name="unlocks")

    class Meta:
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(fields=["player", "achievement"], name="karni_game_unlock_one")
        ]

    class Karni:
        owner_field = "player__person__user"

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["achievement", "player", "created_at"]

    def __str__(self) -> str:
        return f"{self.achievement_id} by {self.player_id}"


class Completion(UUIDModel, TimestampedModel):
    """A mission a player completed in one period (``period_start``: the day or the Monday)."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="completions")
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="completions")
    period_start = models.DateField()

    class Meta:
        constraints: ClassVar[list[Any]] = [
            models.UniqueConstraint(
                fields=["player", "mission", "period_start"], name="karni_game_completion_one"
            )
        ]

    class Karni:
        owner_field = "player__person__user"

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["mission", "player", "period_start"]

    def __str__(self) -> str:
        return f"{self.mission_id} on {self.period_start}"


class ConfigValue(BaseModel):
    """A remote config value or a feature flag of a game, read by the client in one call.

    A config value is any JSON. A flag (``flag``) is on or off: ``value`` true
    with ``rollout`` the percent of players it is on for (the same players every
    time: a hash of the player and the key).
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="config")
    key = models.SlugField(max_length=64)
    value = models.JSONField(default=None, null=True, blank=True)
    flag = models.BooleanField(default=False, help_text="A feature flag: on or off.")
    rollout = models.PositiveSmallIntegerField(
        default=100, help_text="A flag's share of players, in percent."
    )
    description = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "config value"
        ordering = ("key",)
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(fields=["game", "key"], name="karni_game_config_key"),
            models.CheckConstraint(
                condition=Q(rollout__lte=100), name="karni_game_config_rollout_lte_100"
            ),
        ]

    class Karni:
        cascade: ClassVar[dict[str, str]] = {"game": "a config value is part of its game"}

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["key", "game", "flag", "rollout", "value"]
        list_filter: ClassVar[list[str]] = ["game", "flag"]
        inline_on = "game"

    def __str__(self) -> str:
        return self.key
