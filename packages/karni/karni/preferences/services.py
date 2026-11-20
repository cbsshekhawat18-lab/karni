"""Experimental. Reading and changing preferences: one call to read, the locks always win.

Reading, from any part, whether or not ``karni.preferences`` is installed::

    from karni import preferences

    hours = preferences.value("bookings.refund_notice_hours", 0)    # an int
    name = preferences.value("details.name", "")                   # a str
    if preferences.active("crm.deal_timeline"):                     # a connection
        ...
    section = preferences.get(BookingPreferences)                  # the whole section

A value is, in this order: the deployment's lock (``KARNI_PREFERENCES_LOCKED``),
what someone saved in Settings, the deployment's default
(``KARNI_PREFERENCES_DEFAULTS``), then the declared default. Without the app,
or without the part that declares it, :func:`value` returns the lock or the
default it is given, so a part works alone. Inside a request each table is
read once and kept until a change.

Changing, from the API, the admin or code: :func:`save_details`,
:func:`save_section` and :func:`switch` refuse a locked value (``E324``), an
unknown name (``E325``) and a value its field refuses (``E323``). Each
change is audited with who made it.

Override / escape hatch: ``KARNI_PREFERENCES_LOCKED`` and
``KARNI_PREFERENCES_DEFAULTS`` per deployment, and :func:`override` in tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final, overload

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import TypeAdapter, ValidationError

from karni.exceptions import KarniLookupError, KarniValueError
from karni.preferences.registry import (
    RESERVED,
    Section,
    SectionSpec,
    find_connection,
    find_section,
)

__all__ = [
    "APP",
    "PreferenceRefused",
    "active",
    "can_change",
    "details",
    "email_on",
    "forget",
    "get",
    "installed",
    "locked",
    "locked_names",
    "locks",
    "override",
    "save_details",
    "save_section",
    "sender",
    "switch",
    "switch_position",
    "validate_section_values",
    "value",
]

logger = logging.getLogger("karni.preferences")

APP: Final = "karni.preferences"

#: The tables read in this request, by name (``None`` outside a request: no cache).
_CACHE: ContextVar[dict[str, Any] | None] = ContextVar("karni_preferences_cache", default=None)
#: Values :func:`override` sets, by group then name, over everything else.
_OVERRIDES: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "karni_preferences_overrides", default=None
)


class PreferenceRefused(KarniValueError):
    """Experimental. A change was refused: ``code`` says why, ``errors`` maps fields to messages."""

    def __init__(self, message: str, *, code: str, errors: Mapping[str, str] | None = None) -> None:
        super().__init__(message, code=code)
        self.errors: dict[str, str] = dict(errors or {})


def installed() -> bool:
    """Is ``karni.preferences`` installed?"""
    return apps.is_installed(APP)


# the deployment's settings


def _setting(name: str) -> dict[str, dict[str, Any]]:
    found = getattr(settings, name, None) or {}
    return found if isinstance(found, dict) else {}


def locks() -> dict[str, dict[str, Any]]:
    """``KARNI_PREFERENCES_LOCKED``: ``{"details": {...}, "<section>": {...}, ...}``."""
    return _setting("KARNI_PREFERENCES_LOCKED")


def _defaults() -> dict[str, dict[str, Any]]:
    return _setting("KARNI_PREFERENCES_DEFAULTS")


def _group(source: Mapping[str, Any], group: str) -> Mapping[str, Any]:
    found = source.get(group)
    return found if isinstance(found, Mapping) else {}


def _over(group: str) -> Mapping[str, Any]:
    found = _OVERRIDES.get()
    return (found or {}).get(group, {})


def locked_names(group: str) -> list[str]:
    """The names the deployment fixes in ``group`` (``"details"``, a section key, ...)."""
    return sorted(str(name) for name in _group(locks(), group))


def locked(group: str, name: str) -> bool:
    """Does the deployment fix ``group.name`` (``locked("details", "name")``)?"""
    return name in _group(locks(), group)


# the per-request cache


def _cached[T](key: str, load: Callable[[], T]) -> T:
    found = _CACHE.get()
    if found is None:
        return load()
    if key not in found:
        found[key] = load()
    return found[key]  # type: ignore[no-any-return]


def start_request(**kwargs: Any) -> None:
    """``request_started``: a new, empty cache for this request."""
    _CACHE.set({})


def end_request(**kwargs: Any) -> None:
    """``request_finished``: no cache outside a request."""
    _CACHE.set(None)


def forget(**kwargs: Any) -> None:
    """Drop what this request read (a change was saved)."""
    found = _CACHE.get()
    if found is not None:
        found.clear()


def _details_row() -> Any:
    from karni.preferences.models import Details

    return _cached("details", lambda: Details.objects.filter(pk=Details.ONE).first())


def _stored_sections() -> dict[str, Any]:
    from karni.preferences.models import SectionValue

    return _cached("sections", lambda: {row.section: row for row in SectionValue.objects.all()})


def _switches() -> dict[tuple[str, str], bool]:
    from karni.preferences.models import Switch

    return _cached(
        "switches", lambda: {(row.kind, row.name): row.on for row in Switch.objects.all()}
    )


# details


@dataclass(frozen=True)
class DetailsView:
    """Experimental. The project's details as they read now (locks and defaults applied)."""

    name: str
    legal_name: str
    address: str
    phone: str
    email: str
    tax_number: str
    sender_name: str
    sender_email: str
    reply_to: str
    time_zone: str
    language: str
    currency: str
    currency_display: str
    logo: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


def _fallback(name: str) -> str:
    if name == "time_zone":
        return str(getattr(settings, "TIME_ZONE", "") or "UTC")
    if name == "language":
        return str(getattr(settings, "LANGUAGE_CODE", "") or "en")
    if name == "currency_display":
        return "symbol"
    return ""


def details() -> DetailsView:
    """Experimental. The project's details: lock, then saved value, then the defaults."""
    from karni.preferences.models import DETAIL_FIELDS

    row = _details_row() if installed() else None
    fixed, given, over = (
        _group(locks(), "details"),
        _group(_defaults(), "details"),
        _over("details"),
    )
    values: dict[str, str] = {}
    for name in DETAIL_FIELDS:
        if name in over:
            values[name] = str(over[name])
        elif name in fixed:
            values[name] = str(fixed[name])
        elif row is not None and name == "logo":
            values[name] = row.logo.url if row.logo else str(given.get("logo", ""))
        elif row is not None and getattr(row, name):
            values[name] = str(getattr(row, name))
        elif name in given:
            values[name] = str(given[name])
        else:
            values[name] = _fallback(name)
    if not values["sender_name"]:
        values["sender_name"] = values["name"]
    return DetailsView(**values)


def sender() -> str | None:
    """Experimental. The ``From`` of the project's emails: ``"Name <address>"``, or ``None``.

    ``None`` (no sender email in the details) leaves Django's ``DEFAULT_FROM_EMAIL``.
    """
    found = details()
    if not found.sender_email:
        return None
    from email.utils import formataddr

    return formataddr((found.sender_name, found.sender_email))


# sections


def validate_section_values(key: str, values: Mapping[str, Any]) -> Section:
    """Experimental. ``values`` over the section's defaults, validated: the section, or E323."""
    spec = _spec(key)
    try:
        return spec.model.model_validate({**spec.defaults(), **dict(values)})
    except ValidationError as exc:
        errors = {
            ".".join(str(part) for part in error["loc"]) or "values": error["msg"]
            for error in exc.errors()
        }
        raise PreferenceRefused(
            f"karni.preferences: the section {key!r} refuses "
            + "; ".join(f"{name}: {msg}" for name, msg in errors.items()),
            code="E323",
            errors=errors,
        ) from None


def _spec(key: str) -> SectionSpec:
    spec = find_section(key)
    if spec is None:
        raise KarniLookupError(
            f"karni.preferences: no section {key!r} is registered. Registered: "
            f"{', '.join(sorted(_registered_keys())) or 'none'}.",
            code="E325",
        )
    return spec


def _registered_keys() -> list[str]:
    from karni.preferences.registry import sections

    return [spec.key for spec in sections()]


def _section_values(spec: SectionSpec) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    if installed():
        row = _stored_sections().get(spec.key)
        if row is not None and isinstance(row.values, dict):
            stored = dict(row.values)
    merged = {
        **spec.defaults(),
        **dict(_group(_defaults(), spec.key)),
        **stored,
    }
    fixed = {**dict(_group(locks(), spec.key)), **dict(_over(spec.key))}
    try:
        spec.model.model_validate({**merged, **fixed})
    except ValidationError as exc:
        # A field saved under an older shape of the section: its default holds.
        bad = {str(error["loc"][0]) for error in exc.errors() if error["loc"]}
        logger.warning(
            "karni.preferences: the section %r holds values its model refuses (%s), and "
            "their defaults are used.",
            spec.key,
            ", ".join(sorted(bad)),
        )
        defaults = spec.defaults()
        merged = {name: defaults.get(name) if name in bad else v for name, v in merged.items()}
    return {**merged, **fixed}


@overload
def get[S: Section](section: type[S]) -> S: ...
@overload
def get(section: str) -> Section: ...
def get(section: str | type[Section]) -> Section:
    """Experimental. The whole section as it reads now: its Pydantic model.

    :param section: the key (``"bookings"``) or the registered class.
    :raises KarniLookupError: E325, no such section is registered.
    """
    key = section if isinstance(section, str) else _class_key(section)
    spec = _spec(key)
    return spec.model.model_validate(_section_values(spec))


def _class_key(model: type[Section]) -> str:
    spec = getattr(model, "spec", None)
    if spec is None:
        raise KarniLookupError(
            f"karni.preferences: {model.__name__} is not a registered section. Decorate it "
            "with @preferences.section('<key>').",
            code="E325",
        )
    return str(spec.key)


# switches: connections and email kinds


def switch_position(kind: str, name: str, default: bool) -> bool:
    """Experimental. A switch as it reads now: override, lock, saved, deployment default."""
    group = "connections" if kind == "connection" else "emails"
    over = _over(group)
    if name in over:
        return bool(over[name])
    fixed = _group(locks(), group)
    if name in fixed:
        return bool(fixed[name])
    if installed():
        saved = _switches().get((kind, name))
        if saved is not None:
            return saved
    given = _group(_defaults(), group)
    if name in given:
        return bool(given[name])
    return default


def active(name: str) -> bool:
    """Experimental. Is the connection ``name`` on: declared, what it needs installed, switched on?

    A connection nobody declared is never active, so a part may ask about its
    own connection whether or not its ``connections.py`` was imported.
    """
    found = find_connection(name)
    if found is None or not found.installed():
        return False
    return switch_position("connection", name, found.default)


def email_on(name: str, default: bool = True) -> bool:
    """Experimental. Does the email kind ``name`` go out? Its switch, else its declared default.

    A message :func:`karni.mail.register_kind` declared not ``switchable`` (a
    sign-in code) always goes out.
    """
    from karni.mail import find_kind
    from karni.preferences.registry import _registry, ensure_discovered

    ensure_discovered()
    message = find_kind(name)
    if message is not None and not message.switchable:
        return True
    declared = _registry.emails.get(name)
    return switch_position("email", name, declared.default if declared else default)


# one call with a typed default


def value[T](path: str, default: T) -> T:
    """Experimental. One value, as the type of ``default``: ``value("bookings.max_seats", 4)``.

    ``path`` is ``"details.<field>"``, ``"<section>.<field>"``,
    ``"connections.<name>"`` (the connection is active) or
    ``"emails.<kind>"`` (the email goes out). Without the app, the section or
    the field, the lock or ``default`` is returned. A value that cannot be read
    as ``default``'s type is logged and ``default`` returned.
    """
    group, _, name = path.partition(".")
    if not name:
        raise KarniValueError(
            f"karni.preferences: value({path!r}) needs '<section>.<field>', for example "
            "'details.name' or 'bookings.refund_notice_hours'.",
            code="E325",
        )
    found: Any
    if group == "details":
        from karni.preferences.models import DETAIL_FIELDS

        if name not in DETAIL_FIELDS:
            return default
        found = getattr(details(), name)
    elif group == "connections":
        found = active(name)
    elif group == "emails":
        found = email_on(name, bool(default) if isinstance(default, bool) else True)
    else:
        spec = find_section(group)
        if spec is None or name not in spec.model.model_fields:
            fixed = {**dict(_group(locks(), group)), **dict(_over(group))}
            return _typed(fixed[name], default, path) if name in fixed else default
        found = _section_values(spec).get(name, default)
    return _typed(found, default, path)


def _typed[T](found: Any, default: T, path: str) -> T:
    if default is None or found is None:
        return found if default is None else default  # type: ignore[no-any-return]
    kind = type(default)
    if type(found) is kind:
        return found  # type: ignore[no-any-return]
    try:
        return TypeAdapter(kind).validate_python(found)  # type: ignore[no-any-return]
    except ValidationError:
        logger.warning(
            "karni.preferences: %s is %r, which is not a %s: the default %r is used.",
            path,
            found,
            kind.__name__,
            default,
        )
        return default


# who may change what


def can_change(user: Any, target: str) -> bool:
    """Experimental. May ``user`` change ``target``: ``details``, ``connections``, ``emails``
    or a section key?

    A section opens to holders of ``preferences.sectionvalue:change`` (every
    section) and of its own ``change``: a permission key or ``role:<slug>``.
    """
    from karni.accounts.permissions import has_role
    from karni.accounts.roles import user_can

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if target == "details":
        return user_can(user, "preferences.details:change")
    if target in ("connections", "emails"):
        return user_can(user, "preferences.switch:change")
    spec = find_section(target)
    if spec is None:
        return False
    if user_can(user, "preferences.sectionvalue:change"):
        return True  # every section
    if spec.change.startswith("role:"):
        return has_role(user, spec.change.removeprefix("role:"))
    return user_can(user, spec.change)


# changes


def _audited(user: Any) -> Any:
    from karni.middleware import current_user

    return current_user(user) if user is not None else _nothing()


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def _refuse_locked(group: str, names: list[str]) -> None:
    fixed = [name for name in names if locked(group, name)]
    if fixed:
        raise PreferenceRefused(
            f"karni.preferences: {', '.join(f'{group}.{n}' for n in fixed)} "
            f"{'is' if len(fixed) == 1 else 'are'} fixed by the deployment "
            "(KARNI_PREFERENCES_LOCKED) and cannot be changed here.",
            code="E324",
            errors={name: "Fixed by the deployment." for name in fixed},
        )


def _require_installed(what: str) -> None:
    if not installed():
        raise KarniLookupError(
            f"karni.preferences: {what} needs 'karni.preferences' in INSTALLED_APPS. Add it "
            "(features: {preferences: true} in karni.yaml) and run migrate.",
            code="E325",
        )


def save_details(
    values: Mapping[str, Any], *, user: Any = None, logo: Any = None, clear_logo: bool = False
) -> Any:
    """Experimental. Change some of the details, audited: the saved ``Details`` row.

    :param values: field names to new values. A blank value goes back to the default.
    :param logo: an uploaded file for the logo, or ``None`` to keep it.
    :raises PreferenceRefused: E323 (unknown field or refused value), E324 (locked).
    """
    from django.core.exceptions import ValidationError as DjangoValidationError

    from karni.preferences.models import DETAIL_FIELDS, Details

    _require_installed("save_details()")
    names = list(values)
    unknown = [name for name in names if name not in DETAIL_FIELDS or name == "logo"]
    if unknown:
        raise PreferenceRefused(
            f"karni.preferences: the details have no field {', '.join(map(repr, unknown))}. "
            f"Fields: {', '.join(f for f in DETAIL_FIELDS if f != 'logo')} (and the logo file).",
            code="E323",
            errors={name: "No such field." for name in unknown},
        )
    _refuse_locked("details", names + (["logo"] if logo is not None or clear_logo else []))
    with transaction.atomic(), _audited(user):
        row = Details.objects.select_for_update().filter(pk=Details.ONE).first() or Details()
        for name in names:
            found = values[name]
            setattr(row, name, "" if found is None else str(found).strip())
        if not row.currency_display:
            row.currency_display = "symbol"
        if logo is not None:
            row.logo = logo
        elif clear_logo:
            row.logo = ""
        try:
            row.full_clean()
        except DjangoValidationError as exc:
            errors = {name: " ".join(msgs) for name, msgs in exc.message_dict.items()}
            raise PreferenceRefused(
                "karni.preferences: the details refuse "
                + "; ".join(f"{name}: {msg}" for name, msg in errors.items()),
                code="E323",
                errors=errors,
            ) from None
        row.updated_by = user if getattr(user, "is_authenticated", False) else None
        row.save()
    forget()
    return row


def save_section(key: str, values: Mapping[str, Any], *, user: Any = None) -> Section:
    """Experimental. Change some fields of a section, audited: the section as it now reads.

    A field given as ``None`` goes back to its default.

    :raises KarniLookupError: E325, no such section.
    :raises PreferenceRefused: E323 (unknown field or refused value), E324 (locked).
    """
    from karni.preferences.models import SectionValue

    _require_installed("save_section()")
    spec = _spec(key)
    unknown = [name for name in values if name not in spec.model.model_fields]
    if unknown:
        raise PreferenceRefused(
            f"karni.preferences: the section {key!r} has no field "
            f"{', '.join(map(repr, unknown))}. Fields: {', '.join(spec.model.model_fields)}.",
            code="E323",
            errors={name: "No such field." for name in unknown},
        )
    _refuse_locked(key, list(values))
    with transaction.atomic(), _audited(user):
        row = SectionValue.objects.select_for_update().filter(section=key).first()
        stored = dict(row.values) if row is not None and isinstance(row.values, dict) else {}
        stored = {name: v for name, v in stored.items() if name in spec.model.model_fields}
        for name, found in values.items():
            if found is None:
                stored.pop(name, None)
            else:
                stored[name] = found
        checked = validate_section_values(key, stored)
        dumped = checked.model_dump(mode="json")
        stored = {name: dumped[name] for name in stored}
        if row is None:
            row = SectionValue(section=key)
        row.values = stored
        row.version = spec.version
        row.updated_by = user if getattr(user, "is_authenticated", False) else None
        row.updated_at = timezone.now()
        row.save()
    forget()
    return get(key)


def switch(kind: str, name: str, on: bool | None, *, user: Any = None) -> bool:
    """Experimental. Switch a connection or an email kind on or off (``None``: back to default).

    :param kind: ``"connection"`` or ``"email"``.
    :returns: the switch's position now.
    :raises KarniLookupError: E325, no such connection or email kind.
    :raises PreferenceRefused: E324, the deployment fixes it. E323, an email that is
        not switchable.
    """
    from karni.preferences.models import Switch
    from karni.preferences.registry import find_email

    _require_installed("switch()")
    declared_email: Any = None
    if kind == "connection":
        declared = find_connection(name)
        group, default = "connections", declared.default if declared else True
    elif kind == "email":
        declared_email = find_email(name)
        declared = declared_email  # type: ignore[assignment]
        group, default = "emails", declared_email.default if declared_email else True
    else:
        raise KarniValueError(
            f"karni.preferences: switch({kind!r}, ...): the kind is 'connection' or 'email'.",
            code="E325",
        )
    if declared is None:
        raise KarniLookupError(
            f"karni.preferences: no {kind} named {name!r} is declared.", code="E325"
        )
    if kind == "email" and declared_email is not None and not declared_email.switchable:
        raise PreferenceRefused(f"{declared_email.title} always goes out.", code="E323")
    _refuse_locked(group, [name])
    with transaction.atomic(), _audited(user):
        if on is None:
            for row in Switch.objects.filter(kind=kind, name=name):
                row.delete()
        else:
            row = Switch.objects.select_for_update().filter(kind=kind, name=name).first()
            if row is None:
                row = Switch(kind=kind, name=name, on=on)
            row.on = bool(on)
            row.updated_at = timezone.now()
            row.updated_by = user if getattr(user, "is_authenticated", False) else None
            row.save()
    forget()
    return switch_position(kind, name, default)


# tests


@contextmanager
def override(**groups: Mapping[str, Any]) -> Iterator[None]:
    """Experimental. Set values for a block, over locks and saved values: for tests.

    ``with override(bookings={"refund_notice_hours": 48}, connections={"crm.deal_timeline":
    False}): ...``. Keys are the groups of :func:`value` (``details``, a section key,
    ``connections``, ``emails``).
    """
    current = {group: dict(found) for group, found in (_OVERRIDES.get() or {}).items()}
    for group, found in groups.items():
        if group not in RESERVED and find_section(group) is None:
            raise KarniLookupError(
                f"karni.preferences: override({group}=...): no section {group!r} is registered "
                "(nor is it details, connections or emails).",
                code="E325",
            )
        current[group] = {**current.get(group, {}), **dict(found)}
    token = _OVERRIDES.set(current)
    forget()
    try:
        yield
    finally:
        _OVERRIDES.reset(token)
        forget()
