"""A game's own settings (``Game.settings``), checked by a Pydantic model.

Staff edit them as JSON in the admin or ``/api/games/``. Every field has a
default, so ``{}`` is a valid game. A value the model refuses is ``GAME026``
when the game is saved.

Override / escape hatch: subclass :class:`GameSettings`, add fields, and
read them with ``GameSettings.model_validate(game.settings)`` in your own
code; the server keeps the fields it knows and ignores the others.
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["PROP_TYPES", "GameSettings"]

#: The types an analytics prop may declare.
PROP_TYPES = ("int", "float", "str", "bool")

PropType = Literal["int", "float", "str", "bool"]


class GameSettings(BaseModel):
    """What the server needs to know about one game."""

    model_config = ConfigDict(extra="allow")

    timezone: str = Field(
        "UTC", description="The game's clock: an IANA time zone. A day starts at midnight there."
    )
    save_schema_version: int = Field(
        1, ge=1, le=10_000, description="The shape of a save's data the game writes now."
    )
    max_save_bytes: int = Field(
        64 * 1024, ge=256, description="The largest save, in bytes of its JSON."
    )
    max_slots: int = Field(5, ge=1, le=50, description="How many save slots a player may have.")
    streak_grace_days: int = Field(
        1, ge=0, le=7, description="Days a player may miss and keep their daily streak."
    )
    max_progress_step: int = Field(
        1000, ge=1, description="The largest amount one progress event may add to a counter."
    )
    analytics: dict[str, dict[str, PropType]] = Field(
        default_factory=dict,
        description="The analytics events the game may send: {name: {prop: type}}.",
    )

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(  # karni: bare-raise-ok - pydantic turns it into a field error
                f"{value!r} is not an IANA time zone. Use one such as UTC or Europe/Paris."
            ) from exc
        return value

    @field_validator("analytics")
    @classmethod
    def _event_names(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for name, props in value.items():
            if not name or len(name) > 64 or not name.replace("_", "").replace(".", "").isalnum():
                raise ValueError(  # karni: bare-raise-ok - pydantic turns it into a field error
                    f"{name!r} is not an event name: letters, digits, _ and ., up to 64."
                )
            if len(props) > 10:
                raise ValueError(  # karni: bare-raise-ok - pydantic turns it into a field error
                    f"{name!r} declares {len(props)} props: at most 10."
                )
        return value
