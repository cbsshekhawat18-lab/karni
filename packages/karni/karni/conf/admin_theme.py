"""``KARNI_ADMIN_THEME`` → ``UNFOLD["THEME"]``, resolved on every admin request.

The admin is light by default: ``"light"`` pins unfold's light palette and
hides its light / dark / system switch, so every screen and screenshot of the
admin looks the same. ``"dark"`` pins the dark palette, and ``"auto"`` brings
the switch back (the admin then follows the system preference).

``karni_settings()`` sets ``UNFOLD["THEME"]`` to :func:`theme`. Unfold calls it
with the request each time it renders a page, and it reads
``settings.KARNI_ADMIN_THEME`` then, so the setting takes effect wherever
``settings.py`` assigns it, before or after the call.

Override / escape hatch: assign ``UNFOLD["THEME"]`` yourself (``"light"``,
``"dark"``, ``None`` for the switch, or a callable taking the request) and
unfold uses yours instead.
"""

from __future__ import annotations

from typing import Any, Final, Literal

AdminTheme = Literal["light", "dark", "auto"]

THEMES: Final[tuple[str, ...]] = ("light", "dark", "auto")
DEFAULT: Final = "light"


def theme_value(value: Any) -> str | None:
    """Unfold's ``THEME`` for a ``KARNI_ADMIN_THEME`` value: ``"light"``, ``"dark"`` or ``None``.

    ``None`` is unfold's switch (``"auto"``). An unknown value falls back to the
    default: ``karni check`` and startup validation report it.
    """
    chosen = str(value).strip().lower() if value not in (None, "") else DEFAULT
    if chosen not in THEMES:
        chosen = DEFAULT
    return None if chosen == "auto" else chosen


def theme(request: Any) -> str | None:
    """``UNFOLD["THEME"]`` entry: ``settings.KARNI_ADMIN_THEME`` as unfold reads it."""
    from django.conf import settings

    return theme_value(getattr(settings, "KARNI_ADMIN_THEME", DEFAULT))
