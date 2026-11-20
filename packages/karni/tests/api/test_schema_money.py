"""A MoneyField reaches the schema with its currency (``x-karni-money``, experimental)."""

from __future__ import annotations

from typing import Any

import pytest
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ComponentRegistry
from rest_framework import serializers

from karni.api.formats import MoneyDecimalField, money_of
from karni.api.serializers import build_serializer
from tests.fieldsapp.models import Product

pytestmark = pytest.mark.django_db


def _property(field: serializers.Field[Any, Any, Any, Any]) -> dict[str, Any]:
    from drf_spectacular.extensions import OpenApiSerializerFieldExtension

    extension = OpenApiSerializerFieldExtension.get_match(field)
    assert extension is not None
    auto = AutoSchema()
    auto.registry = ComponentRegistry()
    auto.method = "GET"
    return dict(extension.map_serializer_field(auto, "response"))


def test_a_money_field_names_its_currency_fixed_or_per_row() -> None:
    fields = build_serializer(Product)().fields
    price, cost = fields["price"], fields["cost"]
    assert isinstance(price, MoneyDecimalField) and isinstance(cost, MoneyDecimalField)
    assert price.money == {"currency": "EUR"}
    assert cost.money == {"currency_field": "currency"}
    assert _property(price)["x-karni-money"] == {"currency": "EUR"}
    assert _property(cost)["x-karni-money"] == {"currency_field": "currency"}
    assert money_of(Product._meta.get_field("name")) is None
