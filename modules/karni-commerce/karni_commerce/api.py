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
from karni_commerce.models import Order, OrderLine, OrderNote
from karni_commerce.services import PricedLine

__all__ = [
    "AddressSerializer",
    "CouponInputSerializer",
    "QuoteInputSerializer",
    "QuoteSerializer",
    "CustomerPageSerializer",
    "CustomerRowSerializer",
    "ItemSerializer",
    "ManualOrderSerializer",
    "ManualQuoteSerializer",
    "ManualResultSerializer",
    "NoteInputSerializer",
    "OrderStaffSerializer",
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
    details = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
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
            "details": list(instance.details),
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
    coupon = serializers.CharField(allow_null=True, help_text="The coupon applied, or null.")
    coupon_description = serializers.CharField(allow_blank=True)
    coupon_problem = serializers.CharField(
        allow_blank=True, help_text="Why the coupon on the cart takes nothing off now."
    )
    discount = serializers.CharField()

    @staticmethod
    def of(cart: Any, *, buyer: Any, context: dict[str, Any]) -> dict[str, Any]:
        priced = services.cart_lines(cart, buyer)
        quoted = services.quote_cart(cart, buyer=buyer) if cart is not None else None
        applied = cart.coupon if cart is not None else None
        data = {
            "token": cart.token if cart is not None and cart.user_id is None else None,
            "lines": priced,
            "count": sum(row.line.quantity for row in priced),
            "coupon": applied.code if applied is not None else None,
            "coupon_description": applied.description if applied is not None else "",
            "coupon_problem": quoted.coupon_problem if quoted is not None else "",
            "discount": _amount(quoted.discount if quoted is not None else 0),
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


class CouponInputSerializer(serializers.Serializer[Any]):
    """A coupon code to put on the cart (blank takes the coupon off)."""

    code = serializers.CharField(max_length=40, allow_blank=True)


class PlaceSerializer(serializers.Serializer[Any]):
    """Where an order goes, as much as the shipping and the tax need: a country, at least."""

    country = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    region = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    postcode = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")

    def validate_country(self, value: str) -> str:
        return value.upper()


class QuoteInputSerializer(serializers.Serializer[Any]):
    """What the checkout page asks a quote for: the address, the method, the email."""

    address = PlaceSerializer(required=False, default=dict)
    shipping_method = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class MethodSerializer(serializers.Serializer[Any]):
    id = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField()
    cost = serializers.CharField()


class TaxLineSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    rate = serializers.CharField()
    amount = serializers.CharField()


class QuoteSerializer(serializers.Serializer[Any]):
    """What the cart comes to for an address: the coupon, the ways to send it, the tax."""

    currency = serializers.CharField()
    subtotal = serializers.CharField()
    discount = serializers.CharField()
    shipping = serializers.CharField()
    tax = serializers.CharField()
    total = serializers.CharField()
    prices_include_tax = serializers.BooleanField()
    needs_shipping = serializers.BooleanField()
    coupon = serializers.CharField(allow_null=True)
    coupon_problem = serializers.CharField(allow_blank=True)
    methods = MethodSerializer(many=True)
    method = serializers.CharField(allow_null=True)
    shipping_problem = serializers.CharField(allow_blank=True)
    tax_lines = TaxLineSerializer(many=True)

    @staticmethod
    def of(found: Any) -> dict[str, Any]:
        return dict(
            QuoteSerializer(
                {
                    "currency": found.currency,
                    "subtotal": _amount(found.subtotal),
                    "discount": _amount(found.discount),
                    "shipping": _amount(found.shipping),
                    "tax": _amount(found.tax),
                    "total": _amount(found.total),
                    "prices_include_tax": found.prices_include_tax,
                    "needs_shipping": found.needs_shipping,
                    "coupon": found.coupon.code if found.coupon is not None else None,
                    "coupon_problem": found.coupon_problem,
                    "methods": [
                        {"id": m.id, "name": m.name, "kind": m.kind, "cost": _amount(m.cost)}
                        for m in found.methods
                    ],
                    "method": found.method.id if found.method is not None else None,
                    "shipping_problem": found.shipping_problem,
                    "tax_lines": [
                        {
                            "name": t.name,
                            "rate": f"{t.rate.normalize():f}",
                            "amount": _amount(t.amount),
                        }
                        for t in found.tax_lines
                    ],
                }
            ).data
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
    shipping_method = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="The id of the method chosen."
    )


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


def person_name(user: Any) -> str:
    """A user as staff read them: their full name, else their email."""
    if user is None:
        return ""
    full = str(getattr(user, "get_full_name", lambda: "")() or "").strip()
    return full or str(getattr(user, "email", "") or "")


class NoteSerializer(serializers.ModelSerializer[OrderNote]):
    """A note on an order, with who wrote it (by name)."""

    author_name = serializers.SerializerMethodField()

    class Meta:
        model = OrderNote
        fields = ["id", "kind", "body", "author_name", "created_at"]

    def get_author_name(self, note: OrderNote) -> str:
        return person_name(note.author)


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
    discount = serializers.SerializerMethodField()
    tax = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    details = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
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
            "details",
            "quantity",
            "quantity_refunded",
            "unit_price",
            "line_total",
            "discount",
            "tax",
            "total",
            "needs_shipping",
            "url",
            "image",
        ]

    def get_unit_price(self, line: OrderLine) -> str:
        return _amount(line.unit_price)

    def get_line_total(self, line: OrderLine) -> str:
        return _amount(line.line_total)

    def get_discount(self, line: OrderLine) -> str:
        return _amount(line.discount)

    def get_tax(self, line: OrderLine) -> str:
        return _amount(line.tax)

    def get_total(self, line: OrderLine) -> str:
        return _amount(line.paid_total)

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
    notes = serializers.SerializerMethodField()
    payable = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    discount_total = serializers.SerializerMethodField()
    shipping_total = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    tax_lines = TaxLineSerializer(many=True)
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
            "discount_total",
            "shipping_total",
            "tax_total",
            "tax_lines",
            "total",
            "prices_include_tax",
            "coupon_code",
            "shipping_method",
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
            "notes",
            "fulfilment",
        ]

    #: The notes the reader may see: the notes to the customer (staff see every note).
    note_kinds: tuple[str, ...] = ("customer",)

    @extend_schema_field(NoteSerializer(many=True))
    def get_notes(self, order: Order) -> list[dict[str, Any]]:
        rows = order.notes.filter(kind__in=self.note_kinds).select_related("author")
        return list(NoteSerializer(rows, many=True).data)

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

    def get_discount_total(self, order: Order) -> str:
        return _amount(order.discount_total)

    def get_shipping_total(self, order: Order) -> str:
        return _amount(order.shipping_total)

    def get_tax_total(self, order: Order) -> str:
        return _amount(order.tax_total)

    def get_amount_paid(self, order: Order) -> str:
        return _amount(order.amount_paid)

    def get_amount_refunded(self, order: Order) -> str:
        return _amount(order.amount_refunded)

    @extend_schema_field(FulfilmentSerializer(many=True))
    def get_fulfilment(self, order: Order) -> list[dict[str, Any]]:
        """What the selling apps report about the goods (``commerce.fulfilment`` hooks)."""
        from karni_commerce.fulfilment import report

        return report(order)


class NoteInputSerializer(serializers.Serializer[Any]):
    """A note to write: ``internal`` (staff only) or ``customer`` (the buyer gets it too)."""

    body = serializers.CharField(max_length=5000)
    kind = serializers.ChoiceField(choices=OrderNote.Kind.choices, default=OrderNote.Kind.INTERNAL)


class PaymentRowSerializer(serializers.Serializer[Any]):
    """One payment of an order, as staff read it."""

    id = serializers.CharField()
    purpose = serializers.CharField()
    amount = serializers.CharField()
    status = serializers.CharField()
    provider = serializers.CharField()
    created_at = serializers.DateTimeField()


class RefundRowSerializer(serializers.Serializer[Any]):
    """One refund of an order: how much, of which lines, and where it stands."""

    id = serializers.CharField()
    amount = serializers.CharField()
    lines = serializers.DictField(child=serializers.IntegerField())
    restock = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    settled_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class BuyerSerializer(serializers.Serializer[Any]):
    """Who bought: the account (when there is one) and what they bought so far."""

    user = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_blank=True)
    email = serializers.CharField()
    orders = serializers.IntegerField()
    spent = serializers.CharField()


class OrderStaffSerializer(OrderViewSerializer):
    """An order as staff read it: the buyer's view, every note, the payments and refunds,
    the buyer, and what may be done with it now."""

    payments = serializers.SerializerMethodField()
    refunds = serializers.SerializerMethodField()
    buyer = serializers.SerializerMethodField()
    refundable = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_refund = serializers.SerializerMethodField()

    class Meta(OrderViewSerializer.Meta):
        fields = [
            *OrderViewSerializer.Meta.fields,
            "payments",
            "refunds",
            "buyer",
            "refundable",
            "can_cancel",
            "can_refund",
        ]

    note_kinds: tuple[str, ...] = ("internal", "customer")

    @extend_schema_field(PaymentRowSerializer(many=True))
    def get_payments(self, order: Order) -> list[dict[str, Any]]:
        rows = order.payments.select_related("payment").order_by("created_at")
        return [
            {
                "id": str(row.pk),
                "purpose": row.purpose,
                "amount": _amount(row.amount),
                "status": str(row.payment.status),
                "provider": str(row.payment.provider),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @extend_schema_field(RefundRowSerializer(many=True))
    def get_refunds(self, order: Order) -> list[dict[str, Any]]:
        rows = order.refunds.select_related("refund").order_by("created_at")
        return [
            {
                "id": str(row.pk),
                "amount": _amount(row.amount),
                "lines": row.line_quantities(),
                "restock": row.restock,
                "reason": row.reason,
                "status": str(row.refund.status),
                "settled_at": row.settled_at,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @extend_schema_field(BuyerSerializer)
    def get_buyer(self, order: Order) -> dict[str, Any]:
        from karni_commerce.customers import customers_backend

        readable = self.context.get("orders")
        rows = readable if readable is not None else Order.objects.all()
        summary = (
            customers_backend().customers(rows.filter(email__iexact=order.email)).first() or {}
        )
        return {
            "user": str(order.user_id) if order.user_id else None,
            "name": person_name(order.user) or order.buyer_name,
            "email": order.email,
            "orders": int(summary.get("order_count") or 0),
            "spent": _amount(summary.get("spent") or 0),
        }

    def get_refundable(self, order: Order) -> str:
        return _amount(order.refundable)

    def get_can_cancel(self, order: Order) -> bool:
        return order.status in ("pending", "failed", "paid")

    def get_can_refund(self, order: Order) -> bool:
        return order.status in services.PAID_STATES and order.refundable > 0


class ManualLineSerializer(serializers.Serializer[Any]):
    kind = serializers.CharField(max_length=40)
    item = serializers.CharField(max_length=64)
    quantity = serializers.IntegerField(min_value=1)
    options = serializers.DictField(required=False, default=dict)


class ManualOrderSerializer(serializers.Serializer[Any]):
    """An order staff place for a buyer (a phone order). Never a price: the server prices it."""

    email = serializers.EmailField()
    name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    billing = AddressSerializer()
    shipping = AddressSerializer(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    lines = ManualLineSerializer(many=True, allow_empty=False)
    coupon = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    shipping_method = serializers.CharField(required=False, allow_blank=True, default="")
    send_link = serializers.BooleanField(
        required=False, default=True, help_text="Email the buyer the link to pay."
    )


class ManualQuoteSerializer(serializers.Serializer[Any]):
    """An order staff are about to place by hand, to price before they place it."""

    email = serializers.EmailField(required=False, allow_blank=True, default="")
    billing = PlaceSerializer(required=False, allow_null=True, default=None)
    shipping = PlaceSerializer(required=False, allow_null=True, default=None)
    lines = ManualLineSerializer(many=True, allow_empty=False)
    coupon = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    shipping_method = serializers.CharField(required=False, allow_blank=True, default="")


class ManualResultSerializer(serializers.Serializer[Any]):
    """The order placed by hand, and the link the buyer pays it at."""

    id = serializers.CharField()
    number = serializers.IntegerField()
    link = serializers.CharField()


class ItemSerializer(serializers.Serializer[Any]):
    """Something for sale, as staff pick it for an order placed by hand."""

    kind = serializers.CharField()
    item = serializers.CharField()
    options = serializers.DictField()
    name = serializers.CharField()
    sku = serializers.CharField(allow_blank=True)
    price = serializers.CharField()
    available = serializers.IntegerField(allow_null=True)


class CustomerRowSerializer(serializers.Serializer[Any]):
    """A buyer in the staff's customers list."""

    email = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    has_account = serializers.BooleanField()
    order_count = serializers.IntegerField()
    spent = serializers.CharField()
    currency = serializers.CharField()
    first_order = serializers.DateTimeField()
    last_order = serializers.DateTimeField()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        row = dict(instance)
        return {
            "email": row["email"],
            "name": row.get("name") or "",
            "has_account": bool(row.get("has_account")),
            "order_count": int(row.get("order_count") or 0),
            "spent": _amount(row.get("spent") or 0),
            "currency": conf.currency(),
            "first_order": serializers.DateTimeField().to_representation(row["first_order"]),
            "last_order": serializers.DateTimeField().to_representation(row["last_order"]),
        }


class CustomerOrderSerializer(serializers.Serializer[Any]):
    id = serializers.CharField()
    number = serializers.IntegerField()
    status = serializers.CharField()
    total = serializers.CharField()
    created_at = serializers.DateTimeField()


class CustomerPageSerializer(serializers.Serializer[Any]):
    """One buyer: their orders, what they spent, their addresses and their account."""

    email = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    account = serializers.DictField(allow_null=True)
    order_count = serializers.IntegerField()
    spent = serializers.CharField()
    currency = serializers.CharField()
    first_order = serializers.DateTimeField()
    last_order = serializers.DateTimeField()
    addresses = serializers.ListField(child=serializers.DictField())
    orders = CustomerOrderSerializer(many=True)

    def to_representation(self, instance: Any) -> dict[str, Any]:
        stamp = serializers.DateTimeField()
        account = instance.account
        return {
            "email": instance.email,
            "name": person_name(account) or instance.name,
            "account": None
            if account is None
            else {
                "id": str(account.pk),
                "name": person_name(account),
                "email": str(account.email),
                "joined": stamp.to_representation(getattr(account, "date_joined", None))
                if getattr(account, "date_joined", None)
                else None,
            },
            "order_count": instance.order_count,
            "spent": _amount(instance.spent),
            "currency": instance.currency,
            "first_order": stamp.to_representation(instance.first_order),
            "last_order": stamp.to_representation(instance.last_order),
            "addresses": instance.addresses,
            "orders": [
                {
                    "id": str(order.pk),
                    "number": order.number,
                    "status": order.status,
                    "total": _amount(order.total),
                    "created_at": stamp.to_representation(order.created_at),
                }
                for order in instance.orders
            ],
        }
