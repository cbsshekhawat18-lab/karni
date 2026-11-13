"""Experimental. System checks for demo mode (``karni check``, ``manage.py check``).

* ``E950``: ``KARNI_DEMO_ACCOUNTS`` is malformed (a bad entry, an unknown key,
  a login listed twice).
* ``E953``: ``KARNI_DEMO_MODE`` is on but ``DemoWriteGuardMiddleware`` is not in
  ``MIDDLEWARE``, so nothing stops a visitor from writing.

Both run while the ``karni.demo`` app is installed. Override / escape hatch: a project
with its own guard lists it in ``KARNI_DEMO_GUARD_MIDDLEWARE`` (a list of dotted paths).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core import checks

from karni.demo import conf
from karni.errorcodes import get as registry_entry
from karni.exceptions import KarniValueError, check_error

GUARD = "karni.demo.middleware.DemoWriteGuardMiddleware"


def _fix(code: str) -> str:
    entry = registry_entry(code)
    return entry.fix if entry is not None else "See the linked page."


@checks.register()
def check_demo_mode(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """``E950`` and ``E953`` (see the module docstring)."""
    found: list[checks.CheckMessage] = []
    try:
        conf.accounts()
    except KarniValueError as exc:
        found.append(check_error("E950", str(exc), hint=_fix("E950")))
    if conf.demo_mode():
        accepted = {GUARD, *getattr(settings, "KARNI_DEMO_GUARD_MIDDLEWARE", ())}
        if not accepted.intersection(settings.MIDDLEWARE):
            found.append(
                check_error(
                    "E953",
                    "KARNI_DEMO_MODE is on, but the demo write guard is not in MIDDLEWARE, so "
                    "every visitor can write.",
                    hint=_fix("E953"),
                )
            )
    return found
