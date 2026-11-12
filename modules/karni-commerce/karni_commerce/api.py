"""Hand-written serializers for the cart and checkout actions and an order as its buyer reads it.

The resource serializers of the models are generated from their ``APIMeta``
(:func:`karni.api.serializers.build_serializer`). These shape the actions'
input and output, and feed ``@extend_schema``, so the OpenAPI schema and with
it ``@karni/commerce-ui``'s types know them. Money goes out as a decimal
string with two places, with the order's or the project's ``currency``.

Override / escape hatch: subclass the viewset and use your own serializer in
an overridden action. These are plain DRF serializers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from karni_commerce import conf, services
from karni_commerce.models import Order, OrderLine
from karni_commerce.services import PricedLine

__all__ = [
    "AddressSerializer",
    "CartSerializer",
    "CheckoutResultSerializer",
    "CheckoutSerializer",
    "MergeSerializer",
    "OrderKeySerializer",
    "OrderViewSerializer",
    "PayResultSerializer",
    "RefundInputSerializer",
    "SetLineSerializer",
    "media_url",
]


def media_url(context: dict[str, Any], value: Any) -> str | None:
    """A picture's address: a file field's URL made absolute, or a URL as given."""
    if not value:
        return None
    url = getattr(value, "url", value)
    request = context.get("request")
    text = str(url)
    if request is not None and text.startswith("/"):
        return str(request.build_absolute_uri(text))
    return text


def _amount(value: Any) -> str:
    return f"{Decimal(value):.2f}"


class CartLineSerializer(serializers.Serializer[PricedLine]):
    """A cart line as the cart page shows it."""

    id = serializers.CharField()
    kind = serializers.CharField()
    item = serializers.CharField()
    name = serializers.CharField()
    url = serializers.CharField(allow_blank=True)
    image = serializers.CharField(allow_null=True)
    options = serializers.DictField()
    quantity = serializers.IntegerField()
    unit_price = serializers.CharField()
    compare_at_price = serializers.CharField(allow_null=True)
    line_total = serializers.CharField()
    available = serializers.IntegerField(allow_null=True)
    problem = serializers.CharField(allow_blank=True)

    def to_representation(self, instance: PricedLine) -> dict[str, Any]:
        adapter, item, line = instance.adapter, instance.item, instance.line
        found = adapter is not None and item is not None
        compare = instance.price.compare_at if instance.price is not None else None
        return {
            "id": str(line.pk),
            "kind": line.kind,
            "item": line.item,
            "name": instance.name,
            "url": adapter.url(item) if found and adapter is not None else "",
            "image": media_url(self.context, adapter.image(item))
            if found and adapter is not None
            else None,
            "options": dict(line.options or {}),
            "quantity": line.quantity,
            "unit_price": _amount(instance.unit_price),
            "compare_at_price": _amount(compare)
            if compare is not None and Decimal(compare) > instance.unit_price
            else None,
            "line_total": _amount(instance.line_total),
            "available": adapter.available(item, line.options)
            if found and adapter is not None
            else 0,
            "problem": instance.problem,
        }


class CartSerializer(serializers.Serializer[Any]):
    """The cart: its lines, the count, the subtotal, and whether it can be checked out."""

    token = serializers.CharField(allow_null=True)
    lines = CartLineSerializer(many=True)
    count = serializers.IntegerField()
    subtotal = serializers.CharField()
    currency = serializers.CharField()
    needs_shipping = serializers.BooleanField()
    ready = serializers.BooleanField()

    @staticmethod
    def of(cart: Any, *, buyer: Any, context: dict[str, Any]) -> dict[str, Any]:
        priced = services.cart_lines(cart, buyer)
        data = {
            "token": cart.token if cart is not None and cart.user_id is None else None,
            "lines": priced,
            "count": sum(row.line.quantity for row in priced),
            "subtotal": _amount(sum((row.line_total for row in priced), Decimal("0"))),
            "currency": conf.currency(),
            "needs_shipping": any(
                row.adapter.needs_shipping(row.item, row.line.options)
                for row in priced
                if row.adapter is not None and row.item is not None
            ),
            "ready": bool(priced) and not any(row.problem for row in priced),
        }
        return dict(CartSerializer(data, context=context).data)


class SetLineSerializer(serializers.Serializer[Any]):
    """What goes in the cart: a kind, an item, how many (0 takes it out), and its options."""

    kind = serializers.CharField(max_length=40)
    item = serializers.CharField(max_length=64)
    quantity = serializers.IntegerField(min_value=0)
    options = serializers.DictField(required=False, default=dict)
    add = serializers.BooleanField(
        required=False, default=False, help_text="Add to what the cart holds instead of setting it."
    )


class MergeSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(allow_blank=True, required=False, default="")


class AddressSerializer(serializers.Serializer[Any]):
    """An address as checkout takes it (stored on the order as it was typed)."""

    name = serializers.CharField(max_length=120)
    company = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=120)
    region = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    postcode = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2, min_length=2)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate_country(self, value: str) -> str:
        return value.upper()


class CheckoutSerializer(serializers.Serializer[Any]):
    """What checkout takes: who orders, where it goes, and a note. Never a price or a total."""

    email = serializers.EmailField(required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    billing = AddressSerializer()
    shipping = AddressSerializer(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class CheckoutResultSerializer(serializers.Serializer[Any]):
    """The order checkout made, its guest key, and where to pay (``null`` when nothing is due)."""

    number = serializers.IntegerField()
    key = serializers.CharField()
    url = serializers.CharField(allow_null=True)


class OrderKeySerializer(serializers.Serializer[Any]):
    number = serializers.IntegerField()
    key = serializers.CharField(required=False, allow_blank=True, default="")


class PayResultSerializer(serializers.Serializer[Any]):
    url = serializers.CharField(allow_null=True)


class RefundInputSerializer(serializers.Serializer[Any]):
    """A refund by amount, or by lines (``{line id: quantity}``), and whether the items go back."""

    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    lines = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False)
    restock = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class CancelInputSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class FulfilmentSerializer(serializers.Serializer[Any]):
    """One thing a selling app reports about an order's goods (:mod:`karni_commerce.fulfilment`)."""

    title = serializers.CharField()
    status = serializers.CharField()
    label = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField(allow_null=True)


class OrderLineViewSerializer(serializers.ModelSerializer[OrderLine]):
    """An order line as its buyer reads it, with where its item is now."""

    unit_price = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = OrderLine
        fields = [
            "id",
            "kind",
            "item",
            "name",
            "sku",
            "options",
            "quantity",
            "quantity_refunded",
            "unit_price",
            "line_total",
            "needs_shipping",
            "url",
            "image",
        ]

    def get_unit_price(self, line: OrderLine) -> str:
        return _amount(line.unit_price)

    def get_line_total(self, line: OrderLine) -> str:
        return _amount(line.line_total)

    def _item(self, line: OrderLine) -> tuple[Any, Any]:
        items: dict[tuple[str, str], Any] = self.context.get("items", {})
        adapter = services.kinds().get(line.kind)
        return adapter, items.get((line.kind, line.item))

    def get_url(self, line: OrderLine) -> str:
        adapter, item = self._item(line)
        return adapter.url(item) if adapter is not None and item is not None else ""

    def get_image(self, line: OrderLine) -> str | None:
        adapter, item = self._item(line)
        if adapter is None or item is None:
            return None
        return media_url(self.context, adapter.image(item))


class OrderViewSerializer(serializers.ModelSerializer[Order]):
    """An order as its buyer (or the guest with its key) reads it."""

    lines = serializers.SerializerMethodField()
    payable = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    amount_refunded = serializers.SerializerMethodField()
    fulfilment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "email",
            "buyer_name",
            "currency",
            "subtotal",
            "total",
            "amount_paid",
            "amount_refunded",
            "billing",
            "shipping",
            "needs_shipping",
            "note",
            "created_at",
            "paid_at",
            "cancelled_at",
            "hold_until",
            "payable",
            "lines",
            "fulfilment",
        ]

    @extend_schema_field(OrderLineViewSerializer(many=True))
    def get_lines(self, order: Order) -> list[dict[str, Any]]:
        rows = list(order.lines.order_by("position"))
        items: dict[tuple[str, str], Any] = {}
        by_kind: dict[str, list[str]] = {}
        for row in rows:
            by_kind.setdefault(row.kind, []).append(row.item)
        known = services.kinds()
        for kind, keys in by_kind.items():
            adapter = known.get(kind)
            if adapter is not None:
                items.update({(kind, key): item for key, item in adapter.get_many(keys).items()})
        context = {**self.context, "items": items}
        return list(OrderLineViewSerializer(rows, many=True, context=context).data)

    def get_payable(self, order: Order) -> bool:
        """Waiting for its payment (or failed, so it can be tried again) and still held."""
        if order.status == "failed":
            return True
        return order.status == "pending" and (
            order.hold_until is None or order.hold_until > timezone.now()
        )

    def get_subtotal(self, order: Order) -> str:
        return _amount(order.subtotal)

    def get_total(self, order: Order) -> str:
        return _amount(order.total)

    def get_amount_paid(self, order: Order) -> str:
        return _amount(order.amount_paid)

    def get_amount_refunded(self, order: Order) -> str:
        return _amount(order.amount_refunded)

    @extend_schema_field(FulfilmentSerializer(many=True))
    def get_fulfilment(self, order: Order) -> list[dict[str, Any]]:
        """What the selling apps report about the goods (``commerce.fulfilment`` hooks)."""
        from karni_commerce.fulfilment import report

        return report(order)
