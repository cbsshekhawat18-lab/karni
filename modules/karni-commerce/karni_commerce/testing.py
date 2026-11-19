"""Experimental. Test helpers for a part that sells through commerce: does its adapter keep
the contract?

A part runs :func:`assert_sellable` on its own adapter, in its own tests::

    from karni_commerce.testing import assert_sellable


    def test_the_booking_adapter_keeps_the_commerce_contract(slot):
        assert_sellable("booking", slot)

It drives the adapter through commerce's order path inside a transaction it
rolls back, and checks what each hook does to what is left of the item
(``Sellable.available``):

1. The adapter is the one commerce calls for its kind, and finds the item by
   its key (``key``, ``get``, ``get_many``).
2. Reading the item writes nothing to the database and answers the same twice:
   ``name``, ``sku``, ``details``, ``price``, ``needs_shipping``, ``available``,
   ``coupon_keys``, ``allows_deposit``, ``deposit``, ``hold_minutes``,
   ``validate`` and ``clean_options``. Cleaning cleaned options changes
   nothing, and their ``option_key`` stays the same.
3. The price is a :class:`~karni_commerce.sellables.Price` of 0 or more, a
   deposit is more than 0 and less than the price, and a hold is ``None`` or a
   whole number of minutes from 1 (``COM003``).
4. Checkout holds the line (``services.place_order``): what is left drops by the
   quantity. An order that is not paid lets it go (``release``): it is back.
5. Paid (``on_paid``), what is left stays down. A paid order cancelled
   (``on_cancelled``) puts it back.
6. Paid and then refunded in full with the items back (``on_refunded`` with
   ``restock``): it is back. Refunded without them, it is never more than before.

An item with no limit (``available`` is ``None``) skips the counts, but every
hook still runs. A free item is paid when it is placed, so it skips step 4's
release. Every failure is ``COM002`` and names the step and what it saw.

Override / escape hatch: every step is a plain function of this module
(:func:`check_reads`, :func:`check_hold_and_release`, :func:`check_paid_and_cancelled`,
:func:`check_paid_and_refunded`), so a part runs the ones that fit its kind.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from karni.exceptions import KarniAssertionError
from rest_framework.exceptions import ValidationError

from karni_commerce.models import Order, OrderLine
from karni_commerce.sellables import Price, Sellable, hold_of, kinds

__all__ = [
    "SellableReport",
    "assert_sellable",
    "check_hold_and_release",
    "check_paid_and_cancelled",
    "check_paid_and_refunded",
    "check_reads",
]

#: The email the orders of the checks are placed with (rolled back, never sent).
EMAIL = "sellable-check@example.com"
_WRITES = ("insert", "update", "delete")


@dataclass
class SellableReport:
    """What :func:`assert_sellable` checked, and what was left of the item before."""

    kind: str
    key: str
    available: int | None
    checked: list[str] = field(default_factory=list)


def _fail(step: str, message: str) -> KarniAssertionError:
    return KarniAssertionError(
        f"The {step} step of the sellable check failed: {message}", code="COM002"
    )


def _adapter(kind_or_adapter: str | Sellable) -> Sellable:
    known = kinds()
    if isinstance(kind_or_adapter, str):
        found = known.get(kind_or_adapter)
        if found is None:
            raise _fail(
                "adapter",
                f"no adapter sells {kind_or_adapter!r} (registered: "
                f"{', '.join(sorted(known)) or 'none'}).",
            )
        return found
    adapter = kind_or_adapter
    registered = known.get(str(adapter.kind))
    if registered is None or type(registered) is not type(adapter):
        raise _fail(
            "adapter",
            f"{type(adapter).__name__} is not the adapter commerce calls for "
            f"{adapter.kind!r} ({type(registered).__name__ if registered else 'none'} is). "
            "Register it, or name it in KARNI_COMMERCE_SELLABLES.",
        )
    return registered


def _left(adapter: Sellable, key: str, options: Mapping[str, Any]) -> int | None:
    item = adapter.get(key)
    if item is None:
        raise KarniAssertionError(f"The item {key!r} is gone.", code="COM002")
    found = adapter.available(item, options)
    return None if found is None else int(found)


def _expect(
    step: str, adapter: Sellable, key: str, options: Mapping[str, Any], want: int | None, what: str
) -> None:
    if want is None:
        return
    now = _left(adapter, key, options)
    if now != want:
        raise _fail(step, f"{what}: {want} should be left, {now} is (Sellable.available).")


def _no_writes(step: str, run: Callable[[], Any]) -> Any:
    with CaptureQueriesContext(connection) as seen:
        answer = run()
    written = [
        query["sql"]
        for query in seen.captured_queries
        if str(query["sql"]).lstrip().lower().startswith(_WRITES)
    ]
    if written:
        raise _fail(step, f"reading the item wrote to the database: {written[0][:200]}")
    return answer


def check_reads(
    adapter: Sellable, item: Any, quantity: int, options: Mapping[str, Any], buyer: Any = None
) -> dict[str, Any]:
    """Steps 1 to 3: the item is found by its key, and the reading hooks write nothing,
    answer the same twice and give sound values. Returns the cleaned options."""
    key = adapter.key(item)
    if not isinstance(key, str) or not key:
        raise _fail("key", f"key(item) gave {key!r}: a line stores the item by a text key.")
    if adapter.get(key) is None or key not in adapter.get_many([key]):
        raise _fail("key", f"get({key!r}) and get_many([{key!r}]) must find the item again.")

    def read() -> tuple[Any, ...]:
        cleaned = adapter.clean_options(item, dict(options))
        adapter.validate(item, quantity, cleaned, buyer)
        allows = adapter.allows_deposit(item, cleaned)
        return (
            cleaned,
            adapter.option_key(item, cleaned),
            adapter.name(item, cleaned),
            adapter.sku(item, cleaned),
            adapter.details(item, cleaned),
            adapter.price(item, cleaned, buyer),
            adapter.needs_shipping(item, cleaned),
            adapter.available(item, cleaned),
            adapter.coupon_keys(item),
            allows,
            adapter.deposit(item, cleaned) if allows else None,
            hold_of(adapter, item, cleaned),
        )

    try:
        first = _no_writes("reads", read)
    except ValidationError as exc:
        raise _fail(
            "validate",
            f"the adapter refused {quantity} of the item with {dict(options)!r}: {exc.detail}. "
            "Pass the options it is sold with, and an item with enough left.",
        ) from None
    second = _no_writes("reads", read)
    if first != second:
        raise _fail("reads", f"two reads of the item answered differently: {first} then {second}")
    cleaned, option_key, name, sku, details, price, _ships, _left_now, keys, allows, deposit, _ = (
        first
    )
    again = adapter.clean_options(item, dict(cleaned))
    if again != cleaned or adapter.option_key(item, again) != option_key:
        raise _fail("options", f"clean_options is not stable: {cleaned!r} cleaned is {again!r}.")
    if not isinstance(name, str) or not name.strip():
        raise _fail("name", f"name(item, options) gave {name!r}: a line shows a name.")
    if not isinstance(sku, str):
        raise _fail("sku", f"sku(item, options) gave {sku!r}: text, blank when there is none.")
    if not isinstance(details, list) or not all(
        isinstance(row, dict) and {"label", "value"} <= set(row) for row in details
    ):
        raise _fail("details", f'details gave {details!r}: [{{"label": ..., "value": ...}}].')
    if not isinstance(keys, dict):
        raise _fail("coupon_keys", f"coupon_keys(item) gave {keys!r}: a dict of lists.")
    if not isinstance(price, Price) or Decimal(price.unit) < 0:
        raise _fail("price", f"price(item, options, buyer) gave {price!r}: a Price of 0 or more.")
    if allows and not (Decimal(0) < Decimal(deposit) < Decimal(price.unit)):
        raise _fail(
            "deposit",
            f"the deposit is {deposit} for a price of {price.unit}: more than 0 and less than "
            "the price (else allows_deposit should say no).",
        )
    return dict(cleaned)


def _place(adapter: Sellable, key: str, quantity: int, options: Mapping[str, Any]) -> Order:
    from karni_commerce import services

    try:
        return services.place_order(
            [(adapter.kind, key, quantity, dict(options))], email=EMAIL, billing={}, shipping={}
        )
    except ValidationError as exc:
        raise _fail("hold", f"checkout refused the line: {exc.detail}") from None


def _paid(order: Order) -> Order:
    """The order paid as the settlement does it (no payment: the provider is not called)."""
    from karni_commerce import services

    if order.status == "pending":
        services._mark_paid(order)
    return order


def _line(order: Order) -> OrderLine:
    return order.lines.get()


def check_hold_and_release(
    adapter: Sellable, key: str, quantity: int, options: Mapping[str, Any]
) -> None:
    """Step 4: checkout holds the line, and an order not paid lets it go."""
    from karni_commerce import services

    before = _left(adapter, key, options)
    with transaction.atomic():
        order = _place(adapter, key, quantity, options)
        held = None if before is None else before - quantity
        _expect("hold", adapter, key, options, held, "after checkout held the line")
        if order.status == "pending":
            services.cancel(order, "the sellable check")
            _expect("release", adapter, key, options, before, "after the order let it go")
        transaction.set_rollback(True)


def check_paid_and_cancelled(
    adapter: Sellable, key: str, quantity: int, options: Mapping[str, Any]
) -> None:
    """Step 5: a paid line stays taken, and cancelling the paid order puts it back."""
    from karni_commerce import services

    before = _left(adapter, key, options)
    with transaction.atomic():
        order = _paid(_place(adapter, key, quantity, options))
        taken = None if before is None else before - quantity
        _expect("on_paid", adapter, key, options, taken, "after the order was paid")
        services.cancel(order, "the sellable check")
        _expect("on_cancelled", adapter, key, options, before, "after the paid order was cancelled")
        transaction.set_rollback(True)


def check_paid_and_refunded(
    adapter: Sellable, key: str, quantity: int, options: Mapping[str, Any]
) -> None:
    """Step 6: refunded in full with the items back, what is left is back; without them,
    never more than before."""
    before = _left(adapter, key, options)
    for restock in (True, False):
        with transaction.atomic():
            line = _line(_paid(_place(adapter, key, quantity, options)))
            line.quantity_refunded = quantity  # as the settlement of a refund does
            line.save(update_fields=["quantity_refunded", "updated_at"])
            adapter.on_refunded(line, quantity, restock)
            now = _left(adapter, key, options)
            if before is not None and restock and now != before:
                raise _fail(
                    "on_refunded",
                    f"after a full refund with the items back {before} should be left, {now} is.",
                )
            if before is not None and now is not None and now > before:
                raise _fail(
                    "on_refunded",
                    f"after a full refund {now} are left, more than the {before} before it.",
                )
            transaction.set_rollback(True)


def assert_sellable(
    kind_or_adapter: str | Sellable,
    item: Any,
    *,
    quantity: int = 1,
    options: Mapping[str, Any] | None = None,
    buyer: Any = None,
) -> SellableReport:
    """Experimental. Check that the adapter of a kind keeps commerce's contract for ``item``.

    ``kind_or_adapter`` is the kind (``"booking"``) or the adapter; ``options`` are
    what the item is sold with (``{"variation": "<id>"}``). Everything runs in a
    transaction that is rolled back, so the item is as it was afterwards.

    :raises KarniAssertionError: ``COM002``, naming the step and what it saw.
    """
    adapter = _adapter(kind_or_adapter)
    with transaction.atomic():
        try:
            chosen = check_reads(adapter, item, quantity, dict(options or {}), buyer)
            key = adapter.key(item)
            report = SellableReport(adapter.kind, key, _left(adapter, key, chosen))
            report.checked.append("reads")
            check_hold_and_release(adapter, key, quantity, chosen)
            report.checked.append("hold and release")
            check_paid_and_cancelled(adapter, key, quantity, chosen)
            report.checked.append("paid and cancelled")
            check_paid_and_refunded(adapter, key, quantity, chosen)
            report.checked.append("paid and refunded")
        finally:
            transaction.set_rollback(True)
    return report
