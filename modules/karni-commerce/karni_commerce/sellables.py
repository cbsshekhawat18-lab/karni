"""Experimental. The sellable adapter: how commerce sells something it does not know.

An app makes a model sellable by registering an adapter in its own
``<app>/sellables.py``, which karni-commerce imports at startup::

    # shop/sellables.py
    from karni_commerce.sellables import Price, Sellable, register

    from shop.models import Product


    @register
    class ProductSellable(Sellable):
        kind = "product"
        model = Product

        def price(self, item, options, buyer):
            return Price(unit=item.current_price(), compare_at=item.price)

        def hold(self, line):
            ...  # karni.capacity.reserve(item, line.quantity, field="available")

Commerce asks the adapter everything it needs about an item, by its kind:
what it is called and costs, whether it ships, whether a person may buy it,
and what happens to it when an order holds it, is paid, is cancelled or is
refunded. Each hook runs inside commerce's transaction, so a hook that
raises undoes the whole step (a checkout holds every line or none).

A line passed to the hooks is an :class:`~karni_commerce.models.OrderLine`
(``line.item`` is the item's key, ``line.quantity`` how many, and
``line.options`` what was picked). :meth:`Sellable.item_of` gives the item.

Override / escape hatch: subclass an app's adapter and register it again
under the same kind (the last registration wins), or name an adapter per kind
in ``KARNI_COMMERCE_SELLABLES`` (``{"product": "myapp.sellables.Mine"}``),
which wins over every registration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django.apps import apps
from django.db import models
from django.utils.module_loading import autodiscover_modules, import_string
from rest_framework.exceptions import ValidationError

if TYPE_CHECKING:
    from karni_commerce.models import OrderLine

__all__ = [
    "Price",
    "Sellable",
    "adapter_for",
    "autodiscover",
    "hold_of",
    "kinds",
    "refuse",
    "register",
    "unregister",
]

#: The adapters by kind, as the apps registered them.
_REGISTRY: dict[str, Sellable] = {}


@dataclass(frozen=True)
class Price:
    """Experimental. What one item costs now: the unit price, and the price it is compared with.

    ``compare_at`` is the regular price a sale is shown against (``None``
    when there is no sale). ``tax_class`` names the tax rule a later tax step
    applies (blank: the standard one).
    """

    unit: Decimal
    compare_at: Decimal | None = None
    tax_class: str = ""


def refuse(message: str, field: str = "item") -> ValidationError:
    """Experimental. The error an adapter raises to refuse a line: ``raise refuse("Sold out.")``."""
    return ValidationError({field: [message]})


class Sellable:
    """Experimental. The adapter of one kind of thing for sale. Subclass it and register it.

    Set :attr:`kind` (a short name, unique in the project: ``product``,
    ``booking``) and :attr:`model` (the model, or ``"app.Model"``), and
    implement :meth:`price`. Every other hook has a default that suits an
    item with no stock and nothing to ship.
    """

    #: The kind's name, as a cart line and an order line store it.
    kind: ClassVar[str] = ""
    #: The model whose rows are the items (or its ``"app_label.Model"`` label).
    model: ClassVar[type[models.Model] | str] = ""
    #: Whether another app may offer this kind as an extra to its own (a mat with a class).
    addon: ClassVar[bool] = False
    #: The text fields staff find an item by when they place an order by hand.
    search_fields: ClassVar[tuple[str, ...]] = ()
    #: What staff read for the kind (a filter, a badge on an item): "Booking". Blank: the
    #: kind in words.
    label: ClassVar[str] = ""

    def kind_label(self) -> str:
        """The kind as staff read it: :attr:`label`, else the kind in words (``"Product"``)."""
        return self.label or str(self.kind).replace("_", " ").capitalize()

    # -- finding items ------------------------------------------------------------------

    def model_class(self) -> type[models.Model]:
        """The model of the items."""
        if isinstance(self.model, str):
            return apps.get_model(self.model)
        return self.model

    def queryset(self) -> models.QuerySet[Any]:
        """The rows a cart may hold (all of them: :meth:`validate` refuses what is not for sale)."""
        return self.model_class()._default_manager.all()

    def key(self, item: Any) -> str:
        """The item's key, as a line stores it (its primary key, as text)."""
        return str(item.pk)

    def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        """The items of ``keys`` in one query, by key. A key with no row is left out."""
        wanted = list(dict.fromkeys(str(key) for key in keys))
        if not wanted:
            return {}
        found = self.queryset().filter(pk__in=wanted)
        return {self.key(item): item for item in found}

    def get(self, key: str) -> Any | None:
        """The item of ``key``, or ``None``."""
        return self.get_many([key]).get(str(key))

    def search(self, text: str) -> models.QuerySet[Any]:
        """The items staff may pick for an order placed by hand, matching ``text``.

        The default matches ``text`` in :attr:`search_fields` (case blind), and
        with no text gives every row of :meth:`queryset`. A kind with no
        ``search_fields`` is not offered to search.
        """
        rows = self.queryset()
        words = text.strip()
        if not words:
            return rows
        if not self.search_fields:
            return rows.none()
        query = models.Q()
        for name in self.search_fields:
            query |= models.Q(**{f"{name}__icontains": words})
        return rows.filter(query)

    def item_of(self, line: OrderLine) -> Any | None:
        """The item an order line names, or ``None`` when it is gone."""
        return self.get(line.item)

    # -- options: a size, a colour, a date ------------------------------------------------

    def clean_options(self, item: Any, options: Mapping[str, Any]) -> dict[str, Any]:
        """The options a buyer picked, checked and in their stored form.

        Called when a line goes in the cart and at checkout. Raise
        :func:`refuse` for options that do not fit the item (a size it does not
        come in, no size picked when one must be). The default keeps every
        option whose name does not start with ``_`` (those are the adapter's
        own notes on an order line).
        """
        return {str(key): value for key, value in options.items() if not str(key).startswith("_")}

    def option_key(self, item: Any, options: Mapping[str, Any]) -> str:
        """What tells two lines of one item apart: two sizes of a shirt are two cart lines.

        Blank for no options. The default is a short hash of the options.
        """
        chosen = {key: value for key, value in options.items() if not str(key).startswith("_")}
        if not chosen:
            return ""
        text = json.dumps(chosen, sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def choices(self, item: Any) -> list[dict[str, Any]]:
        """Every set of options the item is sold with (each size of a shirt), for staff to pick.

        Staff placing an order by hand see one row per choice. The default is
        one choice with no options.
        """
        return [{}]

    def details(self, item: Any, options: Mapping[str, Any]) -> list[dict[str, str]]:
        """The options in words for a cart and an order line: ``[{"label": "Size", "value": "M"}]``.

        Copied to the order line at checkout. The default lists none.
        """
        return []

    # -- what it is and costs -------------------------------------------------------------

    def name(self, item: Any, options: Mapping[str, Any]) -> str:
        """The name a cart and an order line show (copied to the order line)."""
        return str(item)

    def sku(self, item: Any, options: Mapping[str, Any]) -> str:
        """The stock-keeping code copied to the order line (blank when there is none)."""
        return ""

    def url(self, item: Any) -> str:
        """Where the item's own page is in the app (a path), or blank."""
        return ""

    def image(self, item: Any) -> Any:
        """The item's picture: a file field value, a URL, or ``None``."""
        return None

    def price(self, item: Any, options: Mapping[str, Any], buyer: Any) -> Price:
        """The price of one item now, for ``buyer`` (a user or ``None``)."""
        raise NotImplementedError(f"{type(self).__name__}.price(item, options, buyer)")

    def needs_shipping(self, item: Any, options: Mapping[str, Any]) -> bool:
        """Whether the item is sent to an address (checkout then asks for one)."""
        return False

    def available(self, item: Any, options: Mapping[str, Any]) -> int | None:
        """How many a person can still buy now, or ``None`` for no limit."""
        return None

    def allows_deposit(self, item: Any, options: Mapping[str, Any]) -> bool:
        """Whether the item may be paid in part first (a booking's deposit).

        Checkout offers the buyer a deposit only when every line of the order allows
        one. The order is then ``part_paid`` once the deposit is in, and the rest (the
        balance) is paid later through the order's link.
        """
        return False

    def deposit(self, item: Any, options: Mapping[str, Any]) -> Decimal:
        """The deposit for one item, when :meth:`allows_deposit` says so.

        The order's deposit is the lines' deposits times their quantities, never more
        than the total. Shipping and tax are in the balance.
        """
        return Decimal("0")

    def hold_minutes(self, item: Any, options: Mapping[str, Any]) -> int | None:
        """How long checkout may hold the item for its payment, in minutes, or ``None``.

        ``None`` (the default) keeps the project's hold (``KARNI_COMMERCE_HOLD_MINUTES``,
        or ``KARNI_COMMERCE_MANUAL_HOLD_MINUTES`` for an order staff place). A booking
        slot may say 15: an order holds for the shortest hold of its lines, and one not
        paid by then is cancelled and lets every line go (:meth:`release`). ``COM003``
        for a number below 1.
        """
        return None

    def coupon_keys(self, item: Any) -> dict[str, Any]:
        """What a coupon may be limited to for this item: ``{"categories": ["3", "7"]}``.

        A coupon's ``limits`` name these keys (a category, a seller). Each value
        is a list of texts.
        """
        return {}

    # -- rules ----------------------------------------------------------------------------

    def validate(self, item: Any, quantity: int, options: Mapping[str, Any], buyer: Any) -> None:
        """Refuse a line that cannot be bought: ``raise refuse("...")``.

        The default refuses more than :meth:`available` allows.
        """
        left = self.available(item, options)
        if left is not None and quantity > left:
            name = self.name(item, options)
            raise refuse(f"Only {left} of {name} left." if left > 0 else f"{name} is sold out.")

    # -- what happens to it ------------------------------------------------------------------

    def hold(self, line: OrderLine) -> None:
        """Checkout holds the line for its payment (stock, a seat, a tentative slot)."""

    def release(self, line: OrderLine) -> None:
        """The order was not paid (failed, cancelled, expired): let the hold go."""

    def on_paid(self, line: OrderLine) -> None:
        """The order is paid: take what the line held (stock off the shelf, a confirmed slot).

        It runs once per line: when the order is paid in full, or when its deposit is
        paid (``line.order.status`` is then ``part_paid``). The balance paid later
        calls nothing more.
        """

    def on_cancelled(self, line: OrderLine) -> None:
        """A paid order was cancelled: undo :meth:`on_paid` (its money goes back separately)."""

    def on_refunded(self, line: OrderLine, quantity: int, restock: bool) -> None:
        """``quantity`` of the line was refunded. ``restock``: staff asked for the items back."""

    def refund_limit(self, line: OrderLine, now: datetime) -> Decimal:
        """How much of the line may still be refunded at ``now`` (default: what is left of it).

        What is left is what the buyer paid for the line (its discount off, its
        tax in) less what went back.
        """
        refunded = line.unit_paid() * line.quantity_refunded
        return max(line.paid_total - refunded, Decimal("0"))


def hold_of(adapter: Sellable, item: Any, options: Mapping[str, Any]) -> int | None:
    """Experimental. ``adapter.hold_minutes(item, options)``, checked: ``None`` or 1 and up.

    :raises KarniImproperlyConfigured: ``COM003`` for anything else.
    """
    found = adapter.hold_minutes(item, options)
    if found is None:
        return None
    if isinstance(found, bool) or not isinstance(found, int) or found < 1:
        from karni.exceptions import KarniImproperlyConfigured

        raise KarniImproperlyConfigured(
            f"{type(adapter).__name__}.hold_minutes() gave {found!r} for {adapter.kind!r}: "
            "return None (the project's hold) or a whole number of minutes from 1.",
            code="COM003",
        )
    return found


def register[S: type[Sellable]](adapter: S) -> S:
    """Experimental. Register ``adapter`` (a :class:`Sellable` subclass) under its ``kind``.

    Usable as a class decorator. Registering a kind again replaces it.

    :raises KarniTypeError: ``COM004`` for anything but a Sellable subclass.
    :raises KarniValueError: ``COM004`` for a kind that is not a short name.
    """
    from karni.exceptions import KarniTypeError, KarniValueError

    if not isinstance(adapter, type) or not issubclass(adapter, Sellable):
        raise KarniTypeError(
            f"register() takes a Sellable subclass, got {adapter!r}.", code="COM004"
        )
    if not adapter.kind or not str(adapter.kind).replace("_", "").isalnum():
        raise KarniValueError(
            f"{adapter.__name__}.kind must be a short name of letters, digits and _, "
            f"got {adapter.kind!r}.",
            code="COM004",
        )
    _REGISTRY[str(adapter.kind)] = adapter()
    return adapter


def unregister(kind: str) -> None:
    """Experimental. Forget the adapter of ``kind`` (tests, a project that replaces a kind)."""
    _REGISTRY.pop(kind, None)


def _configured() -> dict[str, Sellable]:
    from karni_commerce import conf

    found: dict[str, Sellable] = {}
    for kind, path in dict(conf.get("KARNI_COMMERCE_SELLABLES") or {}).items():
        adapter = import_string(str(path)) if isinstance(path, str) else path
        found[str(kind)] = adapter() if isinstance(adapter, type) else adapter
    return found


def kinds() -> dict[str, Sellable]:
    """Experimental. Every adapter by kind: the registered ones, then the configured ones."""
    return {**_REGISTRY, **_configured()}


def adapter_for(kind: str) -> Sellable:
    """Experimental. The adapter of ``kind``.

    :raises ValidationError: when no installed app sells that kind.
    """
    found = kinds().get(str(kind))
    if found is None:
        raise refuse(f"Nothing called {kind!r} is for sale here.", field="kind")
    return found


def autodiscover() -> None:
    """Experimental. Import ``<app>/sellables.py`` of every installed app (startup)."""
    autodiscover_modules("sellables")
