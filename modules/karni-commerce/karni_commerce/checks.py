"""System checks of karni-commerce (``karni.COM001``)."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks

__all__ = ["people_installed"]


def people_installed(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """``karni.COM001``: commerce needs the people contract (``karni.people``)."""
    if apps.is_installed("karni.people"):
        return []
    return [
        checks.Error(
            "karni-commerce is installed without the people contract: every order names the "
            "person who bought it (karni.people).",
            hint="Set KARNI_PEOPLE = True above karni_settings(globals()) in your settings, "
            "then run migrate. See karni explain COM001.",
            id="karni.COM001",
        )
    ]
