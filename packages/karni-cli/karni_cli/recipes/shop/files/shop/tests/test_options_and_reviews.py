"""Variations, coupons, shipping and tax on a shop order, reviews, the wishlist and the
products shown beside a product."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from karni.testing import user_with_roles
from karni.testing.factories import create
from karni_commerce import services as commerce
from karni_commerce.models import (
    Cart,
    Coupon,
    ShippingMethod,
    ShippingZone,
    TaxRate,
)
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from shop import services
from shop.models import (
    Attribute,
    AttributeValue,
    Category,
    Product,
    Review,
    Shipment,
    Variation,
    WishlistItem,
)
from shop.tests.conftest import ADDRESS, pay, place

pytestmark = pytest.mark.django_db

MakeProduct = Callable[..., Product]


@pytest.fixture
def shirt(make_product: MakeProduct) -> Product:
    """A shirt in two sizes: M at the product's price, L dearer, each with its stock."""
    product = make_product(name="Linen Shirt", sku="SHIRT", price=Decimal("30.00"))
    size = create(Attribute, name="Size", position=0)
    for position, (value, price, stock) in enumerate(
        [("M", None, 3), ("L", Decimal("34.00"), 1)]
    ):
        found = create(AttributeValue, attribute=size, value=value, position=position)
        variation = create(
            Variation,
            product=product,
            sku=f"SHIRT-{value}",
            price=price,
            sale_price=None,
            stock=stock,
            available=stock,
            active=True,
            position=position,
            image=None,
        )
        variation.values.set([found])
    return product


def way(product: Product, sku: str) -> Variation:
    return Variation.objects.get(product=product, sku=sku)


def fresh(row: Any) -> Any:
    row.refresh_from_db()
    return row


# -- variations ----------------------------------------------------------------------


def test_a_product_with_variations_is_bought_by_one_with_its_price_and_stock(
    shirt: Product,
) -> None:
    large = way(shirt, "SHIRT-L")
    cart = Cart.objects.create()
    with pytest.raises(ValidationError, match="Choose the options"):
        commerce.set_line(cart, "product", str(shirt.pk), 1)
    with pytest.raises(ValidationError, match="does not come that way"):
        commerce.set_line(cart, "product", str(shirt.pk), 1, {"variation": "nope"})
    commerce.set_line(cart, "product", str(shirt.pk), 1, {"variation": str(large.pk)})
    medium = way(shirt, "SHIRT-M")
    commerce.set_line(cart, "product", str(shirt.pk), 2, {"variation": str(medium.pk)})
    assert cart.lines.count() == 2
    with pytest.raises(ValidationError, match="Only 1 of Linen Shirt, L left"):
        commerce.set_line(
            cart, "product", str(shirt.pk), 2, {"variation": str(large.pk)}
        )
    order = place(cart)
    lines = {line.sku: line for line in order.lines.all()}
    assert lines["SHIRT-L"].unit_price == Decimal("34.00")
    assert lines["SHIRT-L"].name == "Linen Shirt, L"
    assert lines["SHIRT-L"].details == [{"label": "Size", "value": "L"}]
    assert lines["SHIRT-M"].unit_price == Decimal("30.00")
    assert (fresh(large).available, fresh(medium).available) == (0, 1)
    pay(order)
    assert (fresh(large).stock, fresh(medium).stock) == (0, 1)
    assert fresh(shirt).stock == 5  # the product's own stock is not the variations'
    commerce.cancel(order)
    assert (fresh(large).stock, fresh(large).available) == (1, 1)


def test_a_product_with_variations_reads_their_stock_everywhere(
    shirt: Product, settings: Any
) -> None:
    """Its stock is its variations' added up: the API, the filters, the sort and the
    home tiles follow them, and its own figure is never asked for."""
    settings.SHOP_LOW_STOCK = 2
    plain = create(
        Product,
        name="Plain Mug",
        sku="MUG",
        price=Decimal("9.00"),
        sale_price=None,
        stock=1,
        available=1,
        active=True,
    )
    manager = APIClient()
    manager.force_authenticate(user_with_roles("shop-manager"))
    row = manager.get(f"/api/products/{shirt.pk}/").data
    assert (row["stock"], row["available"], row["stock_from_variations"]) == (
        4,
        4,
        True,
    )
    assert fresh(shirt).stock == 5 and not shirt.runs_low()
    # Both sizes sell: the product is sold out though its own stock says 5.
    for sku, count in (("SHIRT-M", 3), ("SHIRT-L", 1)):
        cart = Cart.objects.create()
        variation = {"variation": str(way(shirt, sku).pk)}
        commerce.set_line(cart, "product", str(shirt.pk), count, variation)
        pay(place(cart))
    assert fresh(shirt).stock == 5 and fresh(shirt).runs_low()
    row = manager.get(f"/api/products/{shirt.pk}/").data
    assert (row["stock"], row["available"], row["stock_left"]) == (0, 0, 0)
    sold_out = manager.get("/api/products/", {"available__lte": 0, "active": "true"})
    assert [found["sku"] for found in sold_out.data["results"]] == ["SHIRT"]
    in_stock = manager.get("/api/products/", {"stock__gte": 1})
    assert "SHIRT" not in [found["sku"] for found in in_stock.data["results"]]
    ordered = manager.get("/api/products/", {"ordering": "available"})
    assert [found["sku"] for found in ordered.data["results"]][:2] == ["SHIRT", "MUG"]
    board = manager.get("/api/dashboard/").data["tiles"]
    tiles = {tile["key"]: tile for tile in board}
    low = [found["name"] for found in tiles["shop.low_stock"]["data"]["rows"]]
    assert low[:2] == ["Linen Shirt", plain.name]
    # The form sends back the stock it read: nothing changes. Another figure is refused.
    same = manager.patch(f"/api/products/{shirt.pk}/", {"stock": 0}, format="json")
    assert same.status_code == 200, same.data
    other = manager.patch(f"/api/products/{shirt.pk}/", {"stock": 9}, format="json")
    assert other.status_code == 400
    assert "variation" in str(other.data)
    assert fresh(shirt).stock == 5


def test_the_last_of_a_variation_goes_to_one_buyer(shirt: Product) -> None:
    large = {"variation": str(way(shirt, "SHIRT-L").pk)}
    first, second = Cart.objects.create(), Cart.objects.create()
    commerce.set_line(first, "product", str(shirt.pk), 1, large)
    commerce.set_line(second, "product", str(shirt.pk), 1, large)
    place(first)
    with pytest.raises(ValidationError, match="sold out"):
        place(second)


def test_the_catalogue_shows_the_options_the_price_range_and_what_is_left(
    shirt: Product,
) -> None:
    client = APIClient()
    answer = client.get("/api/products/", {"slug": shirt.slug})
    [row] = answer.data["results"]
    assert row["options"] == [{"name": "Size", "values": ["M", "L"]}]
    assert (row["price_from"], row["price_to"], row["stock_left"]) == (
        "30.00",
        "34.00",
        4,
    )
    assert [
        (v["label"], v["current_price"], v["available"]) for v in row["variations"]
    ] == [
        ("M", "30.00", 3),
        ("L", "34.00", 1),
    ]
    by_id = client.get("/api/products/", {"ids": str(shirt.pk)})
    assert [found["id"] for found in by_id.data["results"]] == [str(shirt.pk)]


def test_the_catalogue_reads_variations_in_a_fixed_number_of_queries(
    make_product: MakeProduct, shirt: Product
) -> None:
    client = APIClient()
    client.get("/api/products/")
    with CaptureQueriesContext(connection) as few:
        client.get("/api/products/")
    for number in range(6):
        extra = make_product(name=f"Shirt {number}", sku=f"S{number}")
        create(
            Variation,
            product=extra,
            sku=f"S{number}-M",
            price=None,
            sale_price=None,
            stock=2,
            available=2,
            active=True,
            position=0,
            image=None,
        )
    with CaptureQueriesContext(connection) as many:
        client.get("/api/products/")
    assert len(many) == len(few)


# -- coupons, shipping and tax on a shop order ---------------------------------------


def test_a_category_coupon_shipping_and_tax_on_a_shop_order(
    make_product: MakeProduct,
) -> None:
    kitchen = create(Category, name="Kitchen", parent=None)
    pans = create(Category, name="Pans", parent=kitchen)
    pan = make_product(name="Pan", sku="PAN", price=Decimal("40.00"))
    pan.categories.set([pans])
    pen = make_product(name="Pen", sku="PEN", price=Decimal("10.00"))
    europe = ShippingZone.objects.create(name="Europe", countries="PT, ES")
    ShippingMethod.objects.create(zone=europe, name="Standard", cost=Decimal("6.50"))
    TaxRate.objects.create(name="VAT", country="", rate=Decimal(20))
    Coupon.objects.create(
        code="KITCHEN15",
        amount=Decimal(15),
        limits={"categories": [{"key": str(kitchen.pk), "name": "Kitchen"}]},
    )
    cart = Cart.objects.create()
    for product in (pan, pen):
        commerce.set_line(cart, "product", str(product.pk), 1)
    commerce.apply_coupon(cart, "kitchen15")  # the pan's parent category counts
    order = place(cart)
    assert order.discount_total == Decimal("6.00")  # 15% of the pan only
    assert (order.shipping_method, order.shipping_total) == (
        "Standard",
        Decimal("6.50"),
    )
    # (50.00 - 6.00 + 6.50) x 20% = 10.10
    assert order.tax_total == Decimal("10.10") and order.total == Decimal("60.60")


# -- reviews -------------------------------------------------------------------------


def delivered(product: Product, user: Any, **variation: str) -> None:
    """``user`` bought ``product`` and its parcel arrived."""
    cart = Cart.objects.create()
    commerce.set_line(cart, "product", str(product.pk), 1, variation or None)
    order = pay(place(cart, email=user.email, user=user))
    shipment = Shipment.objects.get(order=order)
    services.ship(shipment, "TR1")
    services.deliver(shipment)


def test_only_a_buyer_whose_parcel_arrived_reviews_and_staff_approve_it(
    make_product: MakeProduct,
) -> None:
    lamp = make_product(name="Lamp", sku="LAMP")
    buyer = user_with_roles("customer", email="buyer@example.com")
    other = user_with_roles("customer", email="other@example.com")
    staff = user_with_roles("shop-staff", email="staff@example.com")
    client = APIClient()
    body = {"product": str(lamp.pk), "rating": 5, "title": "Good", "body": "Bright."}
    assert client.post("/api/reviews/", body, format="json").status_code in (401, 403)
    client.force_authenticate(buyer)
    early = client.post("/api/reviews/", body, format="json")
    assert early.status_code == 400
    assert early.data["product"] == [
        "You can review a product once it has reached you."
    ]
    delivered(lamp, buyer)
    asked = client.get("/api/reviews/eligibility/", {"product": str(lamp.pk)})
    assert asked.data == {"can_review": True, "reason": "", "status": None}
    sneaky = {**body, "status": "approved", "author": str(other.pk), "verified": False}
    made = client.post("/api/reviews/", sneaky, format="json")
    assert made.status_code == 201, made.data
    review = Review.objects.get()
    assert (review.author, review.status, review.verified) == (buyer, "pending", True)
    again = client.post("/api/reviews/", body, format="json")
    assert again.status_code == 400
    # Waiting: the writer sees it, nobody else does, and it does not count yet.
    assert client.get("/api/reviews/", {"product": str(lamp.pk)}).data["count"] == 1
    client.force_authenticate(other)
    assert client.get("/api/reviews/", {"product": str(lamp.pk)}).data["count"] == 0
    assert client.patch(
        f"/api/reviews/{review.pk}/", {"status": "approved"}, format="json"
    ).status_code in (403, 404)
    assert fresh(lamp).rating_count == 0
    client.force_authenticate(staff)
    moved = client.patch(
        f"/api/reviews/{review.pk}/", {"status": "approved"}, format="json"
    )
    assert moved.status_code == 200, moved.data
    assert (fresh(lamp).rating_average, lamp.rating_count) == (Decimal("5.00"), 1)
    visitor = APIClient().get("/api/reviews/", {"product": str(lamp.pk)})
    assert visitor.data["count"] == 1
    name = visitor.data["results"][0]["author_name"]
    assert name and "@" not in name  # a first name and an initial, never the email


def test_the_average_counts_approved_reviews_only(make_product: MakeProduct) -> None:
    vase = make_product(name="Vase", sku="VASE")
    for number, (rating, status) in enumerate(
        [(5, "approved"), (3, "approved"), (1, "rejected"), (2, "pending")]
    ):
        person = user_with_roles("customer", email=f"p{number}@example.com")
        review = Review.objects.create(
            product=vase, author=person, rating=rating, body="Words", status="pending"
        )
        if status != "pending":
            review.transition("status", status)
    assert (fresh(vase).rating_average, vase.rating_count) == (Decimal("4.00"), 2)


def test_a_review_of_a_variation_counts_for_its_product(shirt: Product) -> None:
    buyer = user_with_roles("customer", email="buyer@example.com")
    delivered(shirt, buyer, variation=str(way(shirt, "SHIRT-M").pk))
    assert services.review_problem(buyer, shirt) == ""


# -- the wishlist and the products beside a product ----------------------------------


def test_the_wishlist_is_each_customers_own(make_product: MakeProduct) -> None:
    lamp = make_product(name="Lamp", sku="LAMP")
    mira = user_with_roles("customer", email="mira@example.com")
    noor = user_with_roles("customer", email="noor@example.com")
    client = APIClient()
    assert client.get("/api/wishlist-items/").status_code in (401, 403)
    client.force_authenticate(mira)
    first = client.post(
        "/api/wishlist-items/", {"product": str(lamp.pk)}, format="json"
    )
    assert first.status_code == 201, first.data
    client.post("/api/wishlist-items/", {"product": str(lamp.pk)}, format="json")
    assert WishlistItem.objects.filter(user=mira).count() == 1  # kept once
    client.force_authenticate(noor)
    assert client.get("/api/wishlist-items/").data["count"] == 0
    row = WishlistItem.objects.get()
    assert client.delete(f"/api/wishlist-items/{row.pk}/").status_code in (403, 404)
    client.force_authenticate(mira)
    assert client.delete(f"/api/wishlist-items/{row.pk}/").status_code == 204


def test_related_products_are_staffs_choice_then_the_same_category(
    make_product: MakeProduct,
) -> None:
    garden = create(Category, name="Garden", parent=None)
    trowel, can, gloves, hidden = (
        make_product(name=name, sku=name.upper(), active=name != "Hidden")
        for name in ("Trowel", "Can", "Gloves", "Hidden")
    )
    for product in (trowel, can, gloves, hidden):
        product.categories.set([garden])
    chosen = make_product(name="Kneeler", sku="KNEELER")
    trowel.related.set([chosen])
    names = [
        row["name"]
        for row in APIClient().get(f"/api/products/{trowel.pk}/related/").data
    ]
    assert names[0] == "Kneeler"
    assert set(names[1:]) == {"Can", "Gloves"} and "Trowel" not in names


def test_checkout_answers_with_the_shipping_methods_for_the_address(
    shirt: Product,
) -> None:
    zone = ShippingZone.objects.create(name="Portugal", countries="PT")
    ShippingMethod.objects.create(
        zone=zone, name="Courier", cost=Decimal("4.00"), free_above=Decimal("60.00")
    )
    ShippingMethod.objects.create(zone=zone, name="Pickup", kind="pickup")
    client = APIClient()
    medium = str(way(shirt, "SHIRT-M").pk)
    added = client.post(
        "/api/carts/current/lines/",
        {
            "kind": "product",
            "item": str(shirt.pk),
            "quantity": 1,
            "options": {"variation": medium},
        },
        format="json",
    )
    token = added.data["token"]
    assert added.data["lines"][0]["details"] == [{"label": "Size", "value": "M"}]
    quoted = client.post(
        "/api/carts/current/quote/",
        {"address": {"country": ADDRESS["country"]}},
        format="json",
        HTTP_X_CART_TOKEN=token,
    )
    assert [m["name"] for m in quoted.data["methods"]] == ["Courier", "Pickup"]
    assert quoted.data["total"] == "34.00"
