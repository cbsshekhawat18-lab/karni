"""``KARNI_ADMIN_LOGO`` → the ``UNFOLD`` logo entries, resolved on every admin request.

The admin carries no logo unless a project asks for one: ``"karni"`` uses
the mark shipped in ``karni.admin``'s static files, a mapping names the
project's own static paths.

``karni_settings()`` sets ``UNFOLD["SITE_LOGO"]`` and ``UNFOLD["SITE_ICON"]``
to :func:`site_logo` and :func:`site_icon`. Unfold calls them with the request
each time it renders a page, and they read ``settings.KARNI_ADMIN_LOGO`` then,
so the setting takes effect wherever ``settings.py`` assigns it, before or
after the call. They also call ``static()`` only then, after the staticfiles
storage is configured. The login screen shows the same logo
(``karni_admin/login.html``, see :mod:`karni.admin.apps`).

Override / escape hatch: assign ``UNFOLD["SITE_LOGO"]`` / ``UNFOLD["SITE_ICON"]``
yourself (a URL, a ``{"light": ..., "dark": ...}`` mapping or a callable
taking the request) and unfold uses yours instead.
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


def logo_paths(setting: Any) -> dict[str, str] | None:
    """The ``light``, ``dark`` and ``icon`` static paths ``setting`` declares, or ``None``.

    :raises KarniImproperlyConfigured: ``E303`` when ``setting`` is neither
        ``"karni"`` nor a mapping with at least ``"light"``.
    """
    if not setting:
        return None
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
    return {"light": light, "dark": paths.get("dark", light), "icon": paths.get("icon", light)}


def unfold_logo_entries(setting: Any) -> dict[str, Any]:
    """``SITE_LOGO`` and ``SITE_ICON`` for ``UNFOLD`` fixed to ``setting``, or ``{}`` for none.

    ``karni_settings()`` uses :func:`site_logo` and :func:`site_icon`
    instead, which follow the setting's final value. This function suits a
    project that builds ``UNFOLD`` itself for one fixed logo.
    """
    paths = logo_paths(setting)
    if paths is None:
        return {}
    return {
        "SITE_LOGO": {"light": _static(paths["light"]), "dark": _static(paths["dark"])},
        "SITE_ICON": {"light": _static(paths["icon"]), "dark": _static(paths["icon"])},
    }


def _current_paths() -> dict[str, str] | None:
    from django.conf import settings

    return logo_paths(getattr(settings, "KARNI_ADMIN_LOGO", None))


def site_logo(request: Any) -> dict[str, str] | None:
    """``UNFOLD["SITE_LOGO"]``: the light and dark logo URLs for ``KARNI_ADMIN_LOGO`` now."""
    from django.templatetags.static import static

    paths = _current_paths()
    if paths is None:
        return None
    return {"light": static(paths["light"]), "dark": static(paths["dark"])}


def site_icon(request: Any) -> dict[str, str] | None:
    """``UNFOLD["SITE_ICON"]``: the small icon URL for ``KARNI_ADMIN_LOGO`` now."""
    from django.templatetags.static import static

    paths = _current_paths()
    if paths is None:
        return None
    icon = static(paths["icon"])
    return {"light": icon, "dark": icon}
