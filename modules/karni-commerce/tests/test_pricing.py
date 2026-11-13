"""Options, coupons, shipping zones and tax: for a gadget (shipped) and a seat (not shipped)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from karni_commerce import services
from karni_commerce.models import (
    Cart,
    Coupon,
    CouponUse,
    Order,
    ShippingMethod,
    ShippingZone,
    TaxRate,
)
from tests.conftest import ADDRESS, cart_with, pay, place, refund_webhook
from tests.testapp.models import Gadget, Workshop

pytestmark = pytest.mark.django_db

US = {**ADDRESS, "country": "US", "region": "NY", "postcode": "10001"}


def zones() -> dict[str, Any]:
    """France: flat 5.00, free above 50, pickup. Some of the EU: flat 12. No zone for the US."""
    france = ShippingZone.objects.create(name="France", countries="FR", position=1)
    europe = ShippingZone.objects.create(name="Europe", countries="DE, ES, IT", position=2)
    return {
        "flat": ShippingMethod.objects.create(
            zone=france, name="Standard", kind="flat", cost=Decimal("5.00"), position=1
        ),
        "free": ShippingMethod.objects.create(
            zone=france, name="Free", kind="free", free_above=Decimal("50.00"), position=2
        ),
        "pickup": ShippingMethod.objects.create(
            zone=france, name="Pickup in Lyon", kind="pickup", position=3, taxable=False
        ),
        "europe": ShippingMethod.objects.create(
            zone=europe, name="Europe", kind="flat", cost=Decimal("12.00")
        ),
    }


# -- options -------------------------------------------------------------------------------


def test_two_colours_of_one_item_are_two_lines_and_the_order_keeps_them_in_words(
    make_gadget: Callable[..., Gadget],
) -> None:
    lamp = make_gadget(stock=9)
    cart = Cart.objects.create()
    services.set_line(cart, "gadget", str(lamp.pk), 1, {"colour": "red"})
    services.set_line(cart, "gadget", str(lamp.pk), 2, {"colour": "blue"})
    services.set_line(cart, "gadget", str(lamp.pk), 1, {"colour": "blue"}, add=True)
    assert sorted((line.options["colour"], line.quantity) for line in cart.lines.all()) == [
        ("blue", 3),
        ("red", 1),
    ]
    services.set_line(cart, "gadget", str(lamp.pk), 0, {"colour": "red"})
    [line] = cart.lines.all()
    order = place(cart)
    [ordered] = order.lines.all()
    assert ordered.name == "Lamp, blue" and ordered.details == [
        {"label": "Colour", "value": "blue"}
    ]
    assert line.variant and ordered.quantity == 3


# -- coupons -------------------------------------------------------------------------------


def test_a_percent_coupon_takes_off_each_line_it_applies_to(
    make_gadget: Callable[..., Gadget], make_workshop: Callable[..., Workshop]
) -> None:
    lamp = make_gadget(price=Decimal("20.00"), sku="LMP-1")
    seat = make_workshop(price=Decimal("45.00"))
    Coupon.objects.create(code="gadgets10", kind="percent", amount=Decimal("10"), kinds="gadget")
    cart = cart_with(("gadget", lamp, 2), ("seat", seat, 1))
    assert services.apply_coupon(cart, "GADGETS10") is not None
    order = place(cart)
    assert order.coupon_code == "GADGETS10"
    assert (order.subtotal, order.discount_total, order.total) == (
        Decimal("85.00"),
        Decimal("4.00"),
        Decimal("81.00"),
    )
    lines = {line.kind: line for line in order.lines.all()}
    assert lines["gadget"].discount == Decimal("4.00") and lines["seat"].discount == 0
    assert CouponUse.objects.get().amount == Decimal("4.00")


def test_a_fixed_coupon_is_shared_by_price_and_never_more_than_the_items(
    make_gadget: Callable[..., Gadget],
) -> None:
    lamp = make_gadget(price=Decimal("30.00"), sku="LMP-1")
    vase = make_gadget(name="Vase", price=Decimal("10.00"), sku="VAS-1")
    Coupon.objects.create(code="TENOFF", kind="fixed", amount=Decimal("10"))
    cart = cart_with(("gadget", lamp, 1), ("gadget", vase, 1))
    services.apply_coupon(cart, "tenoff")
    order = place(cart)
    discounts = sorted(line.discount for line in order.lines.all())
    assert discounts == [Decimal("2.50"), Decimal("7.50")] and order.total == Decimal("30.00")
    Coupon.objects.create(code="BIG", kind="fixed", amount=Decimal("500"))
    cart = cart_with(("gadget", vase, 1))
    services.apply_coupon(cart, "big")
    free = place(cart)
    assert free.total == 0 and free.discount_total == Decimal("10.00")
    services.open_payment(free)
    free.refresh_from_db()
    assert free.status == "paid"  # nothing to pay: settled at once


def test_coupon_rules_minimum_dates_limits_and_what_it_applies_to(
    make_gadget: Callable[..., Gadget], make_workshop: Callable[..., Workshop]
) -> None:
    lamp = make_gadget(price=Decimal("20.00"), sku="LMP-1", stock=20)
    seat = make_workshop()
    now = timezone.now()

    def refused(code: str, *lines: tuple[str, Any, int], email: str = "") -> str:
        with pytest.raises(ValidationError) as caught:
            services.apply_coupon(cart_with(*lines), code, email=email)
        return str(caught.value.detail["code"][0])  # type: ignore[index]

    Coupon.objects.create(code="MIN50", amount=Decimal("5"), minimum_spend=Decimal("50"))
    assert "Spend at least 50.00" in refused("MIN50", ("gadget", lamp, 1))
    Coupon.objects.create(code="LATER", amount=Decimal("5"), starts_at=now + timedelta(days=1))
    assert refused("LATER", ("gadget", lamp, 1)) == "This coupon is not valid yet."
    Coupon.objects.create(code="OLD", amount=Decimal("5"), ends_at=now - timedelta(days=1))
    assert refused("OLD", ("gadget", lamp, 1)) == "This coupon has expired."
    Coupon.objects.create(code="SEATS", amount=Decimal("5"), kinds="seat")
    assert "does not apply" in refused("SEATS", ("gadget", lamp, 1))
    assert services.apply_coupon(cart_with(("seat", seat, 1)), "SEATS") is not None
    Coupon.objects.create(code="SHELF", amount=Decimal("5"), limits={"shelves": ["VAS"]})
    assert "does not apply" in refused("SHELF", ("gadget", lamp, 1))
    Coupon.objects.create(
        code="LAMP", amount=Decimal("5"), items=[{"key": f"gadget:{lamp.pk}", "name": "Lamp"}]
    )
    assert services.apply_coupon(cart_with(("gadget", lamp, 1)), "LAMP") is not None
    assert refused("NOPE", ("gadget", lamp, 1)) == "No coupon has that code."

    Coupon.objects.create(code="ONCE", amount=Decimal("5"), usage_limit=1)
    cart = cart_with(("gadget", lamp, 1))
    services.apply_coupon(cart, "ONCE")
    first = place(cart, email="a@example.com")
    assert refused("ONCE", ("gadget", lamp, 1)) == "This coupon has been used up."
    services.cancel(first)  # a cancelled order gives its use back
    assert services.apply_coupon(cart_with(("gadget", lamp, 1)), "ONCE") is not None

    Coupon.objects.create(code="EACH", amount=Decimal("5"), usage_limit_per_person=1)
    cart = cart_with(("gadget", lamp, 1))
    services.apply_coupon(cart, "EACH")
    place(cart, email="b@example.com")
    assert refused("EACH", ("gadget", lamp, 1), email="B@example.com").startswith("You have used")
    cart = cart_with(("gadget", lamp, 1))
    services.apply_coupon(cart, "EACH")  # no email yet: checked again at checkout
    with pytest.raises(ValidationError):
        place(cart, email="b@example.com")
    assert place(cart, email="c@example.com").coupon_code == "EACH"


# -- shipping ------------------------------------------------------------------------------


def test_checkout_offers_the_methods_of_the_zone_and_stores_the_one_chosen(
    make_gadget: Callable[..., Gadget],
) -> None:
    methods = zones()
    lamp = make_gadget(price=Decimal("20.00"), stock=10)
    cart = cart_with(("gadget", lamp, 1))
    quoted = services.quote_cart(cart, address=ADDRESS)
    assert [(m.name, m.cost) for m in quoted.methods] == [
        ("Standard", Decimal("5.00")),
        ("Pickup in Lyon", Decimal("0.00")),
    ]
    order = services.checkout(
        cart,
        email="g@example.com",
        billing=ADDRESS,
        shipping=ADDRESS,
        method=str(methods["pickup"].pk),
    )
    assert (order.shipping_method, order.shipping_total, order.total) == (
        "Pickup in Lyon",
        Decimal("0.00"),
        Decimal("20.00"),
    )
    big = cart_with(("gadget", lamp, 3))
    names = [m.name for m in services.quote_cart(big, address=ADDRESS).methods]
    assert names == ["Standard", "Free", "Pickup in Lyon"]
    assert services.quote_cart(big, address=ADDRESS).methods[0].cost == Decimal("5.00")
    order = services.checkout(big, email="g@example.com", billing=ADDRESS)
    assert order.shipping_method == "Standard" and order.total == Decimal("65.00")
    germany = {**ADDRESS, "country": "DE"}
    assert services.quote_cart(cart_with(("gadget", lamp, 1)), address=germany).shipping == 12
    with pytest.raises(ValidationError) as caught:
        services.checkout(cart_with(("gadget", lamp, 1)), email="g@example.com", billing=US)
    assert "We do not send orders to US" in str(caught.value.detail)
    with pytest.raises(ValidationError):
        services.checkout(
            cart_with(("gadget", lamp, 1)),
            email="g@example.com",
            billing=ADDRESS,
            method=str(methods["europe"].pk),
        )


def test_a_free_shipping_coupon_and_an_order_with_nothing_to_send(
    make_gadget: Callable[..., Gadget], make_workshop: Callable[..., Workshop]
) -> None:
    zones()
    lamp = make_gadget(price=Decimal("20.00"))
    Coupon.objects.create(code="SHIPFREE", kind="free_shipping")
    cart = cart_with(("gadget", lamp, 1))
    services.apply_coupon(cart, "shipfree")
    order = services.checkout(cart, email="g@example.com", billing=ADDRESS)
    assert order.shipping_total == 0 and order.total == Decimal("20.00")
    seat = services.checkout(
        cart_with(("seat", make_workshop(), 1)), email="g@example.com", billing=US
    )
    assert seat.shipping_method == "" and seat.total == Decimal("45.00")


# -- tax -----------------------------------------------------------------------------------


def test_tax_on_top_of_the_prices_with_its_lines_on_the_order(
    make_gadget: Callable[..., Gadget], make_workshop: Callable[..., Workshop]
) -> None:
    zones()
    TaxRate.objects.create(name="TVA", country="FR", rate=Decimal("20"))
    TaxRate.objects.create(
        name="TVA reduced", country="FR", rate=Decimal("5.5"), tax_class="reduced"
    )
    TaxRate.objects.create(name="Tax", rate=Decimal("10"))  # anywhere else
    lamp = make_gadget(price=Decimal("20.00"))
    order = services.checkout(
        cart_with(("gadget", lamp, 2)), email="g@example.com", billing=ADDRESS
    )
    # items 40.00 + 20% = 8.00, shipping 5.00 + 20% = 1.00
    assert (order.tax_total, order.total) == (Decimal("9.00"), Decimal("54.00"))
    assert order.tax_lines == [{"name": "TVA", "rate": "20.0000", "amount": "9.00"}]
    [line] = order.lines.all()
    assert (line.tax_rate, line.tax, line.total) == (
        Decimal("20"),
        Decimal("8.00"),
        Decimal("48.00"),
    )
    seat = services.checkout(
        cart_with(("seat", make_workshop(), 1)), email="g@example.com", billing=US
    )
    assert seat.tax_lines == [{"name": "Tax", "rate": "10.0000", "amount": "4.50"}]


@override_settings(KARNI_COMMERCE_PRICES_INCLUDE_TAX=True)
def test_prices_with_their_tax_in_them_and_a_refund_by_line(
    make_gadget: Callable[..., Gadget],
) -> None:
    TaxRate.objects.create(name="VAT", country="FR", rate=Decimal("20"))
    Coupon.objects.create(code="HALF", kind="percent", amount=Decimal("50"))
    lamp = make_gadget(price=Decimal("24.00"), stock=5)
    cart = cart_with(("gadget", lamp, 2))
    services.apply_coupon(cart, "half")
    order = place(cart)
    # 48.00 less 24.00 = 24.00, of which 4.00 is tax
    assert (order.total, order.tax_total, order.prices_include_tax) == (
        Decimal("24.00"),
        Decimal("4.00"),
        True,
    )
    pay(order)
    [line] = order.lines.all()
    services.refund(order, lines={str(line.pk): 1})
    refund_webhook(order)
    order.refresh_from_db()
    assert order.amount_refunded == Decimal("12.00") and order.status == "part_refunded"


# -- the API -------------------------------------------------------------------------------


def test_the_cart_api_applies_a_coupon_and_quotes_an_address(
    api: APIClient, make_gadget: Callable[..., Gadget]
) -> None:
    zones()
    TaxRate.objects.create(name="TVA", country="FR", rate=Decimal("20"))
    Coupon.objects.create(code="TEN", kind="percent", amount=Decimal("10"), description="10% off")
    lamp = make_gadget(price=Decimal("20.00"))
    answer = api.post(
        "/api/carts/current/lines/",
        {"kind": "gadget", "item": str(lamp.pk), "quantity": 1, "options": {"colour": "red"}},
        format="json",
    )
    token = answer.data["token"]
    assert answer.data["lines"][0]["details"] == [{"label": "Colour", "value": "red"}]
    headers = {"HTTP_X_CART_TOKEN": token}
    bad = api.post("/api/carts/current/coupon/", {"code": "nope"}, format="json", **headers)
    assert bad.status_code == 400 and bad.data["code"] == ["No coupon has that code."]
    good = api.post("/api/carts/current/coupon/", {"code": "ten"}, format="json", **headers)
    assert (good.data["coupon"], good.data["discount"]) == ("TEN", "2.00")
    quoted = api.post(
        "/api/carts/current/quote/", {"address": {"country": "fr"}}, format="json", **headers
    )
    assert quoted.status_code == 200, quoted.data
    assert [m["name"] for m in quoted.data["methods"]] == ["Standard", "Pickup in Lyon"]
    assert (quoted.data["shipping"], quoted.data["tax"], quoted.data["total"]) == (
        "5.00",
        "4.60",
        "27.60",
    )
    pickup = quoted.data["methods"][1]["id"]
    placed = api.post(
        "/api/carts/current/checkout/",
        {"email": "g@example.com", "billing": ADDRESS, "shipping_method": pickup},
        format="json",
        **headers,
    )
    assert placed.status_code == 201, placed.data
    looked = api.get(
        "/api/orders/lookup/", {"number": placed.data["number"], "key": placed.data["key"]}
    )
    assert (looked.data["discount_total"], looked.data["shipping_method"]) == (
        "2.00",
        "Pickup in Lyon",
    )
    assert looked.data["tax_lines"] == [{"name": "TVA", "rate": "20.0000", "amount": "3.60"}]
    assert Order.objects.get().total == Decimal("21.60")


def test_coupons_zones_and_rates_are_staff_records(
    api: APIClient, buyer: Any, manager: Any, clerk: Any
) -> None:
    body = {"code": "spring", "kind": "percent", "amount": "15"}
    assert api.post("/api/coupons/", body, format="json").status_code in (401, 403)
    api.force_authenticate(buyer)
    assert api.post("/api/coupons/", body, format="json").status_code == 403
    assert api.get("/api/tax-rates/").status_code == 403
    api.force_authenticate(manager)
    made = api.post("/api/coupons/", body, format="json")
    assert made.status_code == 201, made.data
    assert Coupon.objects.get().code == "SPRING"
    zone = api.post("/api/shipping-zones/", {"name": "France", "countries": "fr"}, format="json")
    assert zone.status_code == 201, zone.data
    rate = api.post(
        "/api/tax-rates/", {"name": "VAT", "country": "fr", "rate": "20"}, format="json"
    )
    assert rate.status_code == 201 and TaxRate.objects.get().country == "FR"
    api.force_authenticate(clerk)
    assert api.get("/api/coupons/").status_code == 403
