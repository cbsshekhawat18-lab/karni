"""Experimental. Remote config and feature flags per game, and the analytics a game may send.

:func:`values` gives a game's config (any JSON) and its flags, worked out
for a player: a flag with a rollout below 100 is on for that share of
players, the same players every time. ``GET /api/game/<game>/`` returns both
in the one call a client makes at boot.

:func:`track` checks analytics events against the game's ``analytics``
settings (a name it declares, its props with their types, at most 10, text up
to 100 characters) and publishes each one as the family event
``game.analytics.tracked``, for the project's own analytics to subscribe to.

Override / escape hatch: rows staff edit (``ConfigValue``); a subscriber of
``game.analytics.tracked`` stores or forwards the events where the project
wants them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from karni.events import publish

from karni_game.errors import game_error
from karni_game.models import ConfigValue, Game, Player

__all__ = ["MAX_EVENTS", "bucket", "track", "values"]

#: The most events one analytics request holds, and the longest text prop.
MAX_EVENTS = 20
MAX_TEXT = 100
_TYPES: dict[str, tuple[type, ...]] = {
    "int": (int,),
    "float": (int, float),
    "str": (str,),
    "bool": (bool,),
}


def bucket(player: Player, key: str) -> int:
    """The player's place for flag ``key``, 0 to 99, the same every time."""
    digest = hashlib.sha256(f"{player.pk}:{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def _on(row: ConfigValue, player: Player | None) -> bool:
    if not row.value:
        return False
    if row.rollout >= 100:
        return True
    return player is not None and bucket(player, row.key) < row.rollout


def values(game: Game, player: Player | None) -> tuple[dict[str, Any], dict[str, bool]]:
    """``(config, flags)`` of the game, the flags worked out for ``player``."""
    config: dict[str, Any] = {}
    flags: dict[str, bool] = {}
    for row in ConfigValue.objects.filter(game=game):
        if row.flag:
            flags[row.key] = _on(row, player)
        else:
            config[row.key] = row.value
    return config, flags


def _problem(schema: Mapping[str, Mapping[str, str]], event: Any) -> str | None:
    if not isinstance(event, dict):
        return "An event is an object with a name and props."
    name = str(event.get("name") or "")
    props = event.get("props", {}) or {}
    if name not in schema:
        return f"The game declares no analytics event {name!r}."
    if not isinstance(props, dict) or len(props) > 10:
        return "props is an object of at most 10 values."
    declared = schema[name]
    for prop, value in props.items():
        kind = declared.get(prop)
        if kind is None:
            return f"{name} declares no prop {prop!r}."
        if isinstance(value, bool) and kind != "bool":
            return f"{prop} is a {kind}."
        if not isinstance(value, _TYPES[kind]):
            return f"{prop} is a {kind}."
        if isinstance(value, str) and len(value) > MAX_TEXT:
            return f"{prop} is longer than {MAX_TEXT} characters."
    return None


def track(game: Game, player: Player | None, events: list[Any]) -> dict[str, Any]:
    """Publish the events the game declares; returns what was accepted and what refused."""
    if len(events) > MAX_EVENTS:
        raise game_error("GAME025", f"A request holds at most {MAX_EVENTS} analytics events.")
    schema = game.options().analytics
    rejected: list[dict[str, Any]] = []
    accepted = 0
    for index, event in enumerate(events):
        problem = _problem(schema, event)
        if problem is not None:
            rejected.append({"index": index, "code": "GAME025", "detail": problem})
            continue
        publish(
            "game.analytics.tracked",
            subject=game,
            person=player.person_id if player is not None else None,
            game=game.slug,
            player=str(player.pk) if player is not None else "",
            event=event["name"],
            props=dict(event.get("props", {}) or {}),
        )
        accepted += 1
    if events and not accepted:
        raise game_error(
            "GAME025",
            "None of the analytics events is one the game declares (its analytics settings).",
            rejected=rejected,
        )
    return {"accepted": accepted, "rejected": rejected}
