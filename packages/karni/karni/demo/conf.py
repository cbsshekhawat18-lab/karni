"""Experimental. Demo mode's settings, read on every call, and the demo accounts.

Settings (all optional, ``KARNI_DEMO_MODE`` is off by default):

* ``KARNI_DEMO_MODE`` (False): whether the demo rules apply. Env ``KARNI_DEMO_MODE``,
  or ``DEMO_MODE`` as the short name a Blueprint uses.
* ``KARNI_DEMO_ACCOUNTS``: the demo accounts, a list of dicts (below). Unset, one
  account: the one ``karni seed`` makes (``demo@example.com``, staff and superuser,
  every role the API names).
* ``KARNI_DEMO_SEED`` (42): the fixed seed every reset uses. Env ``DEMO_SEED``.
* ``KARNI_DEMO_RESET_HOURS`` (24): hours between two resets. Env ``DEMO_RESET_HOURS``.
* ``KARNI_DEMO_RESET_CHECK_SECONDS`` (60): how often a worker asks whether a reset is due.
* ``KARNI_DEMO_RESET_STAMP``: where the last reset is recorded. Default: next to the
  SQLite database, else ``<BASE_DIR>/data/demo-reset.json``.
* ``KARNI_DEMO_KEEP_APPS``: app labels whose rows a reset keeps (see
  :data:`karni.demo.reset.KEEP_APPS`).
* ``KARNI_DEMO_OPEN_PATHS`` (``[]``): paths anyone may write to, besides the sign-in,
  refresh, sign-out and accept-terms paths. An exact path, or a prefix ending in ``*``.
* ``KARNI_DEMO_LOCKED_PATHS`` (``[]``): paths demo accounts may not write to, besides
  the accounts API and the admin's user and role tables. Same pattern rule.
* ``KARNI_DEMO_WRITE_RULE``: dotted path of ``f(request) -> Refusal | None`` that
  replaces :func:`karni.demo.guard.refusal`.
* ``KARNI_DEMO_SEEDER``: dotted path of ``f(seed: int) -> str`` that reseeds the data
  (it runs inside the reset's transaction, after the tables are emptied). Default:
  ``karni seed --reset`` with the fixed seed.
* ``KARNI_DEMO_APP_INDEX``: the built React app's ``index.html`` that :mod:`karni.demo.views`
  serves. Env ``DEMO_APP_INDEX``. Default ``<BASE_DIR>/frontend/dist/index.html``.
* ``KARNI_DEMO_APP_RESERVED``: first path segments the app's page never answers, added to
  the defaults (``api``, ``health``, ``healthz``, ``readyz``, the admin, static and media).

One entry of ``KARNI_DEMO_ACCOUNTS``::

    {"login": "customer@example.com",   # required, the user model's login field
     "label": "Customer",               # shown on the sign-in pages (default: the login)
     "can": "Place orders.",            # what it can do, shown beside the login
     "roles": ["customer"],             # or "all" (every role the API names)
     "staff": False, "superuser": False,
     "password": "karni-password"}      # default: karni's seed password

Override / escape hatch: :func:`accounts` is the only reader of the list, and every
function here reads ``django.conf.settings`` on each call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from django.conf import settings
from django.contrib.auth import get_user_model

from karni.exceptions import KarniValueError

__all__ = [
    "ALL_ROLES",
    "DemoAccount",
    "accounts",
    "app_index",
    "default_accounts",
    "demo_mode",
    "find_account",
    "is_demo",
    "keep_apps",
    "matches",
    "reset_check_seconds",
    "seed_login",
    "reset_hours",
    "seed_value",
    "stamp_path",
]

#: ``roles`` value meaning every role the routed API names (what ``karni seed`` gives).
ALL_ROLES: Final = "all"

_KEYS: Final = frozenset({"login", "label", "can", "roles", "staff", "superuser", "password"})


@dataclass(frozen=True)
class DemoAccount:
    """One public demo account: who it is, what it can do, how to sign in."""

    login: str
    label: str
    can: str = ""
    #: Role names, or ``None`` for every role the API names (``"all"``).
    roles: tuple[str, ...] | None = ()
    staff: bool = False
    superuser: bool = False
    #: ``None``: karni's seed password (:data:`karni.testing.factories.DEFAULT_PASSWORD`).
    password: str | None = None

    @property
    def secret(self) -> str:
        """The password the account has, and the sign-in notice shows."""
        if self.password is not None:
            return self.password
        from karni.testing.factories import DEFAULT_PASSWORD

        return str(DEFAULT_PASSWORD)


def demo_mode() -> bool:
    """Whether the demo rules apply (``KARNI_DEMO_MODE``, read per call so tests can switch it)."""
    return bool(getattr(settings, "KARNI_DEMO_MODE", False))


def seed_login() -> str:
    """The login ``karni seed`` gives its demo user: ``demo@example.com``, or ``demo``."""
    from django.db import models

    from karni.seeding import DEMO_LOGIN

    model = get_user_model()
    field = model._meta.get_field(model.USERNAME_FIELD)
    return str(DEMO_LOGIN) if isinstance(field, models.EmailField) else "demo"


def default_accounts() -> list[DemoAccount]:
    """The one account used while ``KARNI_DEMO_ACCOUNTS`` is unset: ``karni seed``'s."""
    return [
        DemoAccount(
            login=seed_login(),
            label="Demo account",
            can="Read and change all data.",
            roles=None,
            staff=True,
            superuser=True,
        )
    ]


def parse_account(entry: Any, index: int) -> DemoAccount:
    """One entry of the setting as a :class:`DemoAccount`; ``E950`` names what is wrong."""
    where = f"KARNI_DEMO_ACCOUNTS[{index}]"
    if not isinstance(entry, dict):
        raise KarniValueError(f"{where} is {entry!r}, not a dict.", code="E950")
    unknown = sorted(set(entry) - _KEYS)
    if unknown:
        raise KarniValueError(
            f"{where} has unknown keys {unknown}: use {sorted(_KEYS)}.", code="E950"
        )
    login = entry.get("login")
    if not isinstance(login, str) or not login.strip():
        raise KarniValueError(f"{where} needs a non-empty string 'login'.", code="E950")
    roles = entry.get("roles", ())
    if roles == ALL_ROLES:
        chosen: tuple[str, ...] | None = None
    elif isinstance(roles, (list, tuple)) and all(isinstance(r, str) and r for r in roles):
        chosen = tuple(roles)
    else:
        raise KarniValueError(
            f"{where}['roles'] is {roles!r}: use a list of role names, or 'all'.", code="E950"
        )
    password = entry.get("password")
    if password is not None and (not isinstance(password, str) or not password):
        raise KarniValueError(f"{where}['password'] must be a non-empty string.", code="E950")
    return DemoAccount(
        login=login.strip(),
        label=str(entry.get("label") or login.strip()),
        can=str(entry.get("can") or ""),
        roles=chosen,
        staff=bool(entry.get("staff", False)),
        superuser=bool(entry.get("superuser", False)),
        password=password,
    )


def accounts() -> list[DemoAccount]:
    """The demo accounts, in the order of ``KARNI_DEMO_ACCOUNTS`` (or the default one).

    Raises ``E950`` when the setting is malformed (``karni check`` reports it first).
    """
    configured = getattr(settings, "KARNI_DEMO_ACCOUNTS", None)
    if not configured:
        return default_accounts()
    if not isinstance(configured, (list, tuple)):
        raise KarniValueError(
            f"KARNI_DEMO_ACCOUNTS is {configured!r}, not a list of dicts.", code="E950"
        )
    found = [parse_account(entry, index) for index, entry in enumerate(configured)]
    seen: set[str] = set()
    for account in found:
        key = account.login.lower()
        if key in seen:
            raise KarniValueError(f"KARNI_DEMO_ACCOUNTS lists {account.login} twice.", code="E950")
        seen.add(key)
    return found


def find_account(login: str) -> DemoAccount | None:
    """The configured demo account with this login (case-insensitive), or ``None``."""
    wanted = str(login or "").lower()
    return next((a for a in accounts() if a.login.lower() == wanted), None)


def is_demo(user: Any) -> bool:
    """Whether ``user`` is one of the demo accounts (matched by its login field)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    login = getattr(user, get_user_model().USERNAME_FIELD, None)
    return find_account(str(login or "")) is not None


def seed_value() -> int:
    """The fixed seed every reset uses (``KARNI_DEMO_SEED``): the same rows each time."""
    return int(getattr(settings, "KARNI_DEMO_SEED", 42))


def reset_hours() -> int:
    """Hours between two resets of the demo data (``KARNI_DEMO_RESET_HOURS``)."""
    return int(getattr(settings, "KARNI_DEMO_RESET_HOURS", 24))


def reset_check_seconds() -> float:
    """How often one worker asks whether a reset is due (``KARNI_DEMO_RESET_CHECK_SECONDS``)."""
    return float(getattr(settings, "KARNI_DEMO_RESET_CHECK_SECONDS", 60))


def keep_apps(default: tuple[str, ...]) -> set[str]:
    """App labels a reset keeps: ``KARNI_DEMO_KEEP_APPS`` or ``default``, plus the user model's."""
    chosen = getattr(settings, "KARNI_DEMO_KEEP_APPS", None)
    return {*(default if chosen is None else chosen), get_user_model()._meta.app_label}


def _base_dir() -> Path:
    return Path(str(getattr(settings, "BASE_DIR", None) or os.getcwd()))


def stamp_path() -> Path:
    """The file holding the last reset's time (``KARNI_DEMO_RESET_STAMP``)."""
    chosen = getattr(settings, "KARNI_DEMO_RESET_STAMP", None)
    if chosen:
        return Path(str(chosen))
    name = str(settings.DATABASES["default"].get("NAME") or "")
    folder = Path(name).parent if name.endswith(".sqlite3") else _base_dir() / "data"
    return folder / "demo-reset.json"


def app_index() -> Path:
    """The built React app's ``index.html`` (``KARNI_DEMO_APP_INDEX``)."""
    chosen = getattr(settings, "KARNI_DEMO_APP_INDEX", None)
    return Path(str(chosen)) if chosen else _base_dir() / "frontend" / "dist" / "index.html"


def matches(path: str, patterns: Any) -> bool:
    """Whether ``path`` equals a pattern, or starts with one that ends in ``*``."""
    for pattern in patterns or ():
        text = str(pattern)
        if text.endswith("*"):
            if path.startswith(text[:-1]):
                return True
        elif path == text:
            return True
    return False
