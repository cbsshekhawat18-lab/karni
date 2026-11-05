"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, F, Sum
from karni.events import on_created, on_deleted, on_updated
from karni_payments.models import Payment
from karni_payments.services import create_refund
from rest_framework.exceptions import ValidationError
from shop.errors import Conflict
from shop.karni import models as karni


class Category(karni.Category):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Product(karni.Product):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Cart(karni.Cart):
    """A customer's cart. Checkout turns its items into an order."""

    @classmethod
    def of(cls, customer) -> "Cart":
        return cls.objects.get_or_create(customer=customer)[0]

    def total(self) -> Decimal:
        return sum(
            (i.line_total() for i in self.cartitem_set.select_related("product")), Decimal(0)
        )

    @transaction.atomic
    def checkout(self) -> "Order":
        """An order with an item per cart item at today's price. Stock goes down, the cart empties."""
        items = list(self.cartitem_set.select_related("product").order_by("created_at"))
        if not items:
            raise ValidationError({"cart": ["The cart is empty."]})
        products = Product.objects.select_for_update().in_bulk([i.product_id for i in items])
        for item in items:
            if products[item.product_id].stock < item.quantity:
                raise Conflict(f"Not enough stock of {products[item.product_id].name}.")
        order = Order.objects.create(customer=self.customer, total=Decimal(0))
        for item in items:
            product = products[item.product_id]
            OrderItem.objects.create(
                order=order, product=product, quantity=item.quantity, unit_price=product.price
            )
            Product.objects.filter(pk=product.pk).update(stock=F("stock") - item.quantity)
        self.cartitem_set.all().delete()
        order.refresh_from_db()
        return order


class CartItem(karni.CartItem):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    def line_total(self) -> Decimal:
        return self.product.price * self.quantity


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

    @transaction.atomic
    def refund(self) -> None:
        """Refund through the payment provider, give the stock back, mark everything refunded."""
        self.transition("status", "refunded")
        if self.payment_id:
            create_refund(self.payment)
            Payment.objects.filter(pk=self.payment_id).update(status=Payment.Status.REFUNDED)
        for item in self.orderitem_set.all():
            Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)


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
    """The provider settled the payment: its pending order is paid."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for order in Order.objects.filter(payment=payment, status="pending"):
        order.transition("status", "paid")
