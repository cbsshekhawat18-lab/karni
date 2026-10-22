"""Raw-SQL helpers: every guarantee is proven at the database, bypassing the ORM."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from django.db import DataError, IntegrityError, connection, transaction

STAMP = "2026-01-01 00:00:00"


def quote(name: str) -> str:
    return str(connection.ops.quote_name(name))


def raw_insert(table: str, values: dict[str, Any]) -> None:
    """``INSERT INTO table (...) VALUES (...)`` through a bare cursor (no ORM, no validation)."""
    columns = ", ".join(quote(column) for column in values)
    marks = ", ".join(["%s"] * len(values))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {quote(table)} ({columns}) VALUES ({marks})", list(values.values())
        )


def raw_update(table: str, column: str, value: Any, row_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote('id')} = %s",
            [value, row_id],
        )


@contextmanager
def rejected() -> Iterator[None]:
    """The statement inside must be refused by the database.

    A CHECK, NOT NULL or unique violation is an IntegrityError; PostgreSQL
    refuses a value longer than the column (``"Germany"`` in a char(2)) with a
    DataError before any CHECK runs.
    """
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        yield


def new_id() -> str:
    return uuid.uuid4().hex


def product_row(**overrides: Any) -> dict[str, Any]:
    """A valid ``fieldsapp_product`` row; override one column to break one rule."""
    row: dict[str, Any] = {
        "id": new_id(),
        "created_at": STAMP,
        "updated_at": STAMP,
        "name": "Lamp",
        "description": "",
        "slug": f"lamp-{uuid.uuid4().hex[:8]}",
        "price": Decimal("10.00"),
        "currency": "EUR",
        "cost": Decimal("0"),
        "discount": Decimal("0"),
        "stock": 0,
        "made_in": "",
        "phone": "",
        "meta": "{}",
    }
    row.update(overrides)
    return row


def customer_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": new_id(),
        "created_at": STAMP,
        "updated_at": STAMP,
        "email": "someone@example.com",
        "name": "",
    }
    row.update(overrides)
    return row


def account_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": new_id(),
        "created_at": STAMP,
        "updated_at": STAMP,
        "email": "someone@example.com",
    }
    row.update(overrides)
    return row
