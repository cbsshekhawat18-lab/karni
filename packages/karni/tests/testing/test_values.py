"""karni.testing.values: realistic values by name, then type — shared by factories and seeds."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone
from factory.random import reseed_random

from karni.testing.factories import FactoryBuilder, auto_factory
from karni.testing.values import (
    MISSING,
    NAME_RULES,
    SAFE_DOMAINS,
    NameRule,
    ValueContext,
    ValueInference,
    unique_field_names,
)

NOW = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def values() -> ValueInference:
    reseed_random(3)
    return ValueInference(now=NOW)


def _field(model: type[models.Model], name: str) -> Any:
    return model._meta.get_field(name)


@isolate_apps("tests.perfapp")
def test_names_decide_before_types(values: ValueInference) -> None:
    class Gig(models.Model):
        title = models.CharField(max_length=40)
        email = models.CharField(max_length=80)
        contact = models.EmailField()
        price = models.DecimalField(max_digits=6, decimal_places=2)
        starts_at = models.DateTimeField()
        birth_date = models.DateField()
        city = models.CharField(max_length=60)
        phone = models.CharField(max_length=12)
        website = models.URLField()
        latitude = models.FloatField()
        rating = models.PositiveSmallIntegerField()
        capacity = models.PositiveIntegerField()
        is_active = models.BooleanField()
        color = models.CharField(max_length=7)
        position = models.PositiveIntegerField()

        class Meta:
            app_label = "perfapp"

    def value(name: str, n: int = 0) -> Any:
        return values.value(Gig, _field(Gig, name), n)

    assert value("email").split("@")[1] in SAFE_DOMAINS  # a CharField called email
    assert value("contact").split("@")[1] in SAFE_DOMAINS  # an EmailField by type
    price = value("price")
    assert isinstance(price, Decimal) and Decimal(5) <= price <= Decimal(500)
    assert price == price.quantize(Decimal("0.01"))
    assert NOW < value("starts_at") <= NOW + dt.timedelta(days=61)
    assert value("starts_at").second == 0
    age = (NOW.date() - value("birth_date")).days / 365
    assert 17.9 < age < 80.1
    assert value("city") and len(value("phone")) <= 12
    assert re.fullmatch(r"https://example\.(com|org|net)/[a-z0-9-]+", value("website"))
    assert -60 <= value("latitude") <= 70
    assert 1 <= value("rating") <= 5 and 10 <= value("capacity") <= 500
    assert isinstance(value("is_active"), bool)
    assert re.fullmatch(r"#[0-9a-f]{6}", value("color"))
    assert [value("position", n) for n in range(3)] == [0, 1, 2]
    assert len(value("title")) <= 40


@isolate_apps("tests.perfapp")
def test_unique_values_embed_the_sequence_within_max_length(values: ValueInference) -> None:
    class Code(models.Model):
        label = models.CharField(max_length=6, unique=True)
        email = models.EmailField(unique=True)
        slug = models.SlugField(unique=True)

        class Meta:
            app_label = "perfapp"

    label = _field(Code, "label")
    produced = {values.value(Code, label, n, unique=True) for n in range(30)}
    assert len(produced) == 30 and all(len(v) <= 6 for v in produced)
    emails = {values.value(Code, _field(Code, "email"), n, unique=True) for n in range(30)}
    assert len(emails) == 30
    assert values.value(Code, _field(Code, "slug"), 4, unique=True).endswith("-4")


@isolate_apps("tests.perfapp")
def test_dependent_values_follow_the_row() -> None:
    class Session(models.Model):
        first_name = models.CharField(max_length=40)
        last_name = models.CharField(max_length=40)
        email = models.EmailField()
        title = models.CharField(max_length=80)
        slug = models.SlugField(max_length=80)
        starts_at = models.DateTimeField()
        ends_at = models.DateTimeField()

        class Meta:
            app_label = "perfapp"

    reseed_random(5)
    row = auto_factory(Session, builder=FactoryBuilder()).build()
    assert row.email.startswith(f"{row.first_name}.{row.last_name}".lower().replace("'", ""))
    assert row.slug.startswith(row.title.lower().split()[0].strip(".,"))
    assert row.starts_at < row.ends_at <= row.starts_at + dt.timedelta(hours=4)


@isolate_apps("tests.perfapp")
def test_model_names_shape_the_name_field(values: ValueInference) -> None:
    class Venue(models.Model):
        name = models.CharField(max_length=80)

        class Meta:
            app_label = "perfapp"

    class EventCategory(models.Model):
        name = models.CharField(max_length=80)

        class Meta:
            app_label = "perfapp"

    venue = values.value(Venue, _field(Venue, "name"))
    assert venue.split()[-1] in {
        "Hall", "Center", "Arena", "Theatre", "Pavilion", "Studio", "Gardens", "Auditorium",
    }  # fmt: skip
    assert " " not in values.value(EventCategory, _field(EventCategory, "name"))


@isolate_apps("tests.perfapp")
def test_validators_and_types_bound_numbers(values: ValueInference) -> None:
    class Bounded(models.Model):
        stars = models.IntegerField(validators=[MinValueValidator(3), MaxValueValidator(4)])
        tiny = models.DecimalField(max_digits=3, decimal_places=2)
        amount = models.PositiveSmallIntegerField()

        class Meta:
            app_label = "perfapp"

    for n in range(20):
        assert 3 <= values.value(Bounded, _field(Bounded, "stars"), n) <= 4
        assert Decimal(0) <= values.value(Bounded, _field(Bounded, "tiny"), n) <= Decimal("9.99")
        assert 5 <= values.value(Bounded, _field(Bounded, "amount"), n) <= 500


def test_reseeding_reproduces_every_value() -> None:
    from tests.perfapp.models import Specimen

    def sample() -> list[Any]:
        reseed_random(11)
        inference = ValueInference(now=NOW)
        return [
            inference.value(Specimen, field, 1)
            for field in Specimen._meta.concrete_fields
            if not field.is_relation and inference.generator(Specimen, field) is not None
        ]

    assert sample() == sample()


def test_the_anchor_defaults_to_now_and_can_be_a_callable() -> None:
    assert abs(ValueInference().now() - timezone.now()) < dt.timedelta(seconds=5)
    assert ValueInference(now=lambda: NOW).now() == NOW


def test_custom_rules_and_type_methods_override() -> None:
    from tests.perfapp.models import Publisher, Specimen

    class House(ValueInference):
        rules = (
            NameRule("house", ("name",), (models.CharField,), lambda ctx: "House"),
            *NAME_RULES,
        )

        def datetime(self, ctx: ValueContext) -> dt.datetime:
            return ctx.now

    house = House(now=NOW)
    assert house.value(Publisher, _field(Publisher, "name")) == "House"
    assert house.value(Specimen, _field(Specimen, "moment")) == NOW  # no name rule: the type
    assert house.value(Specimen, _field(Specimen, "body")) != NOW  # "body": a name rule


def test_unknown_types_and_unique_fields() -> None:
    from tests.perfapp.models import Chapter, Specimen

    assert ValueInference().value(Specimen, models.Field(name="odd")) is MISSING
    assert unique_field_names(Chapter) == {"novel", "number"}
    assert {"label", "email"} <= unique_field_names(Specimen)
