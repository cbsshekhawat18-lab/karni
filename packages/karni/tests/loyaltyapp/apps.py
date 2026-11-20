"""App configuration for the loyalty test part."""

from __future__ import annotations

from django.apps import AppConfig


class LoyaltyAppConfig(AppConfig):
    """Configuration for :mod:`tests.loyaltyapp` (app label ``loyaltyapp``)."""

    name = "tests.loyaltyapp"
    label = "loyaltyapp"
    verbose_name = "Karni loyalty test part"
