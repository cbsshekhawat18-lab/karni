"""The shop with the family's contracts: its connection, on and off."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.apps import apps
from karni import preferences

from shop import services
from shop.models import Product, Shipment
from shop.tests.conftest import cart_with, pay, place

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


def _parcel(make_product: MakeProduct) -> Shipment:
    order = pay(place(cart_with((make_product(), 1))))
    return Shipment.objects.get(order=order)


def test_a_sent_parcel_goes_on_its_order_timeline_while_the_connection_is_on(
    make_product: MakeProduct,
) -> None:
    if not apps.is_installed("karni.timeline"):  # alone: the connection stays off
        assert not preferences.active("shop.parcel_timeline")
        return
    from karni.timeline.models import TimelineEntry

    parcel = _parcel(make_product)
    services.ship(parcel, "PP123", "Parcel Post")
    entry = TimelineEntry.objects.get(kind="shop.shipment.shipped")
    assert entry.title == f"Parcel shipped: order {parcel.order.number}"
    assert entry.body == "Parcel Post PP123"
    services.deliver(parcel)
    assert TimelineEntry.objects.filter(kind="shop.shipment.delivered").count() == 1
    other = _parcel(make_product)
    with preferences.override(connections={"shop.parcel_timeline": False}):
        services.ship(other, "PP456")
    assert TimelineEntry.objects.filter(kind="shop.shipment.shipped").count() == 1
