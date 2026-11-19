"""One player never reads or changes another player's saves, scores, wallet or progress.

Every route of ``karni_game.urls`` is called by a second player (and by nobody), and
the first player's rows are the same afterwards. A route added without a line here
fails :func:`test_every_route_is_covered`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.urls import get_resolver

from karni_game import wallet
from karni_game.models import (
    Achievement,
    Best,
    Board,
    Claim,
    Currency,
    Game,
    Item,
    LedgerEntry,
    Mission,
    Ownership,
    Player,
    Progress,
    Reward,
    Save,
    Score,
    Streak,
    Unlock,
    Wallet,
)
from tests.conftest import Guest

G = "/api/game/block-hopper/"

#: Every route, as the second player calls it: (url name, method, path, body).
CALLS: list[tuple[str, str, str, Any]] = [
    ("me", "get", "/api/game/me/", None),
    ("me", "patch", "/api/game/me/", {"handle": "Taken Over"}),
    ("upgrade", "post", "/api/game/upgrade/", {}),
    ("game", "get", G, None),
    ("saves", "get", f"{G}saves/", None),
    ("save", "get", f"{G}saves/main/", None),
    ("save", "put", f"{G}saves/main/", {"data": {"x": 1}, "schema_version": 1, "base_version": 1}),
    ("save", "delete", f"{G}saves/main/", None),
    ("board", "get", f"{G}boards/high/", None),
    ("board-me", "get", f"{G}boards/high/me/", None),
    ("scores", "post", f"{G}boards/high/scores/", {"value": 1}),
    ("wallet", "get", f"{G}wallet/", None),
    ("ledger", "get", f"{G}wallet/ledger/", None),
    ("rewards", "get", f"{G}rewards/", None),
    ("claim", "post", f"{G}rewards/ad-coins/claim/", {}),
    ("intent", "post", f"{G}rewards/ad-coins/intent/", {}),
    ("shop", "get", f"{G}shop/", None),
    ("buy", "post", f"{G}shop/red-cap/buy/", {}),
    ("equip", "post", f"{G}items/red-cap/equip/", {}),
    ("unequip", "post", f"{G}items/red-cap/unequip/", {}),
    ("daily", "get", f"{G}daily/", None),
    ("check-in", "post", f"{G}daily/check-in/", {}),
    ("progress", "post", f"{G}progress/", {"events": [{"counter": "coins", "amount": 1}]}),
    ("achievements", "get", f"{G}achievements/", None),
    ("missions", "get", f"{G}missions/", None),
    ("events", "post", f"{G}events/", {"events": [{"name": "start"}]}),
    ("multiplayer-token", "post", f"{G}multiplayer/token/", {}),
    ("multiplayer-results", "post", f"{G}multiplayer/results/", {"match": "m", "results": []}),
    ("callback", "post", "/api/game/callbacks/arcade/", {"intent": "x", "event_id": "y"}),
    ("guest", "post", "/api/game/guest/", {}),
]


@pytest.fixture
def world(game: Game, guest: Guest) -> dict[str, Any]:
    """The first player, with a bit of everything."""
    game.settings = {"analytics": {"start": {}}}
    game.save()
    coins = Currency.objects.create(game=game, key="coins", title="Coins")
    Board.objects.create(game=game, key="high", title="High")
    Item.objects.create(
        game=game, key="red-cap", title="Red cap", slot="hat", currency=coins, price=50
    )
    Reward.objects.create(
        game=game, key="ad-coins", title="Ad", kind="ad", currency=coins, amount=5, per_day=9
    )
    Reward.objects.create(
        game=game, key="daily", title="Daily", kind="daily", currency=coins, amount=5
    )
    Achievement.objects.create(game=game, key="hoard", title="Hoard", counter="coins", goal=1)
    Mission.objects.create(game=game, key="daily-coins", title="Coins", counter="coins", goal=1)
    player = Player.objects.get(pk=guest.player_id)
    wallet.change(player, coins, 500, reason="grant")
    guest.put(f"{G}saves/main/", {"data": {"secret": "mine"}, "schema_version": 1, "base_version": 0})
    guest.post(f"{G}boards/high/scores/", {"value": 900})
    guest.post(f"{G}shop/red-cap/buy/")
    guest.post(f"{G}items/red-cap/equip/")
    guest.post(f"{G}rewards/ad-coins/claim/")
    guest.post(f"{G}daily/check-in/")
    guest.post(f"{G}progress/", {"events": [{"counter": "coins", "amount": 1}]})
    return {"player": player}


def state(player: Player) -> str:
    """Everything of the player's, as text, to compare before and after."""
    rows: dict[str, Any] = {
        "player": list(Player._base_manager.filter(pk=player.pk).values("handle", "token_hash")),
        "saves": list(Save._base_manager.filter(player=player).values("slot", "data", "version")),
        "scores": list(Score.objects.filter(player=player).values("value", "status")),
        "bests": list(Best.objects.filter(player=player).values("period", "value")),
        "wallets": list(Wallet.objects.filter(player=player).values("balance")),
        "ledger": LedgerEntry.objects.filter(wallet__player=player).count(),
        "items": list(Ownership._base_manager.filter(player=player).values("equipped")),
        "claims": Claim.objects.filter(player=player).count(),
        "streaks": list(Streak.objects.filter(player=player).values("current")),
        "progress": list(Progress.objects.filter(player=player).values("period", "value")),
        "unlocks": Unlock.objects.filter(player=player).count(),
    }
    return json.dumps(rows, sort_keys=True, default=str)


@pytest.mark.parametrize("name,method,path,body", CALLS, ids=[f"{c[1]} {c[0]}" for c in CALLS])
def test_another_player_never_reaches_the_first(
    world: dict[str, Any], other: Guest, api: Any, name: str, method: str, path: str, body: Any
) -> None:
    first = world["player"]
    before = state(first)
    for caller in (other.client, api):
        call = getattr(caller, method)
        answer = call(path, body, format="json") if body is not None else call(path)
        text = answer.content.decode()
        assert "mine" not in text  # the first player's save
        assert first.token_hash not in text
        if name not in ("board", "board-me"):
            assert "Swift Fox" not in text  # the first player's handle, off the boards
    assert state(first) == before


def test_every_route_is_covered() -> None:
    routes = {
        pattern.name
        for pattern in get_resolver("karni_game.urls").url_patterns
        if getattr(pattern, "name", None)
    }
    assert routes == {name for name, *_ in CALLS}
