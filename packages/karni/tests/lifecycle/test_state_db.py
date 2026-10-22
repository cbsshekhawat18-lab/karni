"""The database itself refuses an undeclared state: raw SQL, bypassing the ORM, on any backend."""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from karni.conflicts import translate
from karni.lifecycle import IllegalTransition
from tests.lifecycleapp.models import Order

pytestmark = pytest.mark.django_db


def _raw(sql: str, params: list[object]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def _table() -> str:
    return connection.ops.quote_name(Order._meta.db_table)


def test_a_raw_update_to_an_undeclared_state_is_rejected() -> None:
    order = Order.objects.create(title="o")
    with pytest.raises(IntegrityError) as raised, transaction.atomic():
        _raw(f"UPDATE {_table()} SET status = %s WHERE id = %s", ["shipped", order.pk.hex])
    assert Order.objects.get(pk=order.pk).status == "draft"
    error = translate(raised.value, model=Order)
    assert isinstance(error, IllegalTransition) and error.code == "E980"
    assert "allows only the declared states" in error.message


def test_a_raw_insert_of_an_undeclared_state_is_rejected() -> None:
    now = "2026-10-21 10:00:00"
    with pytest.raises(IntegrityError), transaction.atomic():
        _raw(
            f"INSERT INTO {_table()} (id, created_at, updated_at, title, status) "
            "VALUES (%s, %s, %s, %s, %s)",
            [uuid.uuid4().hex, now, now, "raw", "teleported"],
        )
    assert Order.objects.count() == 0


def test_a_raw_update_to_a_declared_state_is_accepted() -> None:
    # The CHECK knows the states, not the transitions: transitions are the model's job
    # (QuerySet.update() and raw SQL bypass them, like every other model rule).
    order = Order.objects.create(title="o")
    _raw(f"UPDATE {_table()} SET status = %s WHERE id = %s", ["refunded", order.pk.hex])
    assert Order.objects.get(pk=order.pk).status == "refunded"
