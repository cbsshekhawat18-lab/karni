"""What the storefront reads and sends: the cart, checkout and an order as its customer sees it."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers

from shop import services
from shop.models import Cart, CartItem, Order, OrderItem, Product


def currency() -> str:
    return str(getattr(settings, "KARNI_PAYMENTS_CURRENCY", "usd")).upper()


def image_url(context: dict[str, Any], image: Any) -> str | None:
    if not image:
        return None
    request = context.get("request")
    return (
        request.build_absolute_uri(image.url) if request is not None else str(image.url)
    )


class ProductCardSerializer(serializers.ModelSerializer[Product]):
    """A product as a cart line shows it."""

    image = serializers.SerializerMethodField()
    current_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "sku",
            "image",
            "price",
            "current_price",
            "available",
        ]

    def get_image(self, product: Product) -> str | None:
        return image_url(self.context, product.image)


class CartLineSerializer(serializers.ModelSerializer[CartItem]):
    product = ProductCardSerializer(read_only=True)
    unit_price = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()
    problem = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "unit_price", "line_total", "problem"]

    def get_unit_price(self, line: CartItem) -> str:
        return f"{line.product.current_price():.2f}"

    def get_line_total(self, line: CartItem) -> str:
        return f"{line.product.current_price() * line.quantity:.2f}"

    def get_problem(self, line: CartItem) -> str | None:
        return self.context.get("problems", {}).get(str(line.pk))


class CartSerializer(serializers.Serializer[Cart | None]):
    """The cart: its lines, what stops each one, the count and the subtotal."""

    token = serializers.CharField(allow_null=True)
    lines = CartLineSerializer(many=True)
    count = serializers.IntegerField()
    subtotal = serializers.CharField()
    currency = serializers.CharField()
    ready = serializers.BooleanField()

    @staticmethod
    def of(cart: Cart | None, *, context: dict[str, Any]) -> dict[str, Any]:
        lines = cart.lines() if cart is not None else []
        problems = services.cart_problems(lines)
        data = {
            "token": cart.token
            if cart is not None and cart.customer_id is None
            else None,
            "lines": lines,
            "count": sum(line.quantity for line in lines),
            "subtotal": f"{services.cart_total(lines):.2f}",
            "currency": currency(),
            "ready": bool(lines) and not problems,
        }
        return CartSerializer(data, context={**context, "problems": problems}).data


class SetQuantitySerializer(serializers.Serializer[Any]):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=0, max_value=services.MAX_QUANTITY)


class MergeSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(allow_blank=True, required=False, default="")


class AddressInputSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    company = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default=""
    )
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    city = serializers.CharField(max_length=120)
    region = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default=""
    )
    postcode = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2, min_length=2)
    phone = serializers.CharField(
        max_length=40, required=False, allow_blank=True, default=""
    )

    def validate_country(self, value: str) -> str:
        return value.upper()


class CheckoutSerializer(serializers.Serializer[Any]):
    """What checkout takes: who orders, where it goes, and a note. Never a price or a total."""

    email = serializers.EmailField(required=False, allow_blank=True, default="")
    billing = AddressInputSerializer()
    shipping = AddressInputSerializer(required=False, allow_null=True, default=None)
    note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000
    )
    save_address = serializers.BooleanField(required=False, default=False)


class CheckoutResultSerializer(serializers.Serializer[Any]):
    number = serializers.IntegerField()
    key = serializers.CharField()
    url = serializers.CharField()


class OrderLineSerializer(serializers.ModelSerializer[OrderItem]):
    slug = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "name",
            "sku",
            "quantity",
            "unit_price",
            "line_total",
            "slug",
            "image",
        ]

    def get_slug(self, line: OrderItem) -> str | None:
        return line.product.slug if line.product is not None else None

    def get_image(self, line: OrderItem) -> str | None:
        return image_url(self.context, line.product.image if line.product else None)


class OrderViewSerializer(serializers.ModelSerializer[Order]):
    """An order as its customer (or the guest with its key) sees it."""

    lines = serializers.SerializerMethodField()
    payable = serializers.BooleanField(read_only=True)
    currency = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "email",
            "subtotal",
            "total",
            "currency",
            "billing",
            "shipping",
            "note",
            "created_at",
            "paid_at",
            "reserved_until",
            "payable",
            "lines",
        ]

    def get_lines(self, order: Order) -> list[dict[str, Any]]:
        return list(
            OrderLineSerializer(order.lines(), many=True, context=self.context).data
        )

    def get_currency(self, order: Order) -> str:
        return currency()


class PayResultSerializer(serializers.Serializer[Any]):
    url = serializers.CharField()
