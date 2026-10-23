"""The field layer's system checks fail (or warn about) exactly the models they should."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core import checks
from django.db import connection, models
from django.test.utils import isolate_apps

from karni.fields import (
    JSONField,
    LiveUniqueConstraint,
    MoneyField,
    SearchField,
    SlugField,
)
from karni.fields import checks as field_checks
from karni.models import BaseModel, TimestampedModel, UUIDModel
from tests.fieldsapp import models as fieldsapp


def _configs(*model_classes: type[models.Model]) -> list[Any]:
    """A stand-in app config: the checks only ask it for its models."""
    return [SimpleNamespace(label="fieldsapp", get_models=lambda: list(model_classes))]


def _ids(messages: list[checks.CheckMessage]) -> list[str]:
    return [message.id for message in messages]


# E960: FloatField for money


@isolate_apps("tests.fieldsapp")
def test_a_float_named_like_money_fails_the_boot() -> None:
    class Invoice(models.Model):
        unit_price = models.FloatField()
        total_amount = models.FloatField()
        tax = models.FloatField()
        latitude = models.FloatField()  # not money
        weight = models.FloatField()

        class Meta:
            app_label = "fieldsapp"

    messages = field_checks.check_money_floats(_configs(Invoice))
    assert _ids(messages) == ["karni.E960"] * 3
    assert all(message.level == checks.ERROR for message in messages)
    flagged = " ".join(message.msg for message in messages)
    assert "Invoice.unit_price" in flagged and "Invoice.tax" in flagged
    assert "latitude" not in flagged and "weight" not in flagged
    assert 'MoneyField(currency="EUR")' in str(messages[0].hint)


@isolate_apps("tests.fieldsapp")
def test_not_money_is_the_reasoned_escape_hatch() -> None:
    class Game(models.Model):
        total_score = models.FloatField()

        class Meta:
            app_label = "fieldsapp"

        class Karni:
            not_money = {"total_score": "a game score, not currency"}

    class Sloppy(models.Model):
        balance = models.FloatField()

        class Meta:
            app_label = "fieldsapp"

        class Karni:
            not_money = ["balance"]

    assert field_checks.check_money_floats(_configs(Game)) == []
    assert "karni.E970" in _ids(field_checks.check_money_floats(_configs(Sloppy)))


# W965: CASCADE on financial or audited models


@isolate_apps("tests.fieldsapp")
def test_cascade_on_a_financial_model_is_flagged() -> None:
    class Order(models.Model):
        class Meta:
            app_label = "fieldsapp"

    class Payment(models.Model):  # financial by name and by its MoneyField
        order = models.ForeignKey(Order, on_delete=models.CASCADE)
        amount = MoneyField(currency="EUR")

        class Meta:
            app_label = "fieldsapp"

    class Note(models.Model):  # neither financial nor audited: CASCADE is fine
        order = models.ForeignKey(Order, on_delete=models.CASCADE)

        class Meta:
            app_label = "fieldsapp"

    messages = field_checks.check_cascades(_configs(Order, Payment, Note))
    assert _ids(messages) == ["karni.W965"]
    assert "Payment.order" in messages[0].msg and "financial" in messages[0].msg
    assert "on_delete=models.PROTECT" in str(messages[0].hint)


@isolate_apps("tests.fieldsapp")
def test_cascade_on_an_audited_model_is_flagged_unless_declared() -> None:
    class Ledger(models.Model):
        class Meta:
            app_label = "fieldsapp"

    class Entry(models.Model):
        ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE)
        other = models.ForeignKey(Ledger, on_delete=models.PROTECT, related_name="+")

        class Meta:
            app_label = "fieldsapp"

        class Karni:
            audit = True

    class Line(models.Model):
        ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE)
        price = models.DecimalField(max_digits=10, decimal_places=2)  # financial by name

        class Meta:
            app_label = "fieldsapp"

        class Karni:
            cascade = {"ledger": "a line is part of its ledger and goes with it"}

    messages = field_checks.check_cascades(_configs(Ledger, Entry, Line))
    assert _ids(messages) == ["karni.W965"]
    assert "Entry.ledger" in messages[0].msg and "history" in messages[0].msg


# E961 / E963 / E968: declarations the database cannot honour


@isolate_apps("tests.fieldsapp")
def test_declarations_that_cannot_work_are_errors() -> None:
    class Broken(models.Model):
        total = MoneyField(currency_field="currency")  # no such field
        slug = SlugField(populate_from="title")  # no such field
        search = SearchField(sources=["name", "body"])

        class Meta:
            app_label = "fieldsapp"
            constraints = [LiveUniqueConstraint(fields=["slug"])]  # no soft delete

    messages = field_checks.check_field_declarations(_configs(Broken))
    assert sorted(_ids(messages)) == sorted(
        ["karni.E961", "karni.E963", "karni.E963", "karni.E968"]
    )


def test_the_fieldsapp_models_are_clean() -> None:
    configs = _configs(*[m for m in vars(fieldsapp).values() if _is_model(m)])
    assert field_checks.check_money_floats(configs) == []
    assert field_checks.check_field_declarations(configs) == []
    assert field_checks.check_cascades(configs) == []


def _is_model(value: Any) -> bool:
    return (
        isinstance(value, type)
        and issubclass(value, models.Model)
        and not getattr(value, "_meta").abstract  # noqa: B009 - mypy sees a bare type
        and getattr(value, "_meta").app_label == "fieldsapp"  # noqa: B009
    )


# E964 / W964: non-PostgreSQL backends


def _fake(vendor: str, partial: bool = True) -> Any:
    return SimpleNamespace(
        vendor=vendor, alias="default", features=SimpleNamespace(supports_partial_indexes=partial)
    )


def test_postgres_only_fields_warn_on_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(field_checks, "_model_databases", lambda model: [_fake("sqlite")])
    messages = field_checks.check_backends(_configs(fieldsapp.Product))
    by_text = {message.msg.split(" (")[0]: message.id for message in messages}
    assert by_text == {
        "Product.price": "karni.W964",  # exact NUMERIC
        "Product.cost": "karni.W964",
        "Product.meta": "karni.W964",  # GIN for queried=True
        "Product.search": "karni.W964",  # tsvector + GIN
    }
    assert all(message.level == checks.WARNING for message in messages)
    assert "DATABASES['default'] (sqlite)" in messages[0].msg


def test_the_same_models_are_silent_on_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(field_checks, "_model_databases", lambda model: [_fake("postgresql")])
    configs = _configs(fieldsapp.Product, fieldsapp.Customer, fieldsapp.Membership)
    assert field_checks.check_backends(configs) == []


def test_no_partial_indexes_means_no_live_uniqueness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        field_checks, "_model_databases", lambda model: [_fake("mysql", partial=False)]
    )
    messages = field_checks.check_backends(_configs(fieldsapp.Membership))
    assert _ids(messages) == ["karni.W964"]
    assert "not enforced by the database" in messages[0].msg


@isolate_apps("tests.fieldsapp")
def test_an_array_field_is_an_error_off_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("psycopg", reason="karni.fields.ArrayField needs a PostgreSQL driver")
    from karni.fields import ArrayField

    class Tagged(models.Model):
        tags = ArrayField(models.CharField(max_length=20))

        class Meta:
            app_label = "fieldsapp"

    monkeypatch.setattr(field_checks, "_model_databases", lambda model: [_fake("sqlite")])
    messages = field_checks.check_backends(_configs(Tagged))
    assert _ids(messages) == ["karni.E964"]
    assert messages[0].level == checks.ERROR
    assert "Tagged.tags (ArrayField) cannot work" in messages[0].msg
    assert "JSONField" in messages[0].msg + str(messages[0].hint)
    monkeypatch.setattr(field_checks, "_model_databases", lambda model: [_fake("postgresql")])
    assert field_checks.check_backends(_configs(Tagged)) == []


def test_the_real_check_matches_the_configured_backend() -> None:
    """Run against DATABASES as configured: SQLite warns, PostgreSQL is silent."""
    messages = field_checks.check_backends(_configs(fieldsapp.Product))
    if connection.vendor == "postgresql":
        assert messages == []
    else:
        assert set(_ids(messages)) == {"karni.W964"}


# W967: declared usage without an index


@isolate_apps("tests.fieldsapp")
def test_unindexed_search_filter_and_order_columns_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    class Ticket(BaseModel):
        code = models.CharField(max_length=20, db_index=True)
        status = models.CharField(max_length=20)
        seats = models.IntegerField()
        notes = models.TextField()
        data = JSONField(default=dict)

        class Meta(BaseModel.Meta):
            app_label = "fieldsapp"

    class TicketViewSet:
        model = Ticket
        search_fields = ["notes"]
        filterset_fields = ["status", "code", "created_by"]
        ordering_fields = ["seats", "created_at"]

    router = SimpleNamespace(registry=[("tickets", TicketViewSet, "t")])
    monkeypatch.setattr("karni.api.routers.resolve_router", lambda: router)
    messages = field_checks.check_usage_indexes()
    texts = sorted(message.msg for message in messages)
    assert _ids(messages) == ["karni.W967"] * 3
    assert texts[0].startswith("TicketViewSet.filterset_fields filters by Ticket.status")
    assert texts[1].startswith("TicketViewSet.ordering_fields orders by Ticket.seats")
    assert texts[2].startswith("TicketViewSet.search_fields searches Ticket.notes")
    hints = " ".join(str(message.hint) for message in messages)
    assert 'models.Index(fields=["status"]' in hints and "SearchField" in hints
    assert 'SILENCED_SYSTEM_CHECKS = ["karni.W967"]' in hints


@isolate_apps("tests.fieldsapp")
def test_covered_columns_do_not_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    class Song(UUIDModel, TimestampedModel):
        title = models.CharField(max_length=100)
        genre = models.CharField(max_length=20)
        search = SearchField(sources=["title"])

        class Meta:
            app_label = "fieldsapp"
            indexes = [models.Index(fields=["genre", "title"], name="song_genre_idx")]

    class SongViewSet:
        model = Song
        search_fields = ["search"]
        filterset_fields = {"genre": ["exact"]}
        ordering = ["-created_at"]

    router = SimpleNamespace(registry=[("songs", SongViewSet, "s")])
    monkeypatch.setattr("karni.api.routers.resolve_router", lambda: router)
    assert field_checks.check_usage_indexes() == []
