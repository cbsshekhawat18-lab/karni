"""karni-game's Celery tasks.

``karni_game.tasks.prune_intents`` deletes the retry keys (intents) older than
``KARNI_GAME_INTENT_DAYS``. Schedule it once a day (docs/scheduling.md)::

    CELERY_BEAT_SCHEDULE = {
        "game-prune-intents": {"task": "karni_game.tasks.prune_intents", "schedule": 86400},
    }
"""

from __future__ import annotations

from celery import shared_task

from karni_game import intents


@shared_task(name="karni_game.tasks.prune_intents")
def prune_intents() -> int:
    """Delete the old intents. Returns how many."""
    return intents.prune()
