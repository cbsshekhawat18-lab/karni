"""Experimental. What a business changes without code: the seam to the family's preferences.

Import it as the contract's name, so moving onto the contract is one line per file::

    from karni_commerce import preferences_seam as preferences

The business's details (name, address, the sender of its emails, how money
shows), one settings section per part (``commerce``, ``shop``) and a switch
per email. Code reads them with one call and a typed default::

    from karni_commerce import preferences

    preferences.value("details.name", "")             # a str
    preferences.value("commerce.guest_checkout", True)  # a bool
    preferences.get("shop")                            # the whole section, typed
    preferences.email_on("commerce.order_paid")

and a part declares its section in its own ``<app>/preferences.py``::

    from pydantic import Field
    from karni_commerce import preferences_seam as preferences


    @preferences.section("shop", title="Shop", change="role:shop-manager")
    class ShopPreferences(preferences.Section):
        low_stock: int = Field(3, ge=0, le=1000, description="...")

**The seam.** These are the names of the family's preferences contract
(``karni.preferences``: ``Section``, ``section``, ``value``, ``get``,
``details``, ``sender``, ``email_on``, ``save_details``, ``save_section``,
``switch``, ``can_change``, ``override``, ``PreferenceRefused``), with the
same order of reading (a test's override, ``KARNI_PREFERENCES_LOCKED``, what
someone saved, ``KARNI_PREFERENCES_DEFAULTS``, the declared default) and the
same API (``/api/preferences/``, :class:`karni_commerce.viewsets.PreferenceViewSet`).
Until that contract is installed, this module keeps the values itself, in
:class:`~karni_commerce.models.Setting`. Once it is, each
``from karni_commerce import preferences_seam as preferences`` becomes
``from karni import preferences``, and this module, the Setting table and its
API go: the sections (``<app>/preferences.py``), the screens and the tests
stay as they are.

What it does not do (the contract does): a logo, connections, the history
page. ``details.currency`` is the project's currency (one per shop), shown
and never changed here.

``MailSource`` is ``karni.mail``'s ``KARNI_MAIL_SOURCE`` for a project with
commerce: an email a business edited (:class:`~karni_commerce.models.EmailTemplate`),
the email switches and the sender come from here.

Override / escape hatch: ``KARNI_PREFERENCES_LOCKED`` and
``KARNI_PREFERENCES_DEFAULTS`` (``{"details": {"name": "..."}, "shop": {...}}``),
:func:`override` in tests, ``replace=True`` on :func:`section`, and
``KARNI_MAIL_SOURCE`` pointing at a source of your own.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from email.utils import formataddr
from typing import Any, Literal

from django.conf import settings
from django.core.signals import request_finished, request_started
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as ModelError

__all__ = [
    "CURRENCY_DISPLAYS",
    "DETAIL_FIELDS",
    "Details",
    "MailSource",
    "PreferenceRefused",
    "Section",
    "SectionSpec",
    "can_change",
    "details",
    "email_on",
    "find_section",
    "get",
    "locked_names",
    "override",
    "save_details",
    "save_section",
    "section",
    "sections",
    "sender",
    "switch",
    "unregister",
    "value",
]

log = logging.getLogger(__name__)

#: How money shows its currency: the values ``Intl.NumberFormat``'s ``currencyDisplay`` takes.
CURRENCY_DISPLAYS: tuple[tuple[str, str], ...] = (
    ("symbol", "Symbol (US$ 5.00, €5.00)"),
    ("narrowSymbol", "Narrow symbol ($5.00)"),
    ("code", "Code (USD 5.00)"),
    ("name", "Name (5.00 US dollars)"),
)

#: The details, in the order the Settings page shows them.
DETAIL_FIELDS: tuple[str, ...] = (
    "name",
    "legal_name",
    "address",
    "phone",
    "email",
    "tax_number",
    "sender_name",
    "sender_email",
    "reply_to",
    "time_zone",
    "language",
    "currency",
    "currency_display",
)

#: Group names a section may not take.
RESERVED = frozenset({"details", "connections", "emails"})


class Section(BaseModel):
    """Experimental. The base of a part's settings section: every field has a default."""

    model_config = ConfigDict(extra="ignore")


class Details(Section):
    """Experimental. The business's own details, for the site, its emails and invoices."""

    name: str = Field("", max_length=200, description="The business's name.")
    legal_name: str = Field("", max_length=200, description="The registered name, on invoices.")
    address: str = Field("", max_length=1000, description="The address, on invoices.")
    phone: str = Field("", max_length=50, description="A phone number customers can call.")
    email: str = Field("", max_length=254, description="Where customers write to.")
    tax_number: str = Field("", max_length=60, description="The tax number, on invoices.")
    sender_name: str = Field("", max_length=200, description="The name emails come from.")
    sender_email: str = Field("", max_length=254, description="The address emails come from.")
    reply_to: str = Field("", max_length=254, description="Where answers to emails go.")
    time_zone: str = Field("", max_length=64, description="Blank: the project's time zone.")
    language: str = Field("", max_length=16, description="Blank: the project's language.")
    currency: str = Field("", max_length=3, description="The project's currency.")
    currency_display: Literal["symbol", "narrowSymbol", "code", "name"] = Field(
        "symbol", description="How money shows the currency."
    )

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PreferenceRefused(Exception):  # noqa: N818 - the contract's name
    """Experimental. A change refused: ``code`` E323 (a value refused, ``errors`` by field),
    E324 (the deployment locks it) or E325 (no such name)."""

    def __init__(self, message: str, code: str = "E323", errors: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.errors = dict(errors or {})


@dataclass(frozen=True)
class SectionSpec:
    """Experimental. One part's section: its key, title, model and who may change it."""

    key: str
    title: str
    model: type[Section]
    change: str = ""
    describe: str = ""
    version: int = 1

    def schema(self) -> dict[str, Any]:
        return self.model.model_json_schema()

    def defaults(self) -> dict[str, Any]:
        return self.model().model_dump(mode="json")


_SECTIONS: dict[str, SectionSpec] = {}
_OVERRIDES: list[dict[str, dict[str, Any]]] = []


def section(
    key: str,
    *,
    title: str,
    change: str = "",
    describe: str = "",
    version: int = 1,
    replace: bool = False,
) -> Callable[[type[Any]], type[Any]]:
    """Experimental. Declare a part's settings section (a decorator on a :class:`Section`).

    ``change``: who else may change it, a permission key or ``role:<slug>``.
    """
    if key in RESERVED:
        raise ValueError(f"{key!r} is reserved: name the section after its part.")

    def wrap(model: type[Any]) -> type[Any]:
        if key in _SECTIONS and not replace and _SECTIONS[key].model is not model:
            raise ValueError(f"The section {key!r} is declared twice (replace=True replaces).")
        model().model_dump()  # every field has a default
        first_line = (model.__doc__ or "").strip().splitlines()
        _SECTIONS[key] = SectionSpec(
            key=key,
            title=title,
            model=model,
            change=change,
            describe=describe or (first_line[0] if first_line else ""),
            version=version,
        )
        return model

    return wrap


def unregister(*, section: str) -> None:
    """Experimental. Take a section out (a project then declares its own)."""
    _SECTIONS.pop(section, None)


def _discover() -> None:
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("preferences")


def sections() -> list[SectionSpec]:
    """Experimental. Every declared section, by title."""
    _discover()
    return sorted(_SECTIONS.values(), key=lambda spec: (spec.title, spec.key))


def find_section(key: str) -> SectionSpec | None:
    _discover()
    return _SECTIONS.get(key)


# -- reading ---------------------------------------------------------------------------------


def _setting(name: str) -> dict[str, dict[str, Any]]:
    found = getattr(settings, name, None) or {}
    return {str(group): dict(values or {}) for group, values in dict(found).items()}


_REQUEST = threading.local()


def _start(**kwargs: Any) -> None:
    _REQUEST.rows = None
    _REQUEST.on = True


def _finish(**kwargs: Any) -> None:
    _REQUEST.rows = None
    _REQUEST.on = False


request_started.connect(_start, dispatch_uid="karni_commerce.preferences.start")
request_finished.connect(_finish, dispatch_uid="karni_commerce.preferences.finish")


def _stored() -> dict[str, dict[str, Any]]:
    """What someone saved, by group: read once per request (and on every call outside one)."""
    from karni_commerce.models import Setting

    if getattr(_REQUEST, "on", False) and getattr(_REQUEST, "rows", None) is not None:
        return dict(_REQUEST.rows)
    rows = {row.group: dict(row.values or {}) for row in Setting.objects.all()}
    if getattr(_REQUEST, "on", False):
        _REQUEST.rows = rows
    return rows


def _layers(group: str, stored: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The values of ``group``, the strongest last: defaults, saved, locked, a test's."""
    saved = dict((stored if stored is not None else _stored()).get(group, {}))
    if group == "details":
        saved = {name: v for name, v in saved.items() if v not in ("", None)}
    merged: dict[str, Any] = {}
    merged.update(_setting("KARNI_PREFERENCES_DEFAULTS").get(group, {}))
    merged.update(saved)
    merged.update(_setting("KARNI_PREFERENCES_LOCKED").get(group, {}))
    for layer in _OVERRIDES:
        merged.update(layer.get(group, {}))
    return merged


def _valid[S: Section](model: type[S], values: Mapping[str, Any], group: str) -> S:
    """``values`` as ``model``: a value the model now refuses gives way to its default."""
    kept = {name: v for name, v in values.items() if name in model.model_fields}
    while True:
        try:
            return model(**kept)
        except ModelError as exc:
            wrong = {str(error["loc"][0]) for error in exc.errors() if error.get("loc")}
            if not wrong & set(kept):
                return model()
            for name in wrong & set(kept):
                log.warning("The saved %s.%s is refused now: the default is used.", group, name)
                kept.pop(name)


def details() -> Details:
    """Experimental. The business's details, with the blanks read as the project's own."""
    from karni_commerce import conf

    found = _valid(Details, _layers("details"), "details")
    filled = {
        "time_zone": found.time_zone or str(getattr(settings, "TIME_ZONE", "") or ""),
        "language": found.language or str(getattr(settings, "LANGUAGE_CODE", "") or ""),
        "sender_name": found.sender_name or found.name,
        "currency": conf.currency().upper(),
    }
    return found.model_copy(update=filled)


def get(key: str | type[Section]) -> Any:
    """Experimental. A section's values, as its model (a key, or the model itself)."""
    if isinstance(key, type):
        spec = next((s for s in sections() if s.model is key), None)
        if spec is None:
            return key()
        key = spec.key
    spec = find_section(key)
    if spec is None:
        raise PreferenceRefused(f"No section {key!r}.", code="E325")
    return _valid(spec.model, _layers(spec.key), spec.key)


def email_on(kind: str) -> bool:
    """Experimental. Whether the email ``kind`` goes out (on unless switched off)."""
    from karni.mail import find_kind

    declared = find_kind(kind)
    if declared is not None and not declared.switchable:
        return True
    return bool(_layers("emails").get(kind, True))


def value[T](path: str, default: T) -> T:
    """Experimental. One value by its path (``details.name``, ``shop.low_stock``,
    ``emails.<kind>``), as the type of ``default``. It never fails: a section nobody
    declared, or a value that cannot be read as that type, gives ``default``."""
    group, _, name = path.partition(".")
    found: Any = None
    if group == "details":
        found = getattr(details(), name, None)
    elif group == "emails":
        found = email_on(name)
    elif group == "connections":
        found = None
    elif find_section(group) is not None:
        found = getattr(get(group), name, None)
    else:
        found = _layers(group).get(name)
    return _as(default, found, path)


def _as[T](default: T, found: Any, path: str) -> T:
    if found is None:
        return default
    try:
        if isinstance(default, bool):
            if isinstance(found, str):
                return found.strip().lower() in ("1", "true", "yes", "on")  # type: ignore[return-value]
            return bool(found)  # type: ignore[return-value]
        if isinstance(default, int):
            return int(found)  # type: ignore[return-value]
        if isinstance(default, float):
            return float(found)  # type: ignore[return-value]
        if isinstance(default, Decimal):
            return Decimal(str(found))  # type: ignore[return-value]
        if isinstance(default, str):
            return str(found)  # type: ignore[return-value]
    except (TypeError, ValueError, InvalidOperation):
        log.warning("%s cannot be read as %s: the default is used.", path, type(default).__name__)
        return default
    return found


def sender() -> str | None:
    """Experimental. The ``From`` of the project's emails, or ``None`` (``DEFAULT_FROM_EMAIL``)."""
    found = details()
    if not found.sender_email:
        return None
    return formataddr((found.sender_name or found.name, found.sender_email))


def locked_names(group: str) -> set[str]:
    return set(_setting("KARNI_PREFERENCES_LOCKED").get(group, {}))


# -- changing --------------------------------------------------------------------------------


def can_change(user: Any, target: str) -> bool:
    """Experimental. Whether ``user`` may change ``target``: ``details``, ``emails`` or a
    section. ``karni_commerce.setting:change`` changes every one, and a section's
    ``change`` (a permission key or ``role:<slug>``) lets its own people change it."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or user.can("karni_commerce.setting:change"):
        return True
    spec = find_section(target) if target not in RESERVED else None
    if spec is None or not spec.change:
        return False
    if spec.change.startswith("role:"):
        from karni.accounts.permissions import user_roles

        return spec.change.removeprefix("role:") in set(user_roles(user))
    return bool(user.can(spec.change))


def _save(group: str, changes: Mapping[str, Any], model: type[Section] | None) -> dict[str, Any]:
    from django.db import transaction

    from karni_commerce.models import Setting

    locked = locked_names(group) | ({"currency"} if group == "details" else set())
    refused = sorted(name for name in changes if name in locked)
    if refused:
        raise PreferenceRefused(f"The deployment fixes {', '.join(refused)}.", code="E324")
    if model is not None:
        unknown = sorted(name for name in changes if name not in model.model_fields)
        if unknown:
            raise PreferenceRefused(f"No such setting: {', '.join(unknown)}.", code="E325")
    with transaction.atomic():
        row, _ = Setting.objects.select_for_update().get_or_create(group=group)
        values = dict(row.values or {})
        for name, given in changes.items():
            if given is None or (group == "details" and given == ""):
                values.pop(name, None)
            else:
                values[name] = given
        if model is not None:
            try:
                checked = model(**{**_layers(group, {group: values}), **values})
            except ModelError as exc:
                errors: dict[str, list[str]] = {}
                for error in exc.errors():
                    name = str(error["loc"][0]) if error.get("loc") else "non_field_errors"
                    errors.setdefault(name, []).append(str(error["msg"]))
                raise PreferenceRefused("Some values are refused.", errors=errors) from None
            dumped = checked.model_dump(mode="json")
            values = {name: dumped[name] for name in values if name in dumped}
        row.values = values
        row.save()
    _REQUEST.rows = None
    return values


def save_details(values: Mapping[str, Any], *, user: Any = None) -> Details:
    """Experimental. Change some details. A blank value goes back to the default."""
    _save("details", values, Details)
    return details()


def save_section(key: str, values: Mapping[str, Any], *, user: Any = None) -> Any:
    """Experimental. Change some fields of a section. ``None`` puts one back to its default."""
    spec = find_section(key)
    if spec is None:
        raise PreferenceRefused(f"No section {key!r}.", code="E325")
    _save(key, values, spec.model)
    return get(key)


def switch(kind: str, name: str, on: bool | None, *, user: Any = None) -> bool:
    """Experimental. Switch an email on or off (``None``: back to on). ``kind`` is ``email``."""
    from karni.mail import find_kind

    if kind != "email":
        raise PreferenceRefused("Only emails have switches here.", code="E325")
    declared = find_kind(name)
    if declared is None:
        raise PreferenceRefused(f"No email {name!r}.", code="E325")
    if not declared.switchable and on is False:
        raise PreferenceRefused(f"{declared.title} always goes out.", code="E323")
    _save("emails", {name: on}, None)
    return email_on(name)


@contextmanager
def override(**groups: Mapping[str, Any]) -> Iterator[None]:
    """Experimental. Set values for a block, over locks and saved values (tests)."""
    _OVERRIDES.append({group: dict(values) for group, values in groups.items()})
    try:
        yield
    finally:
        _OVERRIDES.pop()


class MailSource:
    """Experimental. ``karni.mail``'s source: edited emails, their switches, the sender.

    It answers nothing (the files, every email on) while ``karni_commerce`` is not in
    ``INSTALLED_APPS``: the package's settings fragment may be there without the app.
    """

    @staticmethod
    def _on() -> bool:
        from django.apps import apps

        return apps.is_installed("karni_commerce")

    def template(self, kind: str) -> Any:
        from karni.mail import EditedTemplate

        if not self._on():
            return None
        from karni_commerce.models import EmailTemplate

        row = EmailTemplate.objects.filter(kind=kind).first()
        return EditedTemplate(row.subject, row.text) if row is not None else None

    def enabled(self, kind: str) -> bool:
        return email_on(kind) if self._on() else True

    def sender(self) -> str | None:
        return sender() if self._on() else None
