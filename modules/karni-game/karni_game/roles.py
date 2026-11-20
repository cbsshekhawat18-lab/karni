"""The roles karni-game declares (the ``karni.roles`` entry point).

* ``game-manager``: everything of the games: the games and what they declare
  (boards, currencies, rewards, items, achievements, missions, config), the
  players, the flagged runs, the wallets and their ledgers.
* ``game-moderator``: the players and the scores: reads them, bans and
  unbans players from the boards, accepts and rejects flagged runs. No
  wallet, no config.

Override / escape hatch: ``KARNI_GAME_ROLES = False`` declares neither, a
role of the same slug in ``KARNI_ROLES`` replaces one, and the permission
matrix changes their grants without a deploy.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MODERATOR_ACTIONS", "declared", "manager_grants", "moderator_grants"]


def manager_grants() -> dict[str, str]:
    # The Games section of Settings names this role (change="role:game-manager"), so it
    # needs no grant on karni.preferences, which a project may not install.
    return {"karni_game.*:*": "all", "people.person:view": "all"}


#: What a moderator does, by model: read, and the actions that keep the boards fair.
MODERATOR_ACTIONS: dict[str, tuple[str, ...]] = {
    "game": ("view",),
    "board": ("view",),
    "player": ("view", "ban", "unban"),
    "score": ("view", "accept", "reject"),
}


def moderator_grants() -> dict[str, str]:
    from django.apps import apps

    known = {model._meta.model_name for model in apps.get_app_config("karni_game").get_models()}
    grants = {
        f"karni_game.{model}:{action}": "all"
        for model, actions in MODERATOR_ACTIONS.items()
        if model in known
        for action in actions
    }
    grants["people.person:view"] = "all"
    return grants


def declared() -> dict[str, Any]:
    """``{slug: spec}`` for ``KARNI_ROLES``' merge, or ``{}`` when the app is not installed."""
    from django.apps import apps

    from karni_game import conf

    if not conf.get("KARNI_GAME_ROLES") or not apps.ready or not apps.is_installed("karni_game"):
        return {}
    return {
        "game-manager": {
            "name": "Game manager",
            "description": "Runs the games: what each declares, the players, the flagged runs, "
            "the wallets and their ledgers.",
            "grants": manager_grants(),
        },
        "game-moderator": {
            "name": "Game moderator",
            "description": "Keeps the boards fair: reads players and scores, bans players from "
            "the boards, accepts and rejects flagged runs.",
            "grants": moderator_grants(),
        },
    }
