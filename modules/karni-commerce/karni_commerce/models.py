"""The cart, the order and how its payments and refunds link to it.

A cart line and an order line name what they sell by ``kind`` (a registered
:class:`~karni_commerce.sellables.Sellable`) and ``item`` (that kind's key,
as text), never by a foreign key: commerce does not know the selling app's
models, and an order line keeps its copied name, SKU and prices when the
item is gone.

An order's ``status`` is its money state only: ``pending`` (waiting for its
payment), ``paid``, ``part_paid``, ``failed``, ``cancelled``, ``refunded``
and ``part_refunded``. What happens to the goods (shipped, checked in,
enrolled) is the selling app's own record.

Override / escape hatch: these are plain :class:`karni.models.BaseModel`
models, extended by your own tables that point at them (a shipment, an
invoice). ``APIMeta`` keeps the money fields read-only in the API: only
:mod:`karni_commerce.services` writes them.
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from karni.fields import CurrencyField, LiveUniqueConstraint, MoneyField, StateField
from karni.models import BaseModel

__all__ = [
    "ZERO",
    "Cart",
    "CartLine",
    "Coupon",
    "CouponUse",
    "EmailTemplate",
    "Invoice",
    "Order",
    "OrderLine",
    "OrderNote",
    "OrderPayment",
    "OrderRefund",
    "Setting",
    "ShippingMethod",
    "ShippingZone",
    "TaxRate",
    "new_key",
    "split_codes",
]

ZERO = Decimal("0.00")


def split_codes(text: str) -> list[str]:
    """``"fr, de;ES"`` as ``["FR", "DE", "ES"]``: a list typed with commas, upper case."""
    found = [part.strip().upper() for part in str(text or "").replace(";", ",").split(",")]
    return [part for part in found if part]


def new_key() -> str:
    """A secret that lets a visitor reach their own cart or order, and nothing else."""
    return secrets.token_urlsafe(24)


class Cart(BaseModel):
    """A cart: a signed-in person's, or a visitor's, found by its token."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_carts",
    )
    token = models.CharField(max_length=64, default=new_key)
    # The coupon the shopper applied (POST carts/current/coupon/): checkout uses it.
    coupon = models.ForeignKey(
        "karni_commerce.Coupon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="carts",
    )
    # The email a visitor typed at checkout (the quote keeps it), for the abandoned carts.
    email = models.EmailField(blank=True, default="")
    # When a line last changed: a cart left alone since is abandoned (services.abandoned).
    touched_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [LiveUniqueConstraint(fields=["token"], name="karni_commerce_cart_token")]

    class APIMeta:
        exclude = ["token"]
        read_only = ["user", "coupon", "email", "touched_at"]

    class AdminMeta:
        list_display = ["user", "created_at", "updated_at"]

    class Karni:
        owner_field = "user"

    def __str__(self) -> str:
        return f"Cart {str(self.pk)[:8]}"


class CartLine(BaseModel):
    """One thing in a cart: its kind, its item, the options picked and how many."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=40)
    item = models.CharField(max_length=64)
    options = models.JSONField(default=dict, blank=True)
    # The options as a key (Sellable.option_key): two sizes of one shirt are two lines.
    variant = models.CharField(max_length=64, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            LiveUniqueConstraint(
                fields=["cart", "kind", "item", "variant"],
                name="karni_commerce_cartline_unique",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="karni_commerce_cartline_quantity_gte_1"
            ),
        ]

    class APIMeta:
        read_only = ["cart", "kind", "item", "options", "variant", "quantity"]

    class Karni:
        owner_field = "cart__user"
        cascade = {"cart": "a line is part of its cart and goes with it"}

    def __str__(self) -> str:
        return f"{self.quantity} x {self.kind}:{self.item}"


class Order(BaseModel):
    """An order: who bought, what (its lines), for how much, and where the money stands."""

    STATES = (
        "pending",
        "paid",
        "part_paid",
        "failed",
        "cancelled",
        "refunded",
        "part_refunded",
    )

    number = models.PositiveIntegerField()
    # The number as text, for search (karni.global_search takes text fields only).
    reference = models.CharField(max_length=40, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_orders",
    )
    email = models.EmailField()
    buyer_name = models.CharField(max_length=200, blank=True, default="")
    status = StateField(
        states=list(STATES),
        transitions={
            "pending": ["paid", "part_paid", "failed", "cancelled"],
            "part_paid": ["paid", "part_refunded", "refunded"],
            "failed": ["pending", "cancelled"],
            "paid": ["part_refunded", "refunded", "cancelled"],
            "part_refunded": ["refunded"],
        },
    )
    currency = CurrencyField()
    subtotal = MoneyField(currency_field="currency", default=ZERO)
    discount_total = MoneyField(currency_field="currency", default=ZERO)
    shipping_total = MoneyField(currency_field="currency", default=ZERO)
    tax_total = MoneyField(currency_field="currency", default=ZERO)
    total = MoneyField(currency_field="currency", default=ZERO)
    # Whether the prices of this order included their tax (KARNI_COMMERCE_PRICES_INCLUDE_TAX).
    prices_include_tax = models.BooleanField(default=False)
    coupon_code = models.CharField(max_length=40, blank=True, default="")
    shipping_method = models.CharField(max_length=120, blank=True, default="")
    # The tax by rate: [{"name": "VAT", "rate": "20.0000", "amount": "4.00"}].
    tax_lines = models.JSONField(default=list, blank=True)
    amount_paid = MoneyField(currency_field="currency", default=ZERO)
    amount_refunded = MoneyField(currency_field="currency", default=ZERO)
    billing = models.JSONField(default=dict, blank=True)
    shipping = models.JSONField(default=dict, blank=True)
    needs_shipping = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    key = models.CharField(max_length=64, default=new_key)
    hold_until = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            LiveUniqueConstraint(fields=["number"], name="karni_commerce_order_number"),
        ]
        indexes = [
            models.Index(fields=["status", "hold_until"], name="karni_commerce_order_hold"),
            models.Index(fields=["email"], name="karni_commerce_order_email"),
            # revenue by day (the dashboard's tiles and chart)
            models.Index(fields=["paid_at"], name="karni_commerce_order_paid_at"),
        ]

    class APIMeta:
        # The server writes every one of these: checkout, the settlement and refunds.
        read_only = [
            "number",
            "reference",
            "user",
            "email",
            "buyer_name",
            "status",
            "currency",
            "subtotal",
            "discount_total",
            "shipping_total",
            "tax_total",
            "total",
            "prices_include_tax",
            "coupon_code",
            "shipping_method",
            "tax_lines",
            "amount_paid",
            "amount_refunded",
            "billing",
            "shipping",
            "needs_shipping",
            "hold_until",
            "paid_at",
            "cancelled_at",
        ]
        exclude = ["key"]

    class AdminMeta:
        list_display = ["number", "email", "status", "total", "currency", "created_at"]
        search_fields = ["number", "email", "buyer_name"]
        read_only = ["number", "key", "amount_paid", "amount_refunded"]

    class Karni:
        owner_field = "user"
        # A shipment's order column, or any relation to an order, shows its number.
        label = "number"
        # The order page's history: every move of the money (GET orders/{id}/history/).
        audit = ["status", "amount_paid", "amount_refunded"]
        # karni_commerce.order:report runs the sales reports (karni_commerce.reports).
        actions = ["report"]
        # The staff home's tile (docs/api.md, "The staff dashboard"): the orders by
        # money state, those placed today, and the newest.
        dashboard = {
            "label": "Orders",
            "order": 1,
            "by": "status",
            "values": ["pending", "paid", "failed", "refunded"],
            "counts": {"Placed today": {"created_at__gte": "today"}},
            "recent": 8,
            "columns": ["number", "email", "status", "total", "created_at"],
        }
        search = {
            "fields": ["reference", "email", "buyer_name"],
            "title": "reference",
            "subtitle": "email",
        }

    def __str__(self) -> str:
        return f"Order {self.number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.number and not self.reference:
            self.reference = str(self.number)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "reference"}
        super().save(*args, **kwargs)

    @property
    def balance(self) -> Decimal:
        """What is still to pay: the total less what was paid."""
        return max(Decimal(self.total) - Decimal(self.amount_paid), ZERO)

    @property
    def refundable(self) -> Decimal:
        """What may still go back: what was paid less what was refunded."""
        return max(Decimal(self.amount_paid) - Decimal(self.amount_refunded), ZERO)

    def guest_may_read(self, key: str) -> bool:
        """Whether ``key`` is this order's secret (a guest reads their order with it)."""
        return bool(key) and secrets.compare_digest(str(key), str(self.key))


class OrderLine(BaseModel):
    """A line of an order, with the item's name, SKU and price as they were at checkout."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=40)
    item = models.CharField(max_length=64)
    options = models.JSONField(default=dict, blank=True)
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, blank=True, default="")
    quantity = models.PositiveIntegerField()
    quantity_refunded = models.PositiveIntegerField(default=0)
    currency = CurrencyField()
    unit_price = MoneyField(currency_field="currency")
    compare_at_price = MoneyField(currency_field="currency", null=True, blank=True)
    line_total = MoneyField(currency_field="currency")
    # What the options read as ([{"label": "Size", "value": "M"}]), copied at checkout.
    details = models.JSONField(default=list, blank=True)
    discount = MoneyField(currency_field="currency", default=ZERO)
    tax_rate = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0"))
    tax = MoneyField(currency_field="currency", default=ZERO)
    # What the buyer pays for the line: less its discount, with its tax.
    total = MoneyField(currency_field="currency", null=True, blank=True)
    needs_shipping = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "position"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_refunded__lte=models.F("quantity")),
                name="karni_commerce_orderline_refunded_lte_quantity",
            ),
        ]
        indexes = [models.Index(fields=["kind", "item"], name="karni_commerce_line_item")]

    class APIMeta:
        read_only = [
            "order",
            "kind",
            "item",
            "options",
            "name",
            "sku",
            "quantity",
            "quantity_refunded",
            "currency",
            "unit_price",
            "compare_at_price",
            "line_total",
            "details",
            "discount",
            "tax_rate",
            "tax",
            "total",
            "needs_shipping",
            "position",
        ]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "a line is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.quantity} x {self.name}"

    @property
    def paid_total(self) -> Decimal:
        """What the buyer pays for the whole line (its ``total``, or ``line_total`` before M3)."""
        return Decimal(self.total if self.total is not None else self.line_total)

    def unit_paid(self) -> Decimal:
        """What one item of the line cost the buyer, discount off and tax in."""
        return self.paid_total / self.quantity if self.quantity else ZERO


class OrderPayment(BaseModel):
    """A payment of an order: an order may have several (a retry, a deposit and its balance)."""

    class Purpose(models.TextChoices):
        FULL = "full"
        DEPOSIT = "deposit"
        BALANCE = "balance"
        RETRY = "retry"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    payment = models.OneToOneField(
        "karni_payments.Payment", on_delete=models.PROTECT, related_name="commerce_order"
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.FULL)
    currency = CurrencyField()
    amount = MoneyField(currency_field="currency")

    class APIMeta:
        read_only = ["order", "payment", "purpose", "currency", "amount"]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "the link is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.purpose} payment of order {self.order_id}"


class OrderRefund(BaseModel):
    """A refund of an order: how much, of which lines, and whether the items go back."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="refunds")
    refund = models.OneToOneField(
        "karni_payments.Refund", on_delete=models.PROTECT, related_name="commerce_order"
    )
    currency = CurrencyField()
    amount = MoneyField(currency_field="currency")
    lines = models.JSONField(default=dict, blank=True)
    restock = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True, default="")
    settled_at = models.DateTimeField(null=True, blank=True)

    class APIMeta:
        read_only = [
            "order",
            "refund",
            "currency",
            "amount",
            "lines",
            "restock",
            "reason",
            "settled_at",
        ]

    class Karni:
        owner_field = "order__user"
        cascade = {"order": "a refund record is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"refund {self.amount} of order {self.order_id}"

    def line_quantities(self) -> dict[str, int]:
        """``{order line id: quantity}`` this refund covers."""
        found: dict[str, Any] = dict(self.lines or {})
        return {str(key): int(value) for key, value in found.items()}


class OrderNote(BaseModel):
    """A note on an order: for the staff only, or for the buyer (who gets it by email too)."""

    class Kind(models.TextChoices):
        INTERNAL = "internal", "Internal"
        CUSTOMER = "customer", "To the customer"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.INTERNAL)
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_order_notes",
    )

    class Meta:
        ordering = ["created_at"]

    class APIMeta:
        read_only = ["order", "kind", "body", "author"]

    class Karni:
        cascade = {"order": "a note is part of its order and goes with it"}

    def __str__(self) -> str:
        return f"{self.get_kind_display()} note on order {self.order_id}"


class Coupon(BaseModel):
    """A code that takes money off: a percent, a fixed amount, or the shipping.

    ``minimum_spend`` is what the items must come to first. ``starts_at`` and
    ``ends_at`` bound when it works. ``usage_limit`` caps its uses in all,
    ``usage_limit_per_person`` per buyer (by account, else by email). ``kinds``
    limits it to some kinds for sale (``product, seat``), ``items`` to some
    items (``["product:12"]``), and ``limits`` to the coupon keys the kinds'
    adapters give (``{"categories": ["3"]}``, ``Sellable.coupon_keys``). Each
    key may also be ``{"key": "3", "name": "Kitchen"}``, as the staff's form
    keeps it, with its name for the screen. A
    line matches when it is one of ``items`` or shares a value with a key of
    ``limits``. With neither, every line of its kinds matches.
    """

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percent off"
        FIXED = "fixed", "Amount off"
        FREE_SHIPPING = "free_shipping", "Free shipping"

    code = models.CharField(max_length=40, help_text="What the buyer types, any case.")
    description = models.CharField(max_length=200, blank=True, default="")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PERCENT)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="The percent off, or the amount off. Not used for free shipping.",
    )
    minimum_spend = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_limit_per_person = models.PositiveIntegerField(null=True, blank=True)
    kinds = models.CharField(
        max_length=200, blank=True, default="", help_text="Kinds it works on, with commas."
    )
    items = models.JSONField(default=list, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            LiveUniqueConstraint(fields=["code"], name="karni_commerce_coupon_code"),
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="karni_commerce_coupon_amount_gte_0"
            ),
        ]

    class AdminMeta:
        list_display = ["code", "kind", "amount", "active", "ends_at"]
        search_fields = ["code", "description"]

    class Karni:
        search = {"fields": ["code", "description"], "title": "code", "subtitle": "description"}

    def __str__(self) -> str:
        return self.code

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = str(self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def kind_list(self) -> list[str]:
        return [kind.lower() for kind in split_codes(self.kinds)]


class CouponUse(BaseModel):
    """One use of a coupon, by an order: what counts toward its limits."""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="uses")
    order = models.ForeignKey("karni_commerce.Order", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="commerce_coupon_uses",
    )
    email = models.EmailField()
    currency = CurrencyField()
    amount = MoneyField(currency_field="currency", default=ZERO)

    class Meta:
        indexes = [models.Index(fields=["coupon", "email"], name="karni_commerce_use_email")]

    class APIMeta:
        read_only = ["coupon", "order", "user", "email", "currency", "amount"]

    class Karni:
        cascade = {"coupon": "a use is part of its coupon", "order": "and of its order"}

    def __str__(self) -> str:
        return f"{self.coupon_id} on order {self.order_id}"


class ShippingZone(BaseModel):
    """Where methods of shipping apply: some countries (and regions in them), or anywhere.

    Checkout takes the first zone, by ``position``, whose countries hold the
    address's country (and whose regions, when it names any, its region). A
    zone with no countries is everywhere else.
    """

    name = models.CharField(max_length=120)
    countries = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Country codes with commas (FR, DE). Blank: everywhere else.",
    )
    regions = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Regions or postcode starts, with commas (NY, 75*). Blank: the whole country.",
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    class Karni:
        search = {"fields": ["name", "countries"], "title": "name", "subtitle": "countries"}

    def __str__(self) -> str:
        return self.name

    def covers(self, country: str, region: str = "", postcode: str = "") -> bool:
        """Whether an address in ``country`` (``region``, ``postcode``) is in this zone."""
        countries = split_codes(self.countries)
        if countries and str(country or "").upper() not in countries:
            return False
        regions = split_codes(self.regions)
        if not regions:
            return True
        place = str(region or "").strip().upper()
        code = str(postcode or "").replace(" ", "").upper()
        for wanted in regions:
            if wanted.endswith("*") and code.startswith(wanted[:-1]):
                return True
            if wanted == place:
                return True
        return False


class ShippingMethod(BaseModel):
    """A way to send an order in a zone: a flat rate, free above an amount, or pickup.

    ``flat`` costs ``cost`` (free once the items reach ``free_above``, when set).
    ``free`` costs nothing and shows once the items reach ``free_above``.
    ``pickup`` is collected from the business and costs ``cost``.
    """

    class Kind(models.TextChoices):
        FLAT = "flat", "Flat rate"
        FREE = "free", "Free shipping"
        PICKUP = "pickup", "Local pickup"

    zone = models.ForeignKey(ShippingZone, on_delete=models.CASCADE, related_name="methods")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FLAT)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    free_above = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    taxable = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["zone", "position", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cost__gte=0), name="karni_commerce_method_cost_gte_0"
            ),
        ]

    class Karni:
        cascade = {"zone": "a method is part of its zone and goes with it"}

    def __str__(self) -> str:
        return self.name


class TaxRate(BaseModel):
    """The tax of a country (and a region in it, or anywhere), for one tax class.

    The most specific rate wins: the country and region, then the country,
    then the rate with neither. ``tax_class`` matches a sellable's
    ``Price.tax_class`` (blank: the standard class). ``shipping``: the rate
    applies to shipping too.
    """

    name = models.CharField(max_length=80, help_text="What the tax line says (VAT, Sales tax).")
    country = models.CharField(max_length=2, blank=True, default="", help_text="Blank: anywhere.")
    region = models.CharField(
        max_length=120, blank=True, default="", help_text="Blank: the country."
    )
    rate = models.DecimalField(max_digits=7, decimal_places=4, help_text="In percent: 20 is 20%.")
    tax_class = models.CharField(max_length=40, blank=True, default="")
    shipping = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["country", "region", "tax_class", "position"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rate__gte=0) & Q(rate__lte=100), name="karni_commerce_tax_rate_range"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.rate.normalize()}%"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.country = str(self.country or "").strip().upper()
        self.region = str(self.region or "").strip().upper()
        super().save(*args, **kwargs)


class Invoice(BaseModel):
    """The invoice of a paid order: its own number, counted up, and who sold it.

    Numbered once, when the order is paid (``karni_commerce.services``), from
    ``KARNI_COMMERCE_FIRST_INVOICE``. ``seller`` keeps the business's details as
    they were that day (name, legal name, address, tax number), so a printed
    invoice never changes when the details do.
    """

    order = models.OneToOneField(
        "karni_commerce.Order", on_delete=models.PROTECT, related_name="invoice"
    )
    number = models.PositiveIntegerField()
    reference = models.CharField(max_length=40, help_text="The number as printed: INV-1001.")
    issued_at = models.DateTimeField()
    seller = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            LiveUniqueConstraint(fields=["number"], name="karni_commerce_invoice_number")
        ]

    class APIMeta:
        read_only = ["order", "number", "reference", "issued_at", "seller"]

    class Karni:
        label = "reference"

    def __str__(self) -> str:
        return self.reference


class Setting(BaseModel):
    """What a business changed in Settings, one row per group: ``details``, ``emails``,
    or a part's section (``shop``). Experimental, and only until the family's
    preferences contract is installed (:mod:`karni_commerce.preferences`)."""

    group = models.CharField(max_length=60)
    values = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [LiveUniqueConstraint(fields=["group"], name="karni_commerce_setting_group")]

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.group


class EmailTemplate(BaseModel):
    """An email a business rewrote in the app: its subject and text, by kind.

    It wins over the template files (``karni.mail``'s ``KARNI_MAIL_SOURCE``), and
    renders with the restricted engine: the kind's merge fields only. Deleting
    the row puts the files back. Experimental, until the family's notifications
    contract keeps them.
    """

    kind = models.CharField(max_length=120)
    subject = models.CharField(max_length=300)
    text = models.TextField()

    class Meta:
        ordering = ["kind"]
        constraints = [LiveUniqueConstraint(fields=["kind"], name="karni_commerce_email_kind")]

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.kind
