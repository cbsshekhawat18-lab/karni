"""The wallet under requests at the same time (PostgreSQL only: sqlite has no row locks).

Run it on PostgreSQL with the CI overlay::

    PYTHONPATH=../../.github/ci DATABASE_URL=postgres://postgres@127.0.0.1:55432/game \\
        python -m pytest --ds=karni_postgres_settings --no-migrations tests/test_concurrency.py
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection, connections

from karni_game import players, shop, wallet
from karni_game.errors import GameError
from karni_game.models import Currency, Game, Item, LedgerEntry, Ownership, Wallet

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="row locks need PostgreSQL (DATABASE_URL)"
    ),
]


def at_once(*work: Callable[[], Any]) -> list[Any]:
    """Run each function in its own thread and connection, released together."""
    barrier = threading.Barrier(len(work))
    results: list[Any] = [None] * len(work)

    def run(index: int, function: Callable[[], Any]) -> None:
        try:
            barrier.wait()
            results[index] = function()
        except Exception as exc:  # noqa: BLE001 - the test reads it
            results[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=pair) for pair in enumerate(work)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_two_purchases_at_once_never_spend_the_same_coins() -> None:
    game = Game.objects.create(slug="block-hopper", title="Block Hopper")
    coins = Currency.objects.create(game=game, key="coins", title="Coins")
    hat = Item.objects.create(
        game=game, key="red-cap", title="Red cap", slot="hat", currency=coins, price=60
    )
    cap = Item.objects.create(
        game=game, key="blue-cap", title="Blue cap", slot="hat", currency=coins, price=60
    )
    player = players.issue_guest("Swift Fox").player
    wallet.change(player, coins, 100, reason="grant")

    results = at_once(lambda: shop.buy(player, hat), lambda: shop.buy(player, cap))

    refused = [result for result in results if isinstance(result, GameError)]
    bought = [result for result in results if isinstance(result, dict)]
    assert len(bought) == 1 and len(refused) == 1, results
    assert refused[0].game_code == "GAME016"
    assert Wallet.objects.get(player=player).balance == 40
    assert Ownership.objects.filter(player=player).count() == 1
    assert LedgerEntry.objects.filter(reason="purchase").count() == 1


def test_two_credits_at_once_both_count_and_stop_at_the_cap() -> None:
    game = Game.objects.create(slug="block-hopper", title="Block Hopper")
    coins = Currency.objects.create(game=game, key="coins", title="Coins", cap=150)
    player = players.issue_guest("Swift Fox").player
    wallet.change(player, coins, 60, reason="grant")

    results = at_once(
        lambda: wallet.change(player, coins, 50, reason="reward"),
        lambda: wallet.change(player, coins, 50, reason="reward"),
    )

    assert not [result for result in results if isinstance(result, Exception)], results
    assert sorted(result.amount for result in results) == [40, 50]
    assert Wallet.objects.get(player=player).balance == 150
    entries = LedgerEntry.objects.filter(wallet__player=player).order_by("balance_after")
    assert [row.balance_after for row in entries] == [60, 110, 150]
