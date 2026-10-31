"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, F, Sum
from karni.events import on_created, on_deleted, on_updated
from karni_payments.models import Payment
from rest_framework.exceptions import ValidationError

from shop.karni import models as karni


class Category(karni.Category):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Product(karni.Product):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Cart(karni.Cart):
    """A customer's cart. Checkout turns its items into an order."""

    @transaction.atomic
    def checkout(self) -> "Order":
        """An order with an item per cart item at the current price. The cart is emptied."""
        items = list(self.cartitem_set.select_related("product"))
        if not items:
            raise ValidationError({"cart": ["The cart is empty."]})
        total = sum((i.product.price * i.quantity for i in items), Decimal("0.00"))
        order = Order.objects.create(customer=self.customer, total=total)
        OrderItem.objects.bulk_create(
            OrderItem(order=order, product=i.product, quantity=i.quantity, unit_price=i.product.price)
            for i in items
        )
        self.cartitem_set.all().delete()
        return order


class CartItem(karni.CartItem):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Order(karni.Order):
    """An order. Its total is always the sum of its items."""

    def items_total(self) -> Decimal:
        """Quantity times unit price, summed over the order's items."""
        line = F("quantity") * F("unit_price")
        found = self.orderitem_set.aggregate(sum=Sum(line, output_field=DecimalField()))
        return found["sum"] or Decimal("0.00")

    def update_total(self) -> None:
        self.total = self.items_total()
        self.save(update_fields=["total", "updated_at"])


class OrderItem(karni.OrderItem):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


@on_created(OrderItem)
@on_updated(OrderItem)
@on_deleted(OrderItem)
def keep_the_order_total(item: OrderItem) -> None:
    """An item added, changed or removed changes its order's total."""
    item.order.update_total()


@on_updated(Payment)
def mark_the_order_paid(payment: Payment) -> None:
    """The payment provider's webhook settled the payment: its pending order is paid."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for order in Order.objects.filter(payment=payment, status="pending"):
        order.transition("status", "paid")
