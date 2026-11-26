"""Commerce's own settings section: how people buy, and the invoices.

Read with ``preferences.value("commerce.guest_checkout", True)`` (``karni.preferences``).
The values are changed on the Settings page by whoever may change every section
(``preferences.sectionvalue:change``).
"""

from __future__ import annotations

from karni import preferences
from pydantic import Field


@preferences.section("commerce", title="Checkout")
class CommercePreferences(preferences.Section):
    """How people buy: as a guest or with an account, the terms, the invoices."""

    guest_checkout: bool = Field(
        True, description="Visitors may buy without an account. Off: they sign in first."
    )
    accept_terms: bool = Field(
        False, description="Buyers tick that they accept the terms of sale before they pay."
    )
    terms_url: str = Field("/terms", max_length=200, description="Where the terms of sale are.")
    invoice_prefix: str = Field(
        "INV-", max_length=12, description="Printed before an invoice's number (INV-1001)."
    )
    invoice_footer: str = Field(
        "", max_length=500, description="A line at the foot of every invoice (bank details)."
    )
    staff_emails: str = Field(
        "",
        max_length=500,
        description="Who gets the new-order email, with commas. Blank: the project's setting.",
    )
    abandoned_after_hours: int = Field(
        1, ge=1, le=720, description="A cart left this many hours is listed as abandoned."
    )
