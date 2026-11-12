"""The marketplace rules of karni.yaml: what buyers, sellers and staff may send or not."""

from decimal import Decimal
from typing import Any

import pytest
from karni.seeding import seed
from karni.testing.api import user_with_roles
from karni.testing.factories import create
from karni_payments.models import Payment, Refund
from karni_payments.providers.test import TestProvider

from market.models import Listing, Order, Payout, Seller

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def _code(response: Any, field: str) -> str:
    return str(response.json()[field][0])[:4]


def _order(client: Any, listing: Listing, quantity: int = 1) -> Any:
    body = {"listing": str(listing.pk), "quantity": quantity}
    return client.post("/api/orders/", body, format="json")


def _paid(order_id: str, client: Any) -> Order:
    """Pay the order the way the provider's webhook settles it."""
    paid = client.post(f"/api/orders/{order_id}/pay/")
    payment = Payment.objects.get(pk=paid.json()["payment"])
    payment.status = Payment.Status.SUCCEEDED
    payment.save()
    return Order.objects.get(pk=order_id)


def test_a_listing_goes_only_into_your_own_shop(client_as: Any) -> None:
    shop = create(Seller)
    body = {"seller": str(shop.pk), "title": "Mug", "price": "12.00", "active": True}
    for role in ("buyer", "seller"):
        refused = client_as(role).post("/api/listings/", body, format="json")
        assert refused.status_code == 403 and refused.json()["detail"].startswith("E134: ")
    owner = client_as("seller", user=shop.user)
    assert owner.post("/api/listings/", body, format="json").status_code == 201


def test_one_shop_per_person(client_as: Any) -> None:
    client = client_as("seller")
    assert client.post("/api/sellers/", {"name": "Kiln"}, format="json").status_code == 201
    again = client.post("/api/sellers/", {"name": "Kiln Two"}, format="json")
    assert again.status_code == 400 and _code(again, "user") == "E991"


def test_prices_and_quantities_keep_their_bounds(client_as: Any) -> None:
    shop = create(Seller)
    owner = client_as("seller", user=shop.user)
    body = {"seller": str(shop.pk), "title": "Mug", "price": "-5", "active": True}
    price = owner.post("/api/listings/", body, format="json")
    assert price.status_code == 400 and _code(price, "price") == "E990"
    listing = create(Listing, active=True)
    buyer = client_as("buyer")
    for quantity in (0, -2):
        refused = _order(buyer, listing, quantity)
        assert refused.status_code == 400 and _code(refused, "quantity") == "E990"


def test_no_order_of_a_paused_listing_or_your_own(client_as: Any) -> None:
    paused = create(Listing, active=False)
    staff = client_as("staff")  # staff see a paused listing, and still cannot order it
    refused = _order(staff, paused)
    assert refused.status_code == 400 and _code(refused, "listing") == "E993"
    mine = create(Listing, active=True)
    seller = client_as("seller", user=mine.seller.user)
    own = _order(seller, mine)
    assert own.status_code == 400 and _code(own, "listing") == "E993"


def test_quantity_and_listing_are_kept_and_a_paid_order_stays(client_as: Any) -> None:
    buyer = client_as("buyer")
    order = _order(buyer, create(Listing, active=True)).json()
    more = buyer.patch(f"/api/orders/{order['id']}/", {"quantity": 100}, format="json")
    assert more.status_code == 400 and _code(more, "quantity") == "E994"
    _paid(order["id"], buyer)
    assert buyer.delete(f"/api/orders/{order['id']}/").status_code == 403
    refused = client_as("staff").delete(f"/api/orders/{order['id']}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"


def test_pay_once_and_cancel_only_a_pending_order(client_as: Any) -> None:
    buyer = client_as("buyer")
    order = _order(buyer, create(Listing, active=True)).json()
    first = buyer.post(f"/api/orders/{order['id']}/pay/")
    assert buyer.post(f"/api/orders/{order['id']}/pay/").json() == first.json()
    _paid(order["id"], buyer)
    again = buyer.post(f"/api/orders/{order['id']}/pay/")
    assert again.status_code == 409 and again.json()["code"] == "E997"
    cancel = buyer.post(f"/api/orders/{order['id']}/cancel/")
    assert cancel.status_code == 409 and cancel.json()["code"] == "E997"
    other = _order(buyer, create(Listing, active=True)).json()
    cancelled = buyer.post(f"/api/orders/{other['id']}/cancel/")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    paid_cancelled = buyer.post(f"/api/orders/{other['id']}/pay/")
    assert paid_cancelled.status_code == 409


def test_the_seller_ships_and_the_buyer_confirms_delivery(client_as: Any) -> None:
    listing = create(Listing, active=True)
    buyer = client_as("buyer")
    order = _order(buyer, listing).json()
    url = f"/api/orders/{order['id']}"
    early = client_as("seller", user=listing.seller.user).post(f"{url}/ship/")
    assert early.status_code == 409  # not paid yet
    _paid(order["id"], buyer)
    assert buyer.post(f"{url}/ship/").status_code == 403  # only the seller (or staff)
    assert client_as("seller").post(f"{url}/ship/").status_code in (403, 404)  # another seller
    shipped = client_as("seller", user=listing.seller.user).post(f"{url}/ship/")
    assert shipped.status_code == 200 and shipped.json()["status"] == "shipped"
    delivered = buyer.post(f"{url}/deliver/")
    assert delivered.status_code == 200 and delivered.json()["status"] == "delivered"


def test_staff_refund_a_paid_order_and_its_payout_is_void(client_as: Any) -> None:
    buyer = client_as("buyer")
    order = _order(buyer, create(Listing, active=True, price=Decimal("30.00"))).json()
    _paid(order["id"], buyer)
    payout = Payout.objects.get(order_id=order["id"])
    assert payout.status == "pending"
    assert buyer.post(f"/api/orders/{order['id']}/refund/").status_code == 403
    refunded = client_as("staff").post(f"/api/orders/{order['id']}/refund/")
    assert refunded.status_code == 200 and refunded.json()["status"] == "refunded"
    assert refunded.json()["refund"]["amount"] == "30.00"
    payout.refresh_from_db()
    assert payout.status == "void"
    assert Refund.objects.count() == 1


def test_staff_mark_a_payout_paid_and_it_says_when(client_as: Any) -> None:
    payout = create(Payout)
    marked = client_as("staff").post(f"/api/payouts/{payout.pk}/mark_paid/")
    assert marked.status_code == 200 and marked.json()["paid_at"]


def test_seeded_paid_orders_owe_their_sellers() -> None:
    seed(seed=5, reset=True)
    for order in Order.objects.filter(status__in=["paid", "shipped", "delivered", "refunded"]):
        payout = Payout.objects.get(order=order)
        assert payout.seller == order.listing.seller and order.buyer != payout.seller.user


def test_the_buyer_hears_the_order_was_paid_and_shipped(
    client_as: Any, mailoutbox: list[Any], django_capture_on_commit_callbacks: Any
) -> None:
    listing = create(Listing, active=True, title="Stoneware mug")
    buyer = client_as("buyer")
    order = _order(buyer, listing).json()
    with django_capture_on_commit_callbacks(execute=True):
        _paid(order["id"], buyer)
    with django_capture_on_commit_callbacks(execute=True):
        client_as("seller", user=listing.seller.user).post(f"/api/orders/{order['id']}/ship/")
    assert [message.subject for message in mailoutbox] == [
        "Order received: Stoneware mug",
        "On its way: Stoneware mug",
    ]
