"""The shop's rules: the cart, the stock, checkout and the order's payment.

Every change of stock is one conditional ``UPDATE`` that the database
checks, so two buyers of the last item never both get it. A product's stock
is what is on the shelf, and ``reserved`` what orders that wait for their
payment hold of it:

* checkout reserves each line (``reserved + n``, only while ``stock -
  reserved >= n``), and the order holds it for ``SHOP_RESERVATION_MINUTES``
  (default 30);
* the payment takes it (``stock - n``, ``reserved - n``);
* a failed, cancelled or expired payment releases it (``reserved - n``);
* a paid order that is cancelled or refunded returns it (``stock + n``).

Prices and names are copied to the order's lines at checkout, and the
totals are always computed here, never taken from the client.

Settings: ``SHOP_RESERVATION_MINUTES`` (30) and ``SHOP_LOW_STOCK`` (3, the
level at which ``stock_low`` is sent).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Q, QuerySet, When
from django.utils import timezone
from karni_payments.models import Payment
from karni_payments.services import create_checkout, create_refund
from rest_framework.exceptions import ValidationError

from shop import events
from shop.models import ZERO, Cart, CartItem, Order, OrderItem, Product, new_key

#: The most of one product a cart line takes.
MAX_QUANTITY = 99
#: The states in which an order has taken its stock.
STOCK_TAKEN = ("paid", "processing", "shipped", "delivered")


def reservation_minutes() -> int:
    return int(getattr(settings, "SHOP_RESERVATION_MINUTES", 30))


def low_stock_level() -> int:
    return int(getattr(settings, "SHOP_LOW_STOCK", 3))


# -- prices ----------------------------------------------------------------------------


def with_effective_price(queryset: QuerySet[Product]) -> QuerySet[Product]:
    """Each product with ``effective_price``: what a customer pays now (the sale price)."""
    now = timezone.now()
    on_sale = (
        Q(sale_price__isnull=False)
        & (Q(sale_starts__isnull=True) | Q(sale_starts__lte=now))
        & (Q(sale_ends__isnull=True) | Q(sale_ends__gt=now))
    )
    return queryset.annotate(
        effective_price=Case(
            When(on_sale, then=F("sale_price")),
            default=F("price"),
            output_field=DecimalField(max_digits=19, decimal_places=4),
        )
    )


# -- stock -----------------------------------------------------------------------------


def _lines(order: Order) -> list[tuple[int | str, int]]:
    """``(product pk, quantity)`` per line with a product, in a fixed order (no deadlocks)."""
    found: dict[Any, int] = {}
    for item in order.orderitem_set.all():
        if item.product_id is not None:
            found[item.product_id] = found.get(item.product_id, 0) + item.quantity
    return sorted(found.items(), key=lambda pair: str(pair[0]))


def _announce(product_pk: Any, quantity: int, order: Order, reason: str) -> Product:
    product = Product.objects.get(pk=product_pk)
    events.stock_changed.send(
        sender=Product, product=product, quantity=quantity, order=order, reason=reason
    )
    return product


def reserve(order: Order) -> None:
    """Hold each line's quantity for ``order``, or refuse the whole order.

    :raises ValidationError: when a product is not for sale or has fewer
        left than the line asks for. Nothing is held then (the caller's
        transaction rolls back).
    """
    for pk, quantity in _lines(order):
        held = Product.objects.filter(
            pk=pk, active=True, stock__gte=F("reserved") + quantity
        ).update(reserved=F("reserved") + quantity, updated_at=timezone.now())
        if not held:
            product = Product.objects.filter(pk=pk).first()
            left = product.available if product is not None and product.active else 0
            name = product.name if product is not None else "A product"
            raise ValidationError(
                {"stock": [f"{name}: only {left} left." if left else f"{name} is sold out."]}
            )
        _announce(pk, quantity, order, "reserved")


def release(order: Order) -> None:
    """Give back what ``order`` held: it was not paid."""
    for pk, quantity in _lines(order):
        Product.objects.filter(pk=pk, reserved__gte=quantity).update(
            reserved=F("reserved") - quantity, updated_at=timezone.now()
        )
        _announce(pk, quantity, order, "released")


def take(order: Order) -> None:
    """The paid order takes what it held off the shelf."""
    for pk, quantity in _lines(order):
        Product.objects.filter(pk=pk, reserved__gte=quantity, stock__gte=quantity).update(
            stock=F("stock") - quantity,
            reserved=F("reserved") - quantity,
            updated_at=timezone.now(),
        )
        product = _announce(pk, quantity, order, "taken")
        if product.stock <= low_stock_level():
            events.stock_low.send(sender=Product, product=product)


def restock(order: Order) -> None:
    """A paid order was cancelled or refunded: its items go back on the shelf."""
    for pk, quantity in _lines(order):
        Product.objects.filter(pk=pk).update(stock=F("stock") + quantity, updated_at=timezone.now())
        _announce(pk, quantity, order, "returned")


# -- the cart --------------------------------------------------------------------------


def find_cart(user: Any, token: str | None, *, create: bool = False) -> Cart | None:
    """The signed-in customer's cart, or the visitor's cart its token names."""
    if user is not None and user.is_authenticated:
        cart = Cart.objects.filter(customer=user).order_by("created_at").first()
        if cart is None and create:
            cart = Cart.objects.create(customer=user, token=new_key())
        return cart
    if token:
        found = Cart.objects.filter(customer__isnull=True, token=token).first()
        if found is not None:
            return found
    return Cart.objects.create(token=new_key()) if create else None


def set_quantity(cart: Cart, product: Product, quantity: int) -> None:
    """Put ``quantity`` of ``product`` in ``cart`` (0 takes it out).

    :raises ValidationError: for a product that is not for sale, or more
        than are left.
    """
    if quantity <= 0:
        CartItem.objects.filter(cart=cart, product=product).delete()
        return
    if not product.active:
        raise ValidationError({"product": [f"{product.name} is not for sale."]})
    if quantity > min(product.available, MAX_QUANTITY):
        left = product.available
        raise ValidationError(
            {"quantity": [f"Only {left} of {product.name} left." if left else "Sold out."]}
        )
    item = CartItem.objects.filter(cart=cart, product=product).first()
    if item is None:
        CartItem.objects.create(cart=cart, product=product, quantity=quantity)
    elif item.quantity != quantity:
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])


@transaction.atomic
def merge(user: Any, token: str | None) -> Cart:
    """The visitor's cart joins the customer's cart when they sign in.

    Quantities add up, never past what is left of a product. Orders placed as
    a guest with the customer's verified email become theirs too.
    """
    cart = find_cart(user, None, create=True)
    assert cart is not None
    visitor = Cart.objects.filter(customer__isnull=True, token=token).first() if token else None
    if visitor is not None and visitor.pk != cart.pk:
        for item in visitor.lines():
            mine = CartItem.objects.filter(cart=cart, product=item.product).first()
            wanted = item.quantity + (mine.quantity if mine else 0)
            fits = min(wanted, item.product.available, MAX_QUANTITY)
            if fits > 0 and item.product.active:
                set_quantity(cart, item.product, fits)
        visitor.cartitem_set.all().delete()
        visitor.delete()
        events.cart_merged.send(sender=Cart, cart=cart, user=user)
    claim_orders(user)
    return cart


def claim_orders(user: Any) -> list[Order]:
    """The guest orders placed with ``user``'s email, once that email is verified."""
    if not getattr(user, "email_verified", False) or not user.email:
        return []
    found = list(Order.objects.filter(customer__isnull=True, email__iexact=user.email))
    if found:
        rows = Order.objects.filter(pk__in=[order.pk for order in found])
        rows.update(customer=user)  # karni: allow(audited-bulk-write): audit keeps status only
        events.customer_orders_claimed.send(sender=Order, user=user, orders=found)
    return found


def cart_problems(lines: Iterable[CartItem]) -> dict[str, str]:
    """What stops a line from being bought, by line id: sold out, fewer left, not for sale."""
    found: dict[str, str] = {}
    for line in lines:
        product = line.product
        if not product.active:
            found[str(line.pk)] = "No longer for sale."
        elif product.available <= 0:
            found[str(line.pk)] = "Sold out."
        elif line.quantity > product.available:
            found[str(line.pk)] = f"Only {product.available} left."
    return found


def cart_total(lines: Iterable[CartItem]) -> Decimal:
    return sum((line.product.current_price() * line.quantity for line in lines), ZERO)


# -- checkout --------------------------------------------------------------------------


def _new_order(**values: Any) -> Order:
    for _attempt in range(5):
        try:
            with transaction.atomic():
                return Order.objects.create(**values)  # the next number (Order.save)
        except IntegrityError:
            continue  # another checkout took the number at the same moment
    raise ValidationError({"number": ["Too many orders at once. Try again."]})


@transaction.atomic
def place_order(
    cart: Cart,
    *,
    customer: Any,
    email: str,
    billing: dict[str, str],
    shipping: dict[str, str],
    note: str = "",
) -> Order:
    """Turn ``cart`` into an order waiting for its payment, and hold its stock.

    Each line copies the product's name, SKU and price today. The totals are
    the sum of the lines. The cart empties.

    :raises ValidationError: for an empty cart, or a line the stock cannot fill.
    """
    release_expired()
    lines = cart.lines()
    if not lines:
        raise ValidationError({"cart": ["The cart is empty."]})
    subtotal = cart_total(lines)
    order = _new_order(
        customer=customer if customer is not None and customer.is_authenticated else None,
        email=email,
        status="pending",
        subtotal=subtotal,
        total=subtotal,
        billing=billing,
        shipping=shipping,
        note=note,
        key=new_key(),
        reserved_until=timezone.now() + timedelta(minutes=reservation_minutes()),
    )
    OrderItem.objects.bulk_create(
        OrderItem.from_product(order, line.product, line.quantity) for line in lines
    )
    reserve(order)
    cart.cartitem_set.all().delete()
    events.order_placed.send(sender=Order, order=order)
    return order


def order_link(order: Order) -> str:
    """The order's page in the app, with the key a guest reads it by."""
    frontend = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    return f"{frontend}/order/{order.number}?key={order.key}"


def open_payment(order: Order) -> str:
    """Start the order's payment at the provider. Returns where the customer pays."""
    if not order.payable:
        raise ValidationError({"order": ["This order is not waiting for a payment."]})
    back = order_link(order)
    payment, session = create_checkout(
        order.customer,
        amount=order.total,
        success_url=f"{back}&paid=1",
        cancel_url=back,
        metadata={"order": str(order.pk), "number": order.number},
    )
    rows = Order.objects.filter(pk=order.pk)
    rows.update(payment=payment)  # karni: allow(audited-bulk-write): audit keeps status only
    order.payment = payment
    return session.url


def release_expired(now: Any = None) -> int:
    """Cancel the orders whose payment never came in time: their stock is free again."""
    moment = now or timezone.now()
    expired = Order.objects.filter(status="pending", reserved_until__lt=moment)
    count = 0
    for order in expired:
        order.transition("status", "cancelled")
        count += 1
    return count


# -- the payment -----------------------------------------------------------------------


def settle(payment: Payment) -> None:
    """Move the payment's order: paid when it succeeded, failed when it did not.

    A payment that succeeds for an order that stopped waiting (it expired and
    its stock went back) is refunded at once.
    """
    for order in Order.objects.filter(payment=payment).select_for_update():
        if payment.status == Payment.Status.SUCCEEDED:
            if order.status == "pending":
                order.transition("status", "paid", paid_at=timezone.now())
            elif order.status in ("failed", "cancelled"):
                transaction.on_commit(lambda p=payment: refund(p, "the order had expired"))
        elif payment.status in (Payment.Status.FAILED, Payment.Status.CANCELED):
            if order.status == "pending":
                order.transition("status", "failed")


def refund(payment: Payment | None, reason: str) -> None:
    """Refund what is left of ``payment``, if it took money."""
    if payment is None:
        return
    payment.refresh_from_db()
    if payment.status in (Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED):
        create_refund(payment, reason=reason)
