"""System checks of karni-commerce (``karni.COM001``)."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from karni.exceptions import check_error

__all__ = ["people_installed"]


def people_installed(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """``karni.COM001``: commerce needs the people contract (``karni.people``)."""
    if apps.is_installed("karni.people"):
        return []
    return [
        check_error(
            "COM001",
            "karni-commerce is installed without the people contract: every order names the "
            "person who bought it (karni.people).",
            hint="Set KARNI_PEOPLE = True above karni_settings(globals()) in your settings, "
            "then run migrate.",
        )
    ]
