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
from karni.models import BaseModel
from pydantic import ValidationError as PydanticError

from karni_game import conf
from karni_game.gamesettings import GameSettings

#: A game's settings, or its slug, that the server cannot use.
SETTINGS_CODE = "GAME026"

__all__ = ["RESERVED_SLUGS", "Game", "Player"]

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
