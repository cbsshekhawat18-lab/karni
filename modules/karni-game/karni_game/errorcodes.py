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
    ErrorCode(
        code="GAME007",
        title="The save is larger than the game allows",
        kind="exception",
        source=f"{_SOURCE}.saves.write (HTTP 413)",
        why="A save is read and written whole on every sync, so each game caps its size "
        "(max_save_bytes in its settings, at most KARNI_GAME_MAX_SAVE_BYTES).",
        fix="Keep less in the save (derive what can be derived), or raise the game's "
        "max_save_bytes in its settings.",
    ),
    ErrorCode(
        code="GAME008",
        title="The save changed on the server: a stale write",
        kind="exception",
        source=f"{_SOURCE}.saves (HTTP 409)",
        why="Every write names the version it started from (base_version). Another device "
        "wrote since, so this write would lose that one's progress. The server's version "
        "counter decides, not a device's clock.",
        fix="Read the server's copy in the answer's save, choose or combine, and write again "
        "with base_version set to its version.",
    ),
    ErrorCode(
        code="GAME009",
        title="The save's schema version is not one the server knows",
        kind="exception",
        source=f"{_SOURCE}.saves.migrate (HTTP 400)",
        why="schema_version is the shape of the save's data. The server migrates an older "
        "save up to the game's save_schema_version, and cannot read a newer one: the "
        "client is ahead of the server.",
        fix="Raise the game's save_schema_version (and register the migration to it) before "
        "shipping a client that writes the new shape.",
    ),
    ErrorCode(
        code="GAME010",
        title="A save migration is missing",
        kind="exception",
        source=f"{_SOURCE}.saves.migrate",
        why="The game saves a newer schema than a stored save, and each step from one schema "
        "version to the next is a function the project registers. A missing step would hand "
        "the client data of a shape it does not read.",
        fix='Register the step in <app>/game.py: @hooks.save_migration("<game>", n) on a '
        "function that takes the data of version n and returns the data of n + 1.",
    ),
    ErrorCode(
        code="GAME011",
        title="Not a slot name, or no free slot",
        kind="exception",
        source=f"{_SOURCE}.saves (HTTP 400)",
        why="A slot is named in the path (a lowercase letter or digit, then up to 39 more, "
        "_ or -), and each game keeps at most max_slots slots per player.",
        fix="Use a slot name such as main or slot-2, or write to a slot the player has.",
    ),
    ErrorCode(
        code="GAME012",
        title="No active board has this key in the game",
        kind="exception",
        source=f"{_SOURCE}.scores.find_board (HTTP 404)",
        why="A score goes to one board of one game, named by its key in the path. A board "
        "that is not active answers as if it did not exist.",
        fix="Use the key of one of the game's boards (GET /api/game/<game>/ lists them), or "
        "turn the board active in the admin.",
    ),
    ErrorCode(
        code="GAME013",
        title="The score is outside the board's plausible range",
        kind="exception",
        source=f"{_SOURCE}.scores.submit (HTTP 400)",
        why="A client can send any number, so each board names the lowest and the highest "
        "score a real run can make (min_value, max_value), and refuses the rest.",
        fix="Send the score the run made. When real runs go beyond the range, widen the "
        "board's min_value or max_value.",
    ),
    ErrorCode(
        code="GAME014",
        title="The run is missing, too large, or does not check out",
        kind="exception",
        source=f"{_SOURCE}.scores.submit (HTTP 400)",
        why="A board may ask every score for its run (the seed and the input log a "
        "deterministic game replays), a daily board for a run on the day's seed, and the "
        "project's run check may refuse a run.",
        fix="Send run: {seed, inputs, duration_ms} with the score, use today's seed (GET "
        "/api/game/<game>/daily/) on a daily board, and keep the run under "
        "KARNI_GAME_MAX_RUN_BYTES.",
    ),
    ErrorCode(
        code="GAME029",
        title="The player is banned from the boards",
        kind="exception",
        source=f"{_SOURCE}.scores.submit, karni_game.multiplayer (HTTP 403)",
        why="Staff banned the player (Game moderator, ban): their scores no longer count, they "
        "are on no board and get no realtime token. Their saves and wallet stay theirs.",
        fix="Staff unban the player in the admin or with POST /api/game-players/<id>/unban/.",
    ),
    ErrorCode(
        code="GAME033",
        title="The intent was used already with another request",
        kind="exception",
        source=f"{_SOURCE}.intents.once (HTTP 409)",
        why="An intent names one action, so a retry of a score, a claim or a purchase never "
        "counts twice. A second action under the same intent would be lost.",
        fix="Make a new intent (a UUID) for each new action, and send the same body when you "
        "retry one.",
    ),
)
