"""``KARNI_ADMIN_LOGO`` → the ``UNFOLD`` logo entries (``karni_settings()`` applies them).

The admin carries no logo unless a project asks for one: ``"karni"`` uses
the mark shipped in ``karni.admin``'s static files, a mapping names the
project's own static paths. Unfold reads a callable per colour scheme, so
the entries resolve ``static()`` lazily, after the staticfiles storage is
configured.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from karni.exceptions import KarniImproperlyConfigured

KARNI_MARK: Final[dict[str, str]] = {
    "light": "karni/brand/karni-mark.svg",
    "dark": "karni/brand/karni-mark-light.svg",
    "icon": "karni/brand/karni-mark-simple.svg",
}


def _static(path: str) -> Callable[[Any], str]:
    def resolve(request: Any) -> str:
        from django.templatetags.static import static

        return static(path)

    return resolve


def unfold_logo_entries(setting: Any) -> dict[str, Any]:
    """``SITE_LOGO`` and ``SITE_ICON`` for ``UNFOLD``, or ``{}`` when no logo is wanted."""
    if not setting:
        return {}
    paths: Mapping[str, str]
    if setting == "karni":
        paths = KARNI_MARK
    elif isinstance(setting, Mapping) and setting.get("light"):
        paths = {str(key): str(value) for key, value in setting.items()}
    else:
        raise KarniImproperlyConfigured(
            f"KARNI_ADMIN_LOGO must be 'karni' or {{'light': <static path>, 'dark': ..., "
            f"'icon': ...}} with at least 'light', got {setting!r}.",
            code="E303",
        )
    light = paths["light"]
    dark = paths.get("dark", light)
    icon = paths.get("icon", light)
    return {
        "SITE_LOGO": {"light": _static(light), "dark": _static(dark)},
        "SITE_ICON": {"light": _static(icon), "dark": _static(icon)},
    }
