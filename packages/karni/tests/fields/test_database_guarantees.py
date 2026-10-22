"""Every typed-field guarantee, proven at the database with raw SQL (PostgreSQL and SQLite).

Each test writes through a bare cursor, so the ORM, the serializer and every
validator are out of the picture: if the database did not enforce the rule,
the row would be stored. A constraint that only holds through the serializer
does not count.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.fields.conftest import (
    account_row,
    customer_row,
    product_row,
    raw_insert,
    raw_update,
    rejected,
)

pytestmark = pytest.mark.django_db

PRODUCT = "fieldsapp_product"
CUSTOMER = "fieldsapp_customer"
ACCOUNT = "fieldsapp_account"
MEMBERSHIP = "fieldsapp_membership"


def test_a_valid_row_is_accepted() -> None:
    """The control: the helper rows pass every CHECK, so each rejection below is the rule's."""
    raw_insert(PRODUCT, product_row(made_in="DE", phone="+442079460958", discount=Decimal(15)))


# QuantityField: CHECK (stock >= 0)


def test_raw_insert_of_a_negative_quantity_is_rejected() -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(stock=-1))


def test_raw_update_to_a_negative_quantity_is_rejected() -> None:
    row = product_row(stock=3)
    raw_insert(PRODUCT, row)
    with rejected():
        raw_update(PRODUCT, "stock", -3, row["id"])


# PercentField: CHECK between the declared bounds


@pytest.mark.parametrize("value", [Decimal("100.01"), Decimal("-0.01"), Decimal("250")])
def test_raw_update_of_a_percent_out_of_bounds_is_rejected(value: Decimal) -> None:
    row = product_row(discount=Decimal("10"))
    raw_insert(PRODUCT, row)
    with rejected():
        raw_update(PRODUCT, "discount", value, row["id"])


def test_percent_bounds_are_inclusive() -> None:
    row = product_row()
    raw_insert(PRODUCT, row)
    raw_update(PRODUCT, "discount", Decimal("100"), row["id"])
    raw_update(PRODUCT, "discount", Decimal("0"), row["id"])


# MoneyField(min_value=0): CHECK (price >= 0)


def test_raw_insert_of_a_negative_bounded_amount_is_rejected() -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(price=Decimal("-0.01")))


# CountryField / CurrencyField: CHECK (col IN ISO list)


@pytest.mark.parametrize("value", ["XX", "de", "Germany", "UK", "EU"])
def test_raw_insert_of_a_country_outside_iso_3166_is_rejected(value: str) -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(made_in=value))


@pytest.mark.parametrize("value", ["EURO", "XYZ", "eur", "BTC", "HRK"])
def test_raw_insert_of_a_currency_outside_iso_4217_is_rejected(value: str) -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(currency=value))


def test_raw_update_to_a_non_iso_currency_is_rejected() -> None:
    row = product_row(currency="USD")
    raw_insert(PRODUCT, row)
    with rejected():
        raw_update(PRODUCT, "currency", "US$", row["id"])


# PhoneField: CHECK E.164


@pytest.mark.parametrize(
    "value", ["4155552671", "+0123456789", "+1 415 555 2671", "+1234567890123456", "+1-415", "+"]
)
def test_raw_insert_of_a_phone_outside_e164_is_rejected(value: str) -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(phone=value))


# EmailField(unique=True): unique on LOWER(email)


def test_raw_insert_of_alice_after_alice_differing_in_case_is_rejected() -> None:
    raw_insert(CUSTOMER, customer_row(email="alice@x.com"))
    with rejected():
        raw_insert(CUSTOMER, customer_row(email="Alice@x.com"))
    with rejected():
        raw_insert(CUSTOMER, customer_row(email="ALICE@X.COM"))


def test_case_insensitive_email_uniqueness_on_a_model_without_soft_delete() -> None:
    raw_insert(ACCOUNT, account_row(email="bob@x.com"))
    with rejected():
        raw_insert(ACCOUNT, account_row(email="Bob@X.com"))


# Soft delete: a deleted row's unique value is reusable; a live duplicate is not


def test_a_soft_deleted_rows_email_can_be_reused_but_not_twice() -> None:
    raw_insert(CUSTOMER, customer_row(email="carol@x.com", deleted_at="2026-01-02 00:00:00"))
    raw_insert(CUSTOMER, customer_row(email="Carol@x.com"))  # the deleted row does not block it
    with rejected():
        raw_insert(CUSTOMER, customer_row(email="carol@x.com"))  # a live duplicate does


def test_a_soft_deleted_rows_slug_can_be_reused_but_not_twice() -> None:
    raw_insert(PRODUCT, product_row(slug="desk-lamp", deleted_at="2026-01-02 00:00:00"))
    raw_insert(PRODUCT, product_row(slug="desk-lamp"))
    with rejected():
        raw_insert(PRODUCT, product_row(slug="desk-lamp"))


def test_two_deleted_rows_may_share_a_value() -> None:
    for _ in range(2):
        raw_insert(CUSTOMER, customer_row(email="dave@x.com", deleted_at="2026-01-02 00:00:00"))


def test_live_unique_constraint_over_two_columns() -> None:
    customer, product = customer_row(email="erin@x.com"), product_row()
    raw_insert(CUSTOMER, customer)
    raw_insert(PRODUCT, product)
    pair = {"customer_id": customer["id"], "product_id": product["id"]}
    stamps = {"created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00"}
    raw_insert(MEMBERSHIP, {"id": "a" * 32, **stamps, **pair, "deleted_at": "2026-01-02"})
    raw_insert(MEMBERSHIP, {"id": "b" * 32, **stamps, **pair})
    with rejected():
        raw_insert(MEMBERSHIP, {"id": "c" * 32, **stamps, **pair})


# NOT NULL is enforced by the database, not only blank=False


def test_raw_insert_without_a_required_amount_is_rejected() -> None:
    with rejected():
        raw_insert(PRODUCT, product_row(price=None))
