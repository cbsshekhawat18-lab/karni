"""The commerce API: the shopper's cart and checkout, and the orders. Auto-registered.

Shoppers (visitors included, each check below):

* ``GET carts/current/``: the signed-in person's cart, or the visitor's cart
  its ``X-Cart-Token`` header names.
* ``POST carts/current/lines/``: ``{kind, item, quantity, options, add}`` puts
  an item in the cart (0 takes it out). A visitor's first line starts their
  cart, and the answer carries its token.
* ``POST carts/current/merge/``: after sign-in, ``{token}`` joins the
  visitor's cart to the person's.
* ``POST carts/current/coupon/``: ``{code}`` puts a coupon on the cart (blank
  takes it off). The cart answers with the discount.
* ``POST carts/current/quote/``: ``{address, shipping_method, email}`` answers
  what the cart comes to there: the ways to send it, the tax and the total.
* ``POST carts/current/checkout/``: the cart becomes an order waiting for its
  payment (with the cart's coupon and the ``shipping_method`` chosen), and the
  answer says where to pay.
* ``GET orders/lookup/?number=&key=``: one order, for its buyer, the guest
  with its key, or staff.
* ``POST orders/pay/``: ``{number, key}`` starts the payment of an order that
  waits for it, or failed.

The lists and details read the roles' grants, and a person always reads
their own orders (``Owned("user")``). Orders change only through these
actions and :mod:`karni_commerce.services`: the standard writes answer 405.
Staff with ``karni_commerce.order:change`` cancel an order, and staff who may
also add a refund (``karni_commerce.orderrefund:add``) refund one.

Staff (``karni_commerce.order:view``, the rows their grants give):

* ``GET orders/{id}/staff/``: the order with every note, its payments and
  refunds, the buyer and what may be done with it now.
* ``POST orders/{id}/notes/``: ``{body, kind}`` writes a note (``order:change``).
  A note to the customer is emailed to them.
* ``POST orders/manual/``: an order placed by hand for a buyer (``order:add``),
  waiting for their payment, with the link emailed to them.
* ``GET orders/items/?kind=&search=``: what may go on such an order.
* ``GET orders/customers/?search=&ordering=``: the buyers, one row per email,
  and ``GET orders/customer/?email=``: one buyer's page
  (:mod:`karni_commerce.customers`, a seam ``karni.people`` replaces).

Coupons, shipping zones and methods and tax rates (``coupons/``,
``shipping-zones/``, ``shipping-methods/``, ``tax-rates/``) are read and
changed by the roles' grants, and the uses of coupons (``coupon-uses/``) read.

Override / escape hatch: subclass a viewset, set ``auto_register = False`` on
this one, and register yours. ``TOKEN_HEADER`` names the cart header.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from karni.api import Access, Authenticated, BaseViewSet, Budget, Can, Granted, Owned, Public
from rest_framework.decorators import action
from rest_framework.exceptions import (
    MethodNotAllowed,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.request import Request
from rest_framework.response import Response

from karni_commerce import services
from karni_commerce.api import (
    CancelInputSerializer,
    CartSerializer,
    CheckoutResultSerializer,
    CheckoutSerializer,
    CouponInputSerializer,
    CustomerPageSerializer,
    CustomerRowSerializer,
    ItemSerializer,
    ManualOrderSerializer,
    ManualResultSerializer,
    MergeSerializer,
    NoteInputSerializer,
    OrderKeySerializer,
    OrderStaffSerializer,
    OrderViewSerializer,
    PayResultSerializer,
    QuoteInputSerializer,
    QuoteSerializer,
    RefundInputSerializer,
    SetLineSerializer,
)
from karni_commerce.customers import customers_backend
from karni_commerce.models import (
    Cart,
    CartLine,
    Coupon,
    CouponUse,
    Order,
    OrderLine,
    OrderPayment,
    OrderRefund,
    ShippingMethod,
    ShippingZone,
    TaxRate,
)
from karni_commerce.sellables import kinds

__all__ = [
    "TOKEN_HEADER",
    "CartLineViewSet",
    "CartViewSet",
    "CouponUseViewSet",
    "CouponViewSet",
    "OrderLineViewSet",
    "OrderPaymentViewSet",
    "OrderRefundViewSet",
    "OrderViewSet",
    "ShippingMethodViewSet",
    "ShippingZoneViewSet",
    "TaxRateViewSet",
]

TOKEN_HEADER = "X-Cart-Token"


class _ReadOnly:
    """The standard writes answer 405: these rows change only through the actions."""

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "POST")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT")

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PATCH")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "DELETE")


def _buyer(request: Request) -> Any:
    return request.user if request.user.is_authenticated else None


class CartViewSet(_ReadOnly, BaseViewSet):
    """Carts. Staff read them by their grants. Every shopper uses their own through ``current``."""

    model = Cart
    access = Access(read=Granted(), write=Granted())
    query_budget = Budget(
        checkout=90,
        merge=60,
        set_line=40,
        current=40,
        coupon=40,
        quote=40,
        reason="checkout writes the order, each line and its hold, and merging moves each "
        "line: a few queries per line, measured with 10 lines",
    )

    def _current(self, request: Request, *, create: bool = False) -> Cart | None:
        return services.find_cart(request.user, request.headers.get(TOKEN_HEADER), create=create)

    def _cart(self, request: Request, cart: Cart | None) -> Response:
        return Response(
            CartSerializer.of(cart, buyer=_buyer(request), context={"request": request})
        )

    @extend_schema(responses=CartSerializer)
    @action(detail=False, methods=["get"], url_path="current", access=Public())
    def current(self, request: Request) -> Response:
        """The shopper's cart (empty when they have none yet)."""
        return self._cart(request, self._current(request))

    @extend_schema(request=SetLineSerializer, responses=CartSerializer)
    @action(detail=False, methods=["post"], url_path="current/lines", access=Public())
    def set_line(self, request: Request) -> Response:
        """Put ``quantity`` of an item in the cart (``add``: on top of it; 0 removes it)."""
        body = SetLineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        cart = self._current(request, create=True)
        assert cart is not None
        services.set_line(
            cart,
            data["kind"],
            data["item"],
            data["quantity"],
            data["options"],
            buyer=_buyer(request),
            add=data["add"],
        )
        return self._cart(request, cart)

    @extend_schema(request=MergeSerializer, responses=CartSerializer)
    @action(detail=False, methods=["post"], url_path="current/merge", access=Authenticated())
    def merge(self, request: Request) -> Response:
        """The visitor's cart (by its token) joins the signed-in person's cart."""
        body = MergeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._cart(request, services.merge(request.user, body.validated_data["token"]))

    @extend_schema(request=CouponInputSerializer, responses=CartSerializer)
    @action(detail=False, methods=["post"], url_path="current/coupon", access=Public())
    def coupon(self, request: Request) -> Response:
        """Put a coupon on the cart, or take it off with a blank code."""
        body = CouponInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        cart = self._current(request, create=True)
        assert cart is not None
        user = _buyer(request)
        services.apply_coupon(
            cart,
            body.validated_data["code"],
            buyer=user,
            email=user.email if user is not None else "",
        )
        return self._cart(request, cart)

    @extend_schema(request=QuoteInputSerializer, responses=QuoteSerializer)
    @action(detail=False, methods=["post"], url_path="current/quote", access=Public())
    def quote(self, request: Request) -> Response:
        """What the cart comes to at an address: the ways to send it, the tax and the total."""
        body = QuoteInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        user = _buyer(request)
        found = services.quote_cart(
            self._current(request),
            buyer=user,
            email=(user.email if user is not None else "") or data["email"],
            address=dict(data["address"]),
            method=data["shipping_method"] or None,
        )
        return Response(QuoteSerializer.of(found))

    @extend_schema(request=CheckoutSerializer, responses={201: CheckoutResultSerializer})
    @action(detail=False, methods=["post"], url_path="current/checkout", access=Public())
    def checkout(self, request: Request) -> Response:
        """The cart becomes an order, its items are held, and its payment starts."""
        body = CheckoutSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        user = _buyer(request)
        email = (user.email if user is not None else "") or data["email"]
        name = data["name"] or (user.get_full_name() if user is not None else "")
        cart = self._current(request)
        if cart is None:
            raise ValidationError({"cart": ["The cart is empty."]})
        billing = dict(data["billing"])
        shipping = dict(data["shipping"] or billing)
        order = services.checkout(
            cart,
            user=user,
            email=email,
            name=name or billing.get("name", ""),
            billing=billing,
            shipping=shipping,
            note=data["note"],
            method=data["shipping_method"] or None,
        )
        url = services.open_payment(order)
        result = {"number": order.number, "key": order.key, "url": url}
        return Response(CheckoutResultSerializer(result).data, status=201)


class CartLineViewSet(_ReadOnly, BaseViewSet):
    """Cart lines, for staff by their grants (abandoned carts)."""

    model = CartLine
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["cart", "kind"]


class OrderViewSet(_ReadOnly, BaseViewSet):
    """Orders. A person reads their own, staff by their grants, a guest the one with its key."""

    model = Order
    access = Access(read=Owned("user") | Granted(), write=Granted())
    query_budget = Budget(
        cancel=40,
        refund=40,
        pay=25,
        manual=80,
        staff=30,
        notes=20,
        reason="cancelling, refunding and placing an order run each line's adapter and the "
        "selling apps' listeners (a parcel cancelled, stock back on the shelf, each line "
        "held): a few queries per line, and each move of the order is in its history. The "
        "staff view reads the payments, refunds, notes and the buyer's totals: one query each",
    )
    filterset_fields = {
        "status": ["exact", "in"],
        "currency": ["exact"],
        "email": ["exact", "iexact"],
        "user": ["exact"],
        "needs_shipping": ["exact"],
        "created_at": ["gte", "lte"],
        "paid_at": ["gte", "lte"],
    }
    search_fields = ["reference", "email", "buyer_name"]
    ordering_fields = ["number", "created_at", "total", "status", "paid_at"]

    def get_queryset(self) -> QuerySet[Order]:
        """``?mine=true`` narrows the list to the signed-in person's own orders."""
        queryset: QuerySet[Order] = super().get_queryset()
        mine = str(self.request.query_params.get("mine", "")).lower() in ("1", "true")
        if mine:
            user = self.request.user
            queryset = queryset.filter(user=user) if user.is_authenticated else queryset.none()
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("mine", bool, description="Only the signed-in person's orders.")
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _find(self, request: Request, number: Any, key: str) -> Order:
        order = Order.objects.filter(number=number).first()
        user = request.user
        if order is None:
            raise NotFound("No such order.")
        mine = user.is_authenticated and order.user_id == user.pk
        staff = user.is_authenticated and user.can("karni_commerce.order:view")
        if not (mine or order.guest_may_read(key) or (staff and self._staff_reads(request, order))):
            raise NotFound("No such order.")
        return order

    def _staff_reads(self, request: Request, order: Order) -> bool:
        readable: QuerySet[Order] = self.get_queryset()
        return readable.filter(pk=order.pk).exists()

    @extend_schema(
        parameters=[
            OpenApiParameter("number", int, required=True),
            OpenApiParameter("key", str, description="The guest's key, from checkout."),
        ],
        responses=OrderViewSerializer,
    )
    @action(detail=False, methods=["get"], url_path="lookup", access=Public())
    def lookup(self, request: Request) -> Response:
        """One order with its lines and addresses, for its buyer or the guest with its key."""
        body = OrderKeySerializer(data=request.query_params)
        body.is_valid(raise_exception=True)
        order = self._find(request, body.validated_data["number"], body.validated_data["key"])
        return Response(OrderViewSerializer(order, context={"request": request}).data)

    @extend_schema(request=OrderKeySerializer, responses=PayResultSerializer)
    @action(detail=False, methods=["post"], url_path="pay", access=Public())
    def pay(self, request: Request) -> Response:
        """Start the payment again for an order that waits for it (or whose payment failed)."""
        body = OrderKeySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = self._find(request, body.validated_data["number"], body.validated_data["key"])
        return Response(PayResultSerializer({"url": services.open_payment(order)}).data)

    @extend_schema(request=CancelInputSerializer, responses=OrderViewSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
        access=Can("karni_commerce.order:change"),
    )
    def cancel(self, request: Request, pk: Any = None) -> Response:
        """Cancel the order: its items are let go, and what was paid goes back."""
        body = CancelInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.cancel(self.get_object(), body.validated_data["reason"])
        return Response(OrderViewSerializer(order, context={"request": request}).data)

    @extend_schema(request=RefundInputSerializer, responses=OrderViewSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="refund",
        access=Can("karni_commerce.order:change"),
    )
    def refund(self, request: Request, pk: Any = None) -> Response:
        """Refund an amount or lines through the payment, with the items back when asked."""
        body = RefundInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = self.get_object()
        if not request.user.can("karni_commerce.orderrefund:add"):
            raise PermissionDenied("Refunds need karni_commerce.orderrefund:add.")
        services.refund(
            order,
            amount=data["amount"],
            lines=data.get("lines") or None,
            restock=data["restock"],
            reason=data["reason"],
        )
        order.refresh_from_db()
        return Response(OrderViewSerializer(order, context={"request": request}).data)

    # -- staff ----------------------------------------------------------------------------

    def _staff_view(self, request: Request, order: Order) -> Response:
        context = {"request": request, "orders": self.get_queryset()}
        return Response(OrderStaffSerializer(order, context=context).data)

    @extend_schema(responses=OrderStaffSerializer)
    @action(
        detail=True,
        methods=["get"],
        url_path="staff",
        access=Can("karni_commerce.order:view"),
    )
    def staff(self, request: Request, pk: Any = None) -> Response:
        """The order as staff read it: notes, payments, refunds, the buyer, the moves left."""
        return self._staff_view(request, self.get_object())

    @extend_schema(request=NoteInputSerializer, responses=OrderStaffSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="notes",
        access=Can("karni_commerce.order:change"),
    )
    def notes(self, request: Request, pk: Any = None) -> Response:
        """Write a note: for the staff, or to the customer (who gets it by email too)."""
        body = NoteInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = self.get_object()
        services.add_note(
            order,
            body.validated_data["body"],
            kind=body.validated_data["kind"],
            author=request.user,
        )
        return self._staff_view(request, order)

    @extend_schema(request=ManualOrderSerializer, responses={201: ManualResultSerializer})
    @action(
        detail=False,
        methods=["post"],
        url_path="manual",
        access=Can("karni_commerce.order:add"),
    )
    def manual(self, request: Request) -> Response:
        """Place an order for a buyer by hand (a phone order). It waits for their payment."""
        body = ManualOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        billing = dict(data["billing"])
        order = services.place_manual_order(
            [
                (line["kind"], line["item"], line["quantity"], line["options"])
                for line in data["lines"]
            ],
            staff=request.user,
            email=data["email"],
            name=data["name"] or billing.get("name", ""),
            billing=billing,
            shipping=dict(data["shipping"] or billing),
            note=data["note"],
            send_link=data["send_link"],
            coupon=data["coupon"],
            method=data["shipping_method"] or None,
        )
        result = {"id": str(order.pk), "number": order.number, "link": services.order_link(order)}
        return Response(ManualResultSerializer(result).data, status=201)

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, description="One kind (blank: every kind)."),
            OpenApiParameter("search", str, description="Text in the item's search fields."),
        ],
        responses=ItemSerializer(many=True),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="items",
        access=Can("karni_commerce.order:add"),
    )
    def items(self, request: Request) -> Response:
        """What staff may put on an order placed by hand: at most 20 rows, priced today.

        An item sold with options (sizes) gives a row per choice (``Sellable.choices``).
        """
        wanted = str(request.query_params.get("kind", "") or "")
        text = str(request.query_params.get("search", "") or "")
        found: list[dict[str, Any]] = []
        for kind, adapter in sorted(kinds().items()):
            if wanted and kind != wanted:
                continue
            for item in adapter.search(text)[: 20 - len(found)]:
                for options in adapter.choices(item):
                    price = adapter.price(item, options, None)
                    found.append(
                        {
                            "kind": kind,
                            "item": adapter.key(item),
                            "options": options,
                            "name": adapter.name(item, options),
                            "sku": adapter.sku(item, options),
                            "price": f"{services.money(price.unit):.2f}",
                            "available": adapter.available(item, options),
                        }
                    )
            if len(found) >= 20:
                found = found[:20]
                break
        return Response(ItemSerializer(found, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Text in the email, name or number."),
            OpenApiParameter(
                "ordering",
                str,
                description="last_order, first_order, orders, spent, email or name (- first: "
                "the other way).",
            ),
        ],
        responses=CustomerRowSerializer(many=True),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="customers",
        access=Can("karni_commerce.order:view"),
    )
    def customers(self, request: Request) -> Response:
        """The buyers of the orders the caller may read: one row per email, paged."""
        rows = customers_backend().customers(
            self.get_queryset(),
            search=str(request.query_params.get("search", "") or ""),
            ordering=str(request.query_params.get("ordering", "") or "-last_order"),
        )
        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(CustomerRowSerializer(page, many=True).data)
        return Response(CustomerRowSerializer(rows, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("email", str, required=True)],
        responses=CustomerPageSerializer,
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="customer",
        access=Can("karni_commerce.order:view"),
    )
    def customer(self, request: Request) -> Response:
        """One buyer: their orders, what they spent, their addresses and their account."""
        email = str(request.query_params.get("email", "") or "")
        found = customers_backend().customer(self.get_queryset(), email) if email else None
        if found is None:
            raise NotFound("No customer with that email.")
        return Response(CustomerPageSerializer(found).data)


class OrderLineViewSet(_ReadOnly, BaseViewSet):
    """Order lines: a person reads the lines of their own orders, staff by their grants."""

    model = OrderLine
    access = Access(read=Owned("order__user") | Granted(), write=Granted())
    filterset_fields = ["order", "kind", "item"]


class OrderPaymentViewSet(_ReadOnly, BaseViewSet):
    """Which payments belong to which order, for staff by their grants."""

    model = OrderPayment
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["order", "purpose"]


class OrderRefundViewSet(_ReadOnly, BaseViewSet):
    """An order's refunds, for staff by their grants."""

    model = OrderRefund
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["order", "restock"]


class CouponViewSet(BaseViewSet):
    """Coupons, read and changed by the roles' grants (``karni_commerce.coupon:*``)."""

    model = Coupon
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["kind", "active"]
    search_fields = ["code", "description"]
    ordering_fields = ["code", "ends_at", "created_at"]


class CouponUseViewSet(_ReadOnly, BaseViewSet):
    """The uses of coupons: which order took how much off. Read by the roles' grants."""

    model = CouponUse
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["coupon", "order"]


class ShippingZoneViewSet(BaseViewSet):
    """Shipping zones, by the roles' grants. Checkout reads them through the quote."""

    model = ShippingZone
    access = Access(read=Granted(), write=Granted())
    search_fields = ["name", "countries"]


class ShippingMethodViewSet(BaseViewSet):
    """The shipping methods of the zones, by the roles' grants."""

    model = ShippingMethod
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["zone", "kind", "active"]


class TaxRateViewSet(BaseViewSet):
    """Tax rates, by the roles' grants. Checkout reads them through the quote."""

    model = TaxRate
    access = Access(read=Granted(), write=Granted())
    filterset_fields = ["country", "tax_class"]
    search_fields = ["name", "country", "region"]
