"""karni-game's error codes (prefix ``GAME``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain GAME001``
and ``docs/errors.md`` include them. Codes are permanent: never renumber or
reuse one; append new codes at the end. The HTTP status of each API code is in
docs/game-api.md.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_game"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="GAME001",
        title="karni-game is installed without the people contract",
        kind="check",
        source=f"{_SOURCE}.checks.people_installed (karni.GAME001)",
        why="A player is the game profile of a person (karni.people), so a guest who signs in "
        "keeps their progress and the person page, the merge and the erase see the player. "
        "Without karni.people the player table cannot be created.",
        fix="Set KARNI_PEOPLE = True above karni_settings(globals()) in config/settings.py "
        "(karni build writes it when karni.yaml lists the game module), then run migrate.",
    ),
    ErrorCode(
        code="GAME002",
        title="The request names no player",
        kind="exception",
        source=f"{_SOURCE}.api (HTTP 401)",
        why="Every save, score, wallet and progress call belongs to one player, found from "
        "the request alone: a signed-in account, or a guest's token. No endpoint takes a "
        "player's id from the client, so another player's progress is never reachable.",
        fix="Sign in, or call POST /api/game/guest/ once and send its token in the "
        "X-Player-Token header (KARNI_GAME_TOKEN_HEADER).",
    ),
    ErrorCode(
        code="GAME003",
        title="The guest token is unknown or revoked",
        kind="exception",
        source=f"{_SOURCE}.players.player_for_token (HTTP 401)",
        why="A guest token is issued once and kept as a hash. It is revoked when the guest is "
        "upgraded to an account (its progress is the account's then) and when staff revoke it.",
        fix="Drop the stored token. Sign in to the account it was upgraded to, or issue a new "
        "guest with POST /api/game/guest/.",
    ),
    ErrorCode(
        code="GAME004",
        title="The account has no person yet: its email is not verified",
        kind="exception",
        source=f"{_SOURCE}.players.player_for_user (HTTP 403)",
        why="An account is linked to a person only once its email is verified (the people "
        "contract), so nobody takes over another person's progress by signing up with their "
        "address. A player belongs to a person.",
        fix="Verify the account's email (the verification link or a sign-in with an email "
        "code), then call again. Until then the game can keep playing as a guest.",
    ),
    ErrorCode(
        code="GAME005",
        title="Guest play is off",
        kind="exception",
        source=f"{_SOURCE}.api.GuestView (HTTP 403)",
        why="The project's Settings, Games section has allow_guests off, so only signed-in "
        "accounts play.",
        fix="Sign in first, or turn allow_guests on (preferences game.allow_guests).",
    ),
    ErrorCode(
        code="GAME006",
        title="No active game has this slug",
        kind="exception",
        source=f"{_SOURCE}.api (HTTP 404)",
        why="Each path under /api/game/<game>/ names a Game row by its slug. A game that is "
        "not active answers as if it did not exist.",
        fix="Use the slug of a game in the admin (Karni games, Games), or turn it active. "
        "karni load puts a game declared in a content file in the database.",
    ),
    ErrorCode(
        code="GAME015",
        title="Too many requests of this kind",
        kind="exception",
        source=f"{_SOURCE}.throttling.PlayerRateThrottle (HTTP 429)",
        why="Writes are limited per player (KARNI_GAME_RATES), so a script cannot flood the "
        "boards, the wallet or the events.",
        fix="Wait retry_after seconds (the Retry-After header) and send it again, or raise the "
        "scope's rate in KARNI_GAME_RATES.",
    ),
    ErrorCode(
        code="GAME026",
        title="A game's settings do not validate",
        kind="exception",
        source=f"{_SOURCE}.models.Game.clean (karni_game.settings.GameSettings)",
        why="A game's settings (its time zone, save limits, streak grace, analytics schema) "
        "are read on every call. A value the server cannot use is refused when it is saved, "
        "not when a player meets it.",
        fix="Read the message: it names each field and what it takes "
        "(docs/game.md, Game settings).",
    ),
    ErrorCode(
        code="GAME028",
        title="The guest cannot be upgraded to this account",
        kind="exception",
        source=f"{_SOURCE}.players.upgrade (HTTP 409)",
        why="An upgrade merges a guest's person into the account's person, and the guest's "
        "progress into the account's player. It needs a guest token, a guest (not an account "
        "already), and two people the people contract can merge.",
        fix="Send the guest's token in X-Player-Token (or guest_token) with a signed-in, "
        "verified account. The message names the reason a merge was refused.",
    ),
    ErrorCode(
        code="GAME030",
        title="karni_game.urls is not included",
        kind="check",
        source=f"{_SOURCE}.checks.run_checks",
        why="The game API (guest tokens, saves, scores, the wallet) is mounted by one include "
        "line. Without it the client's calls answer 404.",
        fix='Add path("api/game/", include("karni_game.urls")) to config/urls.py, before '
        'path("api/", include("karni.api.urls")).',
    ),
    ErrorCode(
        code="GAME032",
        title="A game hook is registered wrongly",
        kind="exception",
        source=f"{_SOURCE}.hooks (save_migration, run_check)",
        why="A save migration is one step from a schema version (a whole number from 1) to "
        "the next, and each game has one step per version and one run check per board, so the "
        "server knows which code runs.",
        fix='Register one function per step (@hooks.save_migration("<game>", 1)) and per '
        'board (@hooks.run_check("<game>", "<board>")), or pass replace=True to swap one.',
    ),
)
