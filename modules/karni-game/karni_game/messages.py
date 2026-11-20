"""Experimental. The message karni-game sends, under a stable kind name (``karni.notify``).

* ``game.achievement_unlocked``, to the player's account, in the inbox only:
  the server unlocked an achievement (:mod:`karni_game.progress`). A guest
  has no inbox, so a guest gets nothing.

It renders ``karni_game/email/achievement_unlocked_subject.txt`` and
``_body.txt`` with ``game`` and ``achievement``.

Override / escape hatch: put a template of the same name earlier in
``TEMPLATES`` ``DIRS``, switch the kind off in Settings, Emails, or declare it
again in your own ``messages.py`` with other ``channels=``.
"""

from __future__ import annotations

from karni.mail import register_kind

register_kind(
    "game.achievement_unlocked",
    title="Achievement unlocked",
    template="karni_game/email/achievement_unlocked",
    audience="the player, when they have an account",
    describe="The game unlocked an achievement for the player.",
    fields={
        "game.title": "The game's title",
        "achievement.title": "The achievement's title",
        "achievement.description": "What it is for",
    },
    channels=("inbox",),
    samples={
        "game": {"title": "Block Hopper"},
        "achievement": {"title": "Collector", "description": "Collect 300 coins."},
    },
    replace=False,
)
