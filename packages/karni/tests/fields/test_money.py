"""MoneyField: Decimal only, a declared rounding rule, and 10,000 operations that lose nothing."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest
from django.db import connection, models
from django.db.models import Sum
from django.test.utils import isolate_apps

from karni.exceptions import KarniImproperlyConfigured, KarniTypeError
from karni.fields import MoneyField, allocate, quantize, split
from tests.fieldsapp.models import Product

N = 10_000


def _amount(i: int) -> Decimal:
    """Deterministic amounts with five decimals, so every save has to round."""
    return Decimal((i * 7919 + 13) % 10_000_000) / Decimal(100_000)


# assignment and lookups


@pytest.mark.parametrize("value", [9.99, 0.1, True])
def test_assigning_a_float_is_refused(value: object) -> None:
    product = Product(name="Lamp")
    with pytest.raises(KarniTypeError, match="E962") as caught:
        setattr(product, "price", value)  # noqa: B010 - mypy sees the field class
    assert "Decimal" in str(caught.value) and "Product.price" in str(caught.value)


def test_constructing_with_a_float_is_refused() -> None:
    with pytest.raises(KarniTypeError, match="E962"):
        Product(name="Lamp", price=19.99)


@pytest.mark.django_db
def test_a_float_in_a_lookup_or_bulk_update_is_refused() -> None:
    with pytest.raises(KarniTypeError, match="E962"):
        list(Product.objects.filter(price=9.99))
    with pytest.raises(KarniTypeError, match="E962"):
        Product.objects.update(price=9.99)


def test_ints_and_decimals_are_exact() -> None:
    product = Product(name="Lamp", price=12)
    assert product.price == Decimal(12) and isinstance(product.price, Decimal)
    setattr(product, "price", Decimal("0.10"))  # noqa: B010
    assert product.price == Decimal("0.10")


@pytest.mark.django_db
def test_saving_rounds_with_the_declared_rule() -> None:
    product = Product.objects.create(name="Lamp", slug="lamp", price=Decimal("1.00005"))
    assert product.price == Decimal("1.0000")  # half-even: the 0 before the 5 stays
    product.price = Decimal("1.00015")
    product.save()
    product.refresh_from_db()
    assert product.price == Decimal("1.0002")


def test_rounding_rule_is_declared_per_field() -> None:
    @isolate_apps("tests.fieldsapp")
    def build() -> MoneyField:
        class HalfUp(models.Model):
            amount = MoneyField(currency="EUR", rounding=ROUND_HALF_UP)

            class Meta:
                app_label = "fieldsapp"

        return HalfUp._meta.get_field("amount")

    field = build()
    assert field.quantize_value(Decimal("1.00005")) == Decimal("1.0001")
    assert field.deconstruct()[3]["rounding"] == ROUND_HALF_UP


def test_a_currency_is_required_and_must_be_iso() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E961"):
        MoneyField()
    with pytest.raises(KarniImproperlyConfigured, match="E961"):
        MoneyField(currency="EUR", currency_field="currency")
    with pytest.raises(KarniImproperlyConfigured, match="E961"):
        MoneyField(currency="EURO")
    assert MoneyField(currency="usd").currency == "USD"


def test_currency_for_reads_the_declaration() -> None:
    fixed = Product._meta.get_field("price")
    per_row = Product._meta.get_field("cost")
    product = Product(name="Lamp", currency="JPY")
    assert fixed.currency_for(product) == "EUR"
    assert per_row.currency_for(product) == "JPY"


# arithmetic helpers


def test_split_and_allocate_never_lose_a_cent() -> None:
    assert split(Decimal("100"), 3) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert allocate(Decimal("10"), [1, 2, 3]) == [Decimal("1.67"), Decimal("3.33"), Decimal("5.00")]
    assert sum(allocate(Decimal("-0.05"), [1, 1])) == Decimal("-0.05")
    assert quantize(Decimal("2.675"), 2) == Decimal("2.68")  # half-even, exact (float: 2.67)
    assert quantize("0.125", 2, ROUND_HALF_EVEN) == Decimal("0.12")
    with pytest.raises(KarniTypeError, match="E962"):
        split(0.3, 3)


def test_ten_thousand_operations_in_python_are_exact() -> None:
    """Sums, splits and rounding over 10,000 amounts, against exact Decimal expectations."""
    amounts = [_amount(i) for i in range(N)]
    rounded = [quantize(a, 4) for a in amounts]
    assert rounded == [a.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN) for a in amounts]
    total = sum(rounded, Decimal(0))
    for amount in rounded:
        parts = split(amount, 3, places=4)
        assert sum(parts) == amount
        assert max(parts) - min(parts) <= Decimal("0.0001")
        assert sum(allocate(amount, [1, 2, 7], places=4)) == amount
    shares = allocate(total, [1] * 7, places=4)
    assert sum(shares) == total
    # The control: the same running total in floats drifts (a ledger adds one at a time;
    # Python 3.12's sum() compensates, a database or a loop does not).
    running = 0.0
    for _ in range(N):
        running += 0.1
    assert running != 1000
    assert sum(Decimal("0.1") for _ in range(N)) == Decimal(1000)


@pytest.mark.django_db
def test_ten_thousand_amounts_round_trip_exactly() -> None:
    """Every stored amount is the declared rounding of what was assigned, read back exactly."""
    Product.objects.bulk_create(
        Product(name=f"Item {i}", slug=f"item-{i}", price=_amount(i)) for i in range(N)
    )
    expected = {
        f"item-{i}": _amount(i).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
        for i in range(N)
    }
    stored = dict(Product.objects.values_list("slug", "price"))
    assert stored == expected


@pytest.mark.django_db
@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="SQLite stores NUMERIC as a binary float and its SUM() is floating point: exact "
    "money aggregates are a PostgreSQL guarantee (karni.W964 says so on SQLite).",
)
def test_database_sum_of_ten_thousand_amounts_is_exact() -> None:
    Product.objects.bulk_create(
        Product(name=f"Item {i}", slug=f"item-{i}", price=_amount(i)) for i in range(N)
    )
    exact = sum(
        (_amount(i).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN) for i in range(N)),
        Decimal(0),
    )
    assert Product.objects.aggregate(total=Sum("price"))["total"] == exact
