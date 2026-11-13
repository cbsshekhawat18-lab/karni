"""Settings vocabulary for karni-commerce.

:data:`DEFAULTS` is the module's settings fragment, exposed through the
``karni.settings`` entry point, so :func:`karni.conf.karni_settings` merges it
into every project that installs the module. :func:`get` is the accessor
every ``karni_commerce`` module reads settings through.

Override / escape hatch: define any of these names in your ``settings.py`` or
set the matching environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # The project's currency, as an ISO 4217 code. Blank (the default) takes
    # KARNI_PAYMENTS_CURRENCY, so a project names its currency once.
    "KARNI_COMMERCE_CURRENCY": env("KARNI_COMMERCE_CURRENCY", default=""),
    # How long checkout holds an order's items for its payment, in minutes.
    # An order not paid by then is cancelled and its items are free again.
    "KARNI_COMMERCE_HOLD_MINUTES": env.int("KARNI_COMMERCE_HOLD_MINUTES", default=30),
    # The most of one item a cart line takes.
    "KARNI_COMMERCE_MAX_QUANTITY": env.int("KARNI_COMMERCE_MAX_QUANTITY", default=99),
    # The number of the first order. Later orders count up from it.
    "KARNI_COMMERCE_FIRST_NUMBER": env.int("KARNI_COMMERCE_FIRST_NUMBER", default=1001),
    # The dotted path of the function that gives a new order its number:
    # number(order) -> int. Blank (the default) counts up from
    # KARNI_COMMERCE_FIRST_NUMBER (karni_commerce.services.next_number).
    "KARNI_COMMERCE_NUMBER": env("KARNI_COMMERCE_NUMBER", default=""),
    # Where a person reads an order in the app, after KARNI_FRONTEND_URL:
    # {number} and {key} (the guest's secret) are filled in. The payment's
    # return address and the emails' links point here.
    "KARNI_COMMERCE_ORDER_PATH": env(
        "KARNI_COMMERCE_ORDER_PATH", default="/orders/{number}?key={key}"
    ),
    # How long an order staff place by hand (a phone order) holds its items for
    # the buyer's payment, in minutes. Two days by default.
    "KARNI_COMMERCE_MANUAL_HOLD_MINUTES": env.int(
        "KARNI_COMMERCE_MANUAL_HOLD_MINUTES", default=2880
    ),
    # The dotted path of the class behind the staff's customers list and
    # customer page: customers(orders, search, ordering) and customer(orders,
    # email). The default groups the orders by the buyer's email; karni.people
    # replaces it with the people of the project.
    "KARNI_COMMERCE_CUSTOMERS": env(
        "KARNI_COMMERCE_CUSTOMERS", default="karni_commerce.customers.OrderCustomers"
    ),
    # Who gets the new-order email (commerce.new_order): a list of
    # addresses. Empty (the default) sends none.
    "KARNI_COMMERCE_STAFF_EMAILS": env.list("KARNI_COMMERCE_STAFF_EMAILS", default=[]),
    # The checkout validator for payments that are not an order's (the
    # dotted path karni_commerce.payments.checkout_validator hands them to).
    "KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR": env(
        "KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR",
        default="karni_payments.services.default_checkout_validator",
    ),
    # Whether the prices the sellables give include their tax. Off (the default):
    # tax is added on top at checkout. On: the tax is the part of each price
    # that is tax, and the total is the prices (with the discount and shipping).
    "KARNI_COMMERCE_PRICES_INCLUDE_TAX": env.bool(
        "KARNI_COMMERCE_PRICES_INCLUDE_TAX", default=False
    ),
    # The dotted path of the class that gives the shipping methods of an address
    # (karni_commerce.pricing.ZoneShipping: the zones and methods staff set up).
    "KARNI_COMMERCE_SHIPPING": env(
        "KARNI_COMMERCE_SHIPPING", default="karni_commerce.pricing.ZoneShipping"
    ),
    # The dotted path of the class that gives the tax rate of a tax class at an
    # address (karni_commerce.pricing.RateTax: the rates staff set up).
    "KARNI_COMMERCE_TAX": env("KARNI_COMMERCE_TAX", default="karni_commerce.pricing.RateTax"),
    # Sellable adapters by kind, as dotted paths, over the ones the apps
    # register in their sellables.py: {"product": "myapp.sellables.MyProduct"}.
    "KARNI_COMMERCE_SELLABLES": {},
    # The first invoice's number (karni_commerce.services.issue_invoice).
    "KARNI_COMMERCE_FIRST_INVOICE": env.int("KARNI_COMMERCE_FIRST_INVOICE", default=1001),
    # karni.mail's source of the emails a business edits, their switches and the sender
    # (karni_commerce.preferences_seam.MailSource, until the family's notifications).
    "KARNI_MAIL_SOURCE": env(
        "KARNI_MAIL_SOURCE", default="karni_commerce.preferences_seam.MailSource"
    ),
}
"""The karni-commerce settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """The effective value of a karni-commerce setting: the project's, else :data:`DEFAULTS`."""
    return getattr(settings, name, DEFAULTS[name])


def currency() -> str:
    """The project's currency (``KARNI_COMMERCE_CURRENCY``, else the payments currency)."""
    chosen = str(get("KARNI_COMMERCE_CURRENCY") or "")
    if not chosen:
        chosen = str(getattr(settings, "KARNI_PAYMENTS_CURRENCY", "") or "")
    return chosen.upper()
