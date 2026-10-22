"""Real concurrency on PostgreSQL: separate connections in threads, released together by a barrier.

Each worker opens its own connection (Django connections are per thread) and
its own transaction, so these prove what the database does when two
requests race — not what one connection does in sequence. They need
PostgreSQL: SQLite serialises every writer on one file lock, which proves
nothing about row locks.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection, connections, transaction

from karni.capacity import CapacityExceeded, reserve
from karni.constraints import OverlapConflict
from karni.lifecycle import StateConflict
from tests.lifecycleapp.models import HAS_RANGES, Order, Room, Stock

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="row locks and EXCLUDE need PostgreSQL (CI's Postgres step runs these)",
    ),
]

TIMEOUT = 20


def race(workers: list[Callable[[], Any]]) -> list[Any]:
    """Run every worker in its own thread and connection; start them together; collect results."""
    barrier = threading.Barrier(len(workers), timeout=TIMEOUT)
    results: list[Any] = [None] * len(workers)

    def run(index: int, work: Callable[[], Any]) -> None:
        try:
            barrier.wait()
            results[index] = work()
        except Exception as exc:  # noqa: BLE001 - the result is what the test inspects
            results[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i, w)) for i, w in enumerate(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)
        assert not thread.is_alive(), "a worker hung"
    return results


# lifecycle: two transitions from the same state


def test_two_concurrent_transitions_from_one_state_exactly_one_wins() -> None:
    order = Order.objects.create(title="race")
    loaded = [Order.objects.get(pk=order.pk) for _ in range(2)]  # both believe "draft"

    def move(instance: Order, target: str) -> Callable[[], str]:
        def work() -> str:
            with transaction.atomic():
                instance.transition("status", target)
                time.sleep(0.2)  # hold the row lock: the other UPDATE must wait for it
            return target

        return work

    results = race([move(loaded[0], "confirmed"), move(loaded[1], "cancelled")])
    winners = [r for r in results if isinstance(r, str)]
    losers = [r for r in results if isinstance(r, StateConflict)]
    assert len(winners) == 1 and len(losers) == 1, results
    assert losers[0].details == {
        "resource": "lifecycleapp.Order",
        "id": str(order.pk),
        "field": "status",
        "expected": "draft",
        "current": winners[0],
    }
    assert Order.objects.get(pk=order.pk).status == winners[0]
    from karni.audit.models import ChangeLog

    assert ChangeLog.objects.for_object(order).filter(action="transition").count() == 1


def test_the_loser_waited_on_the_row_lock_then_matched_nothing() -> None:
    order = Order.objects.create(title="lock")
    first, second = (Order.objects.get(pk=order.pk) for _ in range(2))
    second_pid: list[int] = []
    updated = threading.Event()

    def holder() -> str:
        with transaction.atomic():
            first.transition("status", "confirmed")
            updated.set()
            deadline = time.monotonic() + TIMEOUT
            with connection.cursor() as cursor:  # until the other UPDATE is blocked on our lock
                while time.monotonic() < deadline:
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                        [second_pid[0] if second_pid else 0],
                    )
                    row = cursor.fetchone()
                    if row is not None and row[0] == "Lock":
                        return "blocked the other"
                    time.sleep(0.02)
        return "never blocked"

    def contender() -> Any:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            second_pid.append(cursor.fetchone()[0])
        updated.wait(TIMEOUT)
        with transaction.atomic():
            second.transition("status", "cancelled")
        return "won"

    results = race([holder, contender])
    assert results[0] == "blocked the other"
    assert isinstance(results[1], StateConflict) and results[1].details["current"] == "confirmed"
    assert Order.objects.get(pk=order.pk).status == "confirmed"


# capacity: the last unit, then a stampede


def _buy(stock: Stock, quantity: int = 1) -> Callable[[], Any]:
    def work() -> Any:
        with transaction.atomic():
            return reserve(Stock.objects.get(pk=stock.pk), quantity)

    return work


def test_two_transactions_buying_the_last_unit_exactly_one_wins() -> None:
    stock = Stock.objects.create(name="last", quantity=1)
    results = race([_buy(stock), _buy(stock)])
    assert sorted(type(r).__name__ for r in results) == ["CapacityExceeded", "int"], results
    loser = next(r for r in results if isinstance(r, CapacityExceeded))
    assert loser.details["remaining"] == 0 and loser.details["requested"] == 1
    assert Stock.objects.get(pk=stock.pk).remaining == 0


@pytest.mark.parametrize(("workers", "capacity"), [(12, 5), (20, 1), (16, 16)])
def test_a_stampede_of_n_buyers_gets_exactly_k_units(workers: int, capacity: int) -> None:
    stock = Stock.objects.create(name="stampede", quantity=capacity)
    results = race([_buy(stock) for _ in range(workers)])
    sold = [r for r in results if isinstance(r, int)]
    refused = [r for r in results if isinstance(r, CapacityExceeded)]
    assert len(sold) == capacity and len(refused) == workers - capacity, results
    assert sorted(sold) == list(range(capacity))  # every remaining count handed out once
    assert Stock.objects.get(pk=stock.pk).remaining == 0  # never negative: the CHECK and the lock


def test_mixed_quantities_never_oversell() -> None:
    stock = Stock.objects.create(name="mixed", quantity=10)
    results = race([_buy(stock, quantity) for quantity in (3, 4, 2, 5, 1, 3, 2)])
    taken = sum(
        q for q, r in zip((3, 4, 2, 5, 1, 3, 2), results, strict=True) if isinstance(r, int)
    )
    remaining = Stock.objects.get(pk=stock.pk).remaining
    assert taken + remaining == 10 and remaining >= 0
    assert all(isinstance(r, int | CapacityExceeded) for r in results), results


# no_overlap: everyone wants the same slot


@pytest.mark.skipif(not HAS_RANGES, reason="range columns need psycopg")
def test_concurrent_bookings_of_one_slot_exactly_one_wins() -> None:
    import datetime as dt

    from psycopg.types.range import Range

    from tests.lifecycleapp.models import Reservation

    room = Room.objects.create(name="Contested")
    start = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)

    def book(offset_minutes: int) -> Callable[[], Any]:
        def work() -> Any:
            lower = start + dt.timedelta(minutes=offset_minutes)
            with transaction.atomic():
                return Reservation.objects.create(
                    room=room, during=Range(lower, lower + dt.timedelta(hours=1))
                ).pk

        return work

    results = race([book(minutes) for minutes in (0, 10, 20, 30, 40, 50, 0, 15)])
    booked = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, OverlapConflict)]
    assert len(booked) == 1 and len(refused) == 7, results
    assert Reservation.objects.filter(room=room).count() == 1
