"""The game's server hooks: the run check of its boards (karni_game.hooks).

karni-game imports this module at startup. Every score on the distance and
daily boards comes with its run (requires_run in content/game.yaml): the seed
and the inputs that @karni/game/sim recorded (toRunRecord), with the run's
own score, its ticks and its state hash in ``meta``. The check answers
"accept", "flag" (held for staff) or "reject" before the score counts.

It checks what the server can check without the game's rules: the run is one
of the simulation's, it claims the score it is sent with, its length agrees
with its ticks, and the score is one a run of that length can reach. Replaying
the run itself needs the rules, which are TypeScript: `verify()` of
@karni/game/sim does it, and the game's tests replay recorded runs.
"""

from typing import Any

from karni_game import hooks

GAME = "__GAME_SLUG__"
#: The fastest the runner goes, in units a second (src/rules/world.ts maxSpeed).
MAX_SPEED = 320
#: Points a coin is worth, and the most coins a stretch of track holds per 100 units.
COIN_POINTS = 5
COINS_PER_100 = 4


def plausible(score: int, run: dict[str, Any] | None) -> str:
    """The run check of both boards: a score its own run can stand behind."""
    meta = (run or {}).get("meta") or {}
    if meta.get("karni_sim") != 1:
        return "flag"  # not a run of the simulation: staff look at it
    if meta.get("score") != score:
        return "reject"  # the score is not the one the run says it reached
    ticks, dt = meta.get("ticks"), meta.get("dt")
    if not isinstance(ticks, int) or not isinstance(dt, int | float) or ticks <= 0 or dt <= 0:
        return "flag"
    seconds = ticks * dt
    duration = (run or {}).get("duration_ms")
    if isinstance(duration, int | float) and abs(duration / 1000 - seconds) > 1:
        return "flag"
    farthest = MAX_SPEED * seconds
    ceiling = farthest / 10 + farthest / 100 * COINS_PER_100 * COIN_POINTS
    return "accept" if score <= ceiling + 10 else "flag"


hooks.run_check(GAME, "distance")(plausible)
hooks.run_check(GAME, "daily")(plausible)
