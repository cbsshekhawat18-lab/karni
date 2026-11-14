"""karni-commerce's error codes (prefix ``COM``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain COM001``
and ``docs/errors.md`` include them. Codes are permanent: never renumber or
reuse one; append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_commerce"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="COM001",
        title="karni-commerce is installed without the people contract",
        kind="check",
        source=f"{_SOURCE}.checks.people_installed (karni.COM001)",
        why="Every order names the person who bought it (Order.person, found or made by "
        "karni.people.resolve at checkout), so the customers list, the person facts and the "
        "timeline are the same person in every part. Without karni.people the order table "
        "cannot be created.",
        fix="Set KARNI_PEOPLE = True above karni_settings(globals()) in config/settings.py "
        "(karni build writes it when karni.yaml lists the commerce module, or "
        "features: {people: true}), then run migrate.",
    ),
    ErrorCode(
        code="COM002",
        title="A sellable adapter does not keep the commerce contract",
        kind="test",
        source=f"{_SOURCE}.testing.assert_sellable",
        why="Commerce calls the adapter of every kind the same way: it holds a line at "
        "checkout, lets it go when the order is not paid, takes it when paid and gives it "
        "back on a refund. An adapter that prices, holds or releases wrongly sells the same "
        "seat twice or loses stock.",
        fix="Read the message: it names the hook and what it saw. Fix that hook of the "
        "adapter (docs/commerce.md, Selling something), then run the test again.",
    ),
    ErrorCode(
        code="COM003",
        title="A sellable's hold is not a positive number of minutes",
        kind="exception",
        source=f"{_SOURCE}.sellables.hold_of (Sellable.hold_minutes)",
        why="Checkout keeps an order's items for the shortest hold of its lines, and an "
        "order not paid by then is cancelled. Zero or a negative number would cancel it "
        "before the buyer could pay.",
        fix="Return None (the project's KARNI_COMMERCE_HOLD_MINUTES) or a whole number of "
        "minutes from 1 from the adapter's hold_minutes(item, options).",
    ),
)
