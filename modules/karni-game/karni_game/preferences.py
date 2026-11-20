"""Experimental. karni-game's settings section: who may play, and who may read the boards.

Read with ``preferences.value("game.allow_guests", True)`` (``karni.preferences``).
Without ``karni.preferences`` installed every value is its default. A game's own
settings (its clock, its save limits) are on the game (``Game.settings``).
"""

from __future__ import annotations

from karni import preferences
from pydantic import Field


@preferences.section("game", title="Games", change="role:game-manager")
class GamePreferences(preferences.Section):
    """Who plays the project's games, and who reads their boards."""

    allow_guests: bool = Field(
        True,
        description="Anyone may play as a guest, with no account, and keep their progress "
        "when they sign in. Off: only signed-in accounts play.",
    )
    public_boards: bool = Field(
        True, description="Anyone may read the leaderboards. Off: only players read them."
    )
