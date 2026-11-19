"""Settings vocabulary for karni-game.

:data:`DEFAULTS` is the module's settings fragment, exposed through the
``karni.settings`` entry point, so :func:`karni.conf.karni_settings` merges it
into every project that installs the module. :func:`get` is the accessor
every ``karni_game`` module reads settings through.

Override / escape hatch: define any of these names in your ``settings.py`` or
set the matching environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

#: The rate of each limited kind of write, per player (``guest`` per client address,
#: ``results`` per game, ``callback`` per portal), in DRF's ``"<number>/<period>"``.
DEFAULT_RATES: dict[str, str | None] = {
    "guest": "10/hour",
    "save": "60/min",
    "score": "30/min",
    "progress": "60/min",
    "events": "30/min",
    "claim": "30/min",
    "buy": "30/min",
    "token": "20/min",
    "results": "600/min",
    "callback": "600/min",
}

DEFAULTS: dict[str, Any] = {
    # The rates of the limited writes, by scope (docs/game-api.md, Rate limits). A
    # project's dict is laid over these: {"score": "10/min"} changes one, None turns one off.
    "KARNI_GAME_RATES": dict(DEFAULT_RATES),
    # The header a guest sends its token in.
    "KARNI_GAME_TOKEN_HEADER": env("KARNI_GAME_TOKEN_HEADER", default="X-Player-Token"),
    # The origins a portal build calls the game API from (https://games.example), or "*".
    # Only /api/game/, only with a token (X-Player-Token or a JWT), never with cookies.
    "KARNI_GAME_CORS_ORIGINS": env.list("KARNI_GAME_CORS_ORIGINS", default=[]),
    # The secret a realtime server of the project's own shares: it signs the player
    # tokens Karni issues (HS256) and the results the server reports. Blank: no
    # multiplayer (karni.GAME027 when a client asks for a token).
    "KARNI_GAME_SERVER_SECRET": env("KARNI_GAME_SERVER_SECRET", default=""),
    # The iss claim of the player token.
    "KARNI_GAME_TOKEN_ISSUER": env("KARNI_GAME_TOKEN_ISSUER", default="karni-game"),
    # How long a player token for the realtime server lives, in seconds.
    "KARNI_GAME_TOKEN_SECONDS": env.int("KARNI_GAME_TOKEN_SECONDS", default=300),
    # Portals that call back when an ad was watched: {name: {"secret": "...",
    # "verifier": "dotted.path.Verifier"}}. The verifier defaults to
    # karni_game.signatures.HmacVerifier (X-Karni-Timestamp and X-Karni-Signature).
    "KARNI_GAME_PORTALS": {},
    # How far a signed request's timestamp may be from the server's clock, in seconds.
    "KARNI_GAME_SIGNATURE_TOLERANCE": env.int("KARNI_GAME_SIGNATURE_TOLERANCE", default=300),
    # How long an ad reward's intent token (POST rewards/<key>/intent/) is valid, in seconds.
    "KARNI_GAME_AD_INTENT_SECONDS": env.int("KARNI_GAME_AD_INTENT_SECONDS", default=3600),
    # How many days a write's intent (the retry key) is kept.
    "KARNI_GAME_INTENT_DAYS": env.int("KARNI_GAME_INTENT_DAYS", default=7),
    # The largest save any game may allow, in bytes (a game's max_save_bytes stays below it).
    "KARNI_GAME_MAX_SAVE_BYTES": env.int("KARNI_GAME_MAX_SAVE_BYTES", default=1024 * 1024),
    # How far back a score's played_at (when it was played, offline) is trusted, in seconds.
    # A score played before midnight and sent after lands on the board of the day it was
    # played. Older is GAME036. A played_at more than a minute ahead of the server is too.
    "KARNI_GAME_PLAYED_AT_WINDOW": env.int("KARNI_GAME_PLAYED_AT_WINDOW", default=86400),
    # The largest run record (seed, input log, meta) a score may carry, in bytes.
    "KARNI_GAME_MAX_RUN_BYTES": env.int("KARNI_GAME_MAX_RUN_BYTES", default=256 * 1024),
    # The class that merges two players (an upgrade, or two people merged):
    # a subclass of karni_game.merge.Merger.
    "KARNI_GAME_MERGER": env("KARNI_GAME_MERGER", default="karni_game.merge.Merger"),
    # The function that gives a game's seed of a day: seed(game, day) -> int.
    "KARNI_GAME_DAILY_SEED": env("KARNI_GAME_DAILY_SEED", default="karni_game.daily.daily_seed"),
    # Import <app>/game.py of every installed app at startup (save migrations, run checks).
    "KARNI_GAME_AUTODISCOVER": env.bool("KARNI_GAME_AUTODISCOVER", default=True),
    # Declare the roles game-manager and game-moderator (the karni.roles entry point).
    "KARNI_GAME_ROLES": env.bool("KARNI_GAME_ROLES", default=True),
}
"""The karni-game settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """The effective value of a karni-game setting: the project's, else :data:`DEFAULTS`."""
    return getattr(settings, name, DEFAULTS[name])


def rate(scope: str) -> str | None:
    """The rate of ``scope``: the project's ``KARNI_GAME_RATES`` over :data:`DEFAULT_RATES`."""
    rates = {**DEFAULT_RATES, **dict(get("KARNI_GAME_RATES") or {})}
    value = rates.get(scope)
    return str(value) if value else None
