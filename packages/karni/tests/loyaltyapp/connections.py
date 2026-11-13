"""The loyalty test part's connections: one needs a module the core suite does not install."""

from __future__ import annotations

from karni import preferences

preferences.connection(
    "loyaltyapp.paid_visits",
    needs=["karni_payments"],
    default=True,
    describe="A paid visit earns points.",
)
preferences.connection(
    "loyaltyapp.visit_events",
    needs=["events"],
    default=False,
    describe="Each visit is published as a family event.",
)
