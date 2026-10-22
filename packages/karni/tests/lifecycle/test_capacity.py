"""CapacityField and reserve()/release(): the counter the database keeps at or above zero."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction

from karni.capacity import CapacityExceeded, release, reserve
from karni.conflicts import translate
from karni.errorcodes import KarniError
from tests.lifecycleapp.models import Pool, Stock

pytestmark = pytest.mark.django_db


def _stock(quantity: int = 3) -> Stock:
    return Stock.objects.create(name="VIP", quantity=quantity)


def _remaining(stock: Stock) -> int:
    return int(Stock.objects.values_list("remaining", flat=True).get(pk=stock.pk))


def test_a_new_row_starts_full() -> None:
    stock = _stock(5)
    assert stock.remaining == 5 and _remaining(stock) == 5


def test_reserve_takes_units_and_refuses_the_last_one_twice() -> None:
    stock = _stock(2)
    with transaction.atomic():
        assert reserve(stock, 2) == 0
    assert stock.remaining == 0 and _remaining(stock) == 0
    with pytest.raises(CapacityExceeded) as raised, transaction.atomic():
        reserve(stock)
    error = raised.value
    assert error.code == "E985" and error.status == 409 and isinstance(error, IntegrityError)
    assert error.details == {
        "resource": "lifecycleapp.Stock",
        "id": str(stock.pk),
        "field": "remaining",
        "remaining": 0,
        "requested": 1,
    }
    assert "is sold out (remaining = 0), but 1 was requested" in error.message
    assert _remaining(stock) == 0


def test_release_gives_units_back_but_never_above_the_total() -> None:
    stock = _stock(3)
    with transaction.atomic():
        reserve(stock, 2)
        assert release(stock, 1) == 2
    with pytest.raises(KarniError) as raised, transaction.atomic():
        release(stock, 2)  # only 1 is reserved
    assert raised.value.code == "E986" and "double release" in raised.value.message
    assert _remaining(stock) == 2


@pytest.mark.django_db(transaction=True)
def test_reserve_must_run_inside_a_transaction() -> None:
    stock = _stock()
    with pytest.raises(KarniError) as raised:
        reserve(stock)
    assert raised.value.code == "E986"
    assert "must run inside transaction.atomic()" in raised.value.message
    assert _remaining(stock) == 3


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_quantity_is_a_positive_integer(quantity: object) -> None:
    stock = _stock()
    with pytest.raises(KarniError, match="positive integer"), transaction.atomic():
        reserve(stock, quantity)  # type: ignore[arg-type]


def test_the_counter_is_never_written_directly() -> None:
    stock = _stock(3)
    stock.remaining = 99
    with pytest.raises(KarniError) as raised:
        stock.save()
    assert raised.value.code == "E986" and "reserve() / release()" in raised.value.message
    assert _remaining(stock) == 3


def test_a_stale_instance_does_not_undo_reservations() -> None:
    stock = _stock(5)
    stale = Stock.objects.get(pk=stock.pk)
    with transaction.atomic():
        reserve(stock, 4)
    stale.name = "renamed"  # a full save of an instance loaded before the reservation
    stale.save()
    assert _remaining(stock) == 1  # "remaining = remaining + 0", never "remaining = 5"


def test_changing_the_total_shifts_what_remains_in_sql() -> None:
    stock = _stock(5)
    with transaction.atomic():
        reserve(stock, 2)
    stock.quantity = 8
    stock.save()
    assert _remaining(stock) == 6
    assert stock.remaining == 6  # re-read on access after a shifted write
    stock.quantity = 4
    stock.save(update_fields=["quantity"])  # the counter follows even when not listed
    assert _remaining(stock) == 2


def test_lowering_the_total_below_what_is_reserved_is_refused_and_named() -> None:
    stock = _stock(5)
    with transaction.atomic():
        reserve(stock, 4)
    stock.quantity = 2
    with pytest.raises(CapacityExceeded) as raised:
        stock.save()
    error = raised.value
    assert error.code == "E985" and error.field == "quantity"
    assert "quantity cannot become 2 because 4 are already reserved" in error.message
    assert Stock.objects.values_list("quantity", "remaining").get(pk=stock.pk) == (5, 1)


def test_a_counter_without_a_total_needs_a_start_and_has_no_ceiling() -> None:
    pool = Pool.objects.create(name="licences")
    with transaction.atomic():
        assert release(pool, 10) == 10
        assert reserve(pool, 4) == 6
    assert Pool.objects.get(pk=pool.pk).units == 6


def test_reserve_needs_a_model_with_one_capacity_field() -> None:
    from tests.lifecycleapp.models import Room

    room = Room.objects.create(name="A")
    with pytest.raises(KarniError, match="has no CapacityField"), transaction.atomic():
        reserve(room)
    stock = _stock()
    with pytest.raises(KarniError, match="not a CapacityField"), transaction.atomic():
        reserve(stock, field="quantity")


# the database refuses an oversell from raw SQL


def _raw(sql: str, params: list[object]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def test_a_raw_update_below_zero_is_rejected() -> None:
    stock = _stock(1)
    table = connection.ops.quote_name(Stock._meta.db_table)
    with pytest.raises(IntegrityError) as raised, transaction.atomic():
        _raw(f"UPDATE {table} SET remaining = remaining - 2 WHERE id = %s", [stock.pk.hex])
    assert _remaining(stock) == 1
    error = translate(raised.value, model=Stock)
    assert isinstance(error, CapacityExceeded) and error.code == "E985"


def test_a_raw_update_above_the_total_is_rejected() -> None:
    stock = _stock(1)
    table = connection.ops.quote_name(Stock._meta.db_table)
    with pytest.raises(IntegrityError), transaction.atomic():
        _raw(f"UPDATE {table} SET remaining = 7 WHERE id = %s", [stock.pk.hex])
    assert _remaining(stock) == 1


def test_queryset_update_bypasses_the_model_but_not_the_check() -> None:
    stock = _stock(1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Stock.objects.filter(pk=stock.pk).update(remaining=-1)
