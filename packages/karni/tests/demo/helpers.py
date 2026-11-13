"""Seeders and URLs for the demo mode tests (``KARNI_DEMO_SEEDER`` points here)."""

from __future__ import annotations

from karni.seeding import seed


def seed_venues(value: int) -> str:
    """The demo's reseed in these tests: three venues, so the suite seeds only what it checks."""
    return seed(models=["testapp.Venue"], count=3, seed=value, reset=True).render()
