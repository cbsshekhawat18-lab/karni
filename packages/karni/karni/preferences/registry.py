"""Experimental. What parts declare: settings sections, connections and email kinds.

A part declares, in its own ``<app>/preferences.py`` and ``<app>/connections.py``
(imported at startup by :func:`autodiscover`)::

    from pydantic import Field

    from karni import preferences


    @preferences.section("bookings", title="Bookings")
    class BookingPreferences(preferences.Section):
        refund_notice_hours: int = Field(0, ge=0, description="...")


    preferences.connection(
        "bookings.family_events",
        needs=["events"],
        default=True,
        describe="Confirmed and cancelled bookings are published as family events.",
    )

A section is a Pydantic model whose every field has a default. Its values are
stored as validated JSON (:class:`karni.preferences.models.SectionValue`). A
connection is code on one side, written against a contract or a module, that
runs when everything it ``needs`` is installed and its switch is on. An email
kind is a message the project sends that Settings, Emails can switch off.

Override / escape hatch: :func:`unregister` removes a declaration, and a
project may declare its own sections, connections and email kinds the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from karni.exceptions import KarniTypeError, KarniValueError

__all__ = [
    "CONTRACT_APPS",
    "RESERVED",
    "Connection",
    "EmailKind",
    "Section",
    "SectionSpec",
    "autodiscover",
    "connection",
    "ensure_discovered",
    "connections",
    "email",
    "emails",
    "find_connection",
    "find_email",
    "find_section",
    "move_email_name",
    "need_installed",
    "section",
    "sections",
    "unregister",
]

#: Section keys the Settings page keeps for itself (``KARNI_PREFERENCES_LOCKED`` uses them too).
RESERVED: Final = frozenset({"details", "connections", "emails"})
#: The app each core contract a connection may need is installed as.
CONTRACT_APPS: Final[dict[str, str]] = {
    "people": "karni.people",
    "events": "karni.outbox",
    "timeline": "karni.timeline",
    "preferences": "karni.preferences",
    "notify": "karni.notify",
}
_KEY: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_DOTTED: Final = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

S = TypeVar("S", bound="Section")


class Section(BaseModel):
    """Experimental. The base of a part's settings section: a Pydantic model with defaults.

    Every field needs a default, so a project that never opens Settings gets
    sensible values. A field's ``description`` is the help line on the
    Settings page, and its constraints (``ge``, ``max_length``, ``Literal``)
    are checked on every change. Unknown keys in stored values are ignored,
    so removing a field from a section never breaks a project.
    """

    model_config = ConfigDict(extra="ignore", validate_assignment=True, validate_default=True)

    #: Set by :func:`section`.
    spec: ClassVar[SectionSpec | None] = None


@dataclass(frozen=True)
class SectionSpec:
    """Experimental. One registered section: its key, title, model and who may change it.

    ``change`` is a permission key (``"bookings.resource:change"``) or a role
    (``"role:bookings-manager"``) the user must hold. ``version`` is the
    shape of the stored values: raise it when a field changes meaning.
    """

    key: str
    model: type[Section]
    title: str
    describe: str = ""
    change: str = "preferences.sectionvalue:change"
    version: int = 1
    source: str = ""

    def defaults(self) -> dict[str, Any]:
        """The declared default of every field, as JSON values."""
        return self.model().model_dump(mode="json")

    def schema(self) -> dict[str, Any]:
        """The JSON schema of the section, which the Settings page renders a form from."""
        return self.model.model_json_schema()


@dataclass(frozen=True)
class Connection:
    """Experimental. Something that happens because what it ``needs`` is installed.

    ``name`` is ``<prefix>.<what>`` (``crm.deal_timeline``). ``needs`` names
    core contracts (``people``, ``events``, ``timeline``, ``preferences``) and
    modules by app label (``karni_payments``), never another part. ``default``
    is the switch's position until someone changes it in Settings.
    """

    name: str
    needs: tuple[str, ...]
    default: bool
    describe: str
    title: str = ""
    source: str = ""

    @property
    def prefix(self) -> str:
        """The part that declares it: the first word of the name."""
        return self.name.split(".", 1)[0]

    def installed(self) -> bool:
        """Is everything it needs installed?"""
        return all(need_installed(need) for need in self.needs)


@dataclass(frozen=True)
class EmailKind:
    """Experimental. A message the project sends, which Settings, Emails can switch off.

    ``name`` is ``<prefix>.<message>`` (``bookings.booking_confirmed``).
    ``transactional`` messages (a receipt, a confirmation) are on by
    default. ``source`` says where it was declared (``rules`` for a move's
    email from ``moves.<state>.notify``, ``mail`` for a message a part
    declared with :func:`karni.mail.register_kind`). ``audience`` says who
    gets it, and an email that is not ``switchable`` (a sign-in code) always
    goes out. ``editable``: the business may rewrite its text (a
    :func:`karni.mail.register_kind` message with merge fields, in a project whose
    ``KARNI_MAIL_SOURCE`` keeps edited emails).
    """

    name: str
    title: str
    describe: str = ""
    default: bool = True
    transactional: bool = True
    source: str = ""
    audience: str = ""
    switchable: bool = True
    editable: bool = False


@dataclass
class _Registry:
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    connections: dict[str, Connection] = field(default_factory=dict)
    emails: dict[str, EmailKind] = field(default_factory=dict)


_registry = _Registry()


def need_installed(need: str) -> bool:
    """Is the contract or the app ``need`` names installed? A module's app label or its name."""
    from django.apps import apps

    app = CONTRACT_APPS.get(need)
    if app is not None:
        return apps.is_installed(app)
    return any(config.label == need or config.name == need for config in apps.get_app_configs())


def _caller_source(depth: int = 3) -> str:
    import sys

    frame = sys._getframe(depth)
    return str(frame.f_globals.get("__name__", ""))


def section(
    key: str,
    *,
    title: str = "",
    describe: str = "",
    change: str = "preferences.sectionvalue:change",
    version: int = 1,
    replace: bool = False,
) -> Callable[[type[S]], type[S]]:
    """Experimental. Register a :class:`Section` subclass as the settings section ``key``.

    :param key: the section's key, the part's prefix (``"bookings"``).
    :param title: the tab's title on the Settings page (default: the key).
    :param change: a permission key or ``role:<slug>`` a user needs to change it.
    :param version: the shape of the stored values.
    :param replace: replace a section already registered under ``key``.
    :raises KarniValueError: E321, a malformed key, a reserved or taken one,
        or a field without a usable default.
    """

    def register(model: type[S]) -> type[S]:
        if not (isinstance(model, type) and issubclass(model, Section)):
            raise KarniTypeError(
                f"karni.preferences: section {key!r} must be a subclass of "
                f"karni.preferences.Section, got {model!r}.",
                code="E321",
            )
        _check_key(key)
        if key in _registry.sections and not replace:
            raise KarniValueError(
                f"karni.preferences: the section {key!r} is registered twice "
                f"({_registry.sections[key].source} and {model.__module__}).",
                code="E321",
            )
        try:
            model()
        except ValidationError as exc:
            raise KarniValueError(
                f"karni.preferences: the section {key!r} ({model.__name__}) cannot be built "
                f"from its defaults: {_first_error(exc)}. Give every field a valid default.",
                code="E321",
            ) from None
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise KarniValueError(
                f"karni.preferences: the section {key!r} has version={version!r}: pass an "
                "integer from 1.",
                code="E321",
            )
        spec = SectionSpec(
            key=key,
            model=model,
            title=title or key.replace("_", " ").capitalize(),
            describe=describe or (model.__doc__ or "").strip().split("\n", 1)[0],
            change=change,
            version=version,
            source=model.__module__,
        )
        model.spec = spec
        _registry.sections[key] = spec
        return model

    return register


def _check_key(key: str) -> None:
    if not isinstance(key, str) or not _KEY.match(key):
        raise KarniValueError(
            f"karni.preferences: the section key {key!r} is not a lower-case name "
            "(letters, digits and underscores, the part's prefix).",
            code="E321",
        )
    if key in RESERVED:
        raise KarniValueError(
            f"karni.preferences: the section key {key!r} is reserved for the Settings page "
            f"({', '.join(sorted(RESERVED))}). Use the part's prefix.",
            code="E321",
        )


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg', '')}" if where else str(error.get("msg", ""))


def connection(
    name: str,
    *,
    needs: Sequence[str],
    default: bool,
    describe: str,
    title: str = "",
    replace: bool = False,
) -> Connection:
    """Experimental. Declare a connection, in a part's ``connections.py``.

    :param name: ``<prefix>.<what>``, for example ``"crm.deal_timeline"``.
    :param needs: the contracts and modules it works against. It is active
        only while every one is installed.
    :param default: the switch's position until someone changes it.
    :param describe: one sentence saying what it does, shown in Settings,
        Connections.
    :raises KarniValueError: E322, a malformed or repeated declaration.
    """
    if not isinstance(name, str) or not _DOTTED.match(name):
        raise KarniValueError(
            f"karni.preferences: the connection name {name!r} is not '<prefix>.<what>' "
            "(lower-case words joined by dots).",
            code="E322",
        )
    if isinstance(needs, str) or not all(isinstance(n, str) and n for n in needs):
        raise KarniValueError(
            f"karni.preferences: the connection {name!r} has needs={needs!r}: pass a list of "
            f"contracts ({', '.join(CONTRACT_APPS)}) or module app labels.",
            code="E322",
        )
    if not needs:
        raise KarniValueError(
            f"karni.preferences: the connection {name!r} needs nothing, so it connects "
            "nothing. Name the contract or module it works against.",
            code="E322",
        )
    if not isinstance(default, bool):
        raise KarniValueError(
            f"karni.preferences: the connection {name!r} has default={default!r}: pass True or "
            "False.",
            code="E322",
        )
    if not describe or not isinstance(describe, str):
        raise KarniValueError(
            f"karni.preferences: the connection {name!r} needs describe=, one sentence that "
            "says what it does.",
            code="E322",
        )
    found = Connection(
        name=name,
        needs=tuple(needs),
        default=default,
        describe=describe,
        title=title or name.split(".", 1)[1].replace("_", " ").capitalize(),
        source=_caller_source(2),
    )
    if name in _registry.connections and not replace:
        if _registry.connections[name] == found:
            return found  # the same module imported twice
        raise KarniValueError(
            f"karni.preferences: the connection {name!r} is declared twice "
            f"({_registry.connections[name].source} and {found.source}).",
            code="E322",
        )
    _registry.connections[name] = found
    return found


def email(
    name: str,
    *,
    title: str,
    describe: str = "",
    default: bool = True,
    transactional: bool = True,
    replace: bool = False,
) -> EmailKind:
    """Experimental. Declare an email kind that Settings, Emails lists with its switch.

    A move's email (``moves.<state>.notify`` in karni.yaml) is listed without
    a declaration. :func:`karni.preferences.email_on` answers whether a kind
    goes out.

    :raises KarniValueError: E322, a malformed or repeated name.
    """
    if not isinstance(name, str) or not _DOTTED.match(name):
        raise KarniValueError(
            f"karni.preferences: the email kind {name!r} is not '<prefix>.<message>' "
            "(lower-case words joined by dots).",
            code="E322",
        )
    found = EmailKind(
        name=name,
        title=title,
        describe=describe,
        default=default,
        transactional=transactional,
        source=_caller_source(2),
    )
    if name in _registry.emails and not replace and _registry.emails[name] != found:
        raise KarniValueError(
            f"karni.preferences: the email kind {name!r} is declared twice.", code="E322"
        )
    _registry.emails[name] = found
    return found


def sections() -> list[SectionSpec]:
    """Experimental. Every registered section, in key order."""
    ensure_discovered()
    return [_registry.sections[key] for key in sorted(_registry.sections)]


def connections() -> list[Connection]:
    """Experimental. Every declared connection, in name order (installed or not)."""
    ensure_discovered()
    return [_registry.connections[name] for name in sorted(_registry.connections)]


def emails() -> list[EmailKind]:
    """Experimental. Every email kind, by name: the declared ones, each move's email and
    each message a part declared with :func:`karni.mail.register_kind`."""
    ensure_discovered()
    found = dict(_registry.emails)
    for kind in [*_move_emails(), *_mail_emails()]:
        found.setdefault(kind.name, kind)
    return [found[name] for name in sorted(found)]


def _mail_emails() -> Iterable[EmailKind]:
    from karni.mail import DefaultSource, kinds, mail_source

    # Editable when the project's mail source keeps edited emails (KARNI_MAIL_SOURCE).
    source = mail_source()
    asks = getattr(source, "keeps_edits", None)
    keeps = (
        bool(asks())
        if callable(asks)
        else getattr(type(source), "template", None) not in (None, DefaultSource.template)
    )
    for kind in kinds():
        yield EmailKind(
            name=kind.name,
            title=kind.title,
            describe=kind.describe,
            transactional=kind.transactional,
            source="mail",
            audience=kind.audience,
            switchable=kind.switchable,
            editable=keeps and bool(kind.fields),
        )


def _move_emails() -> Iterable[EmailKind]:
    from django.apps import apps

    from karni.mail import find_kind, mail_source
    from karni.rules import rules_of

    # karni.notify declares each move's email as a kind with merge fields: editable then.
    asks = getattr(mail_source(), "keeps_edits", None)
    keeps = bool(asks()) if callable(asks) else False

    for model in apps.get_models():
        try:
            moves = rules_of(model).moves
        except Exception:  # noqa: BLE001 - a model whose rules karni check reports
            continue
        for move in moves:
            if move.notify is None:
                continue
            meta = model._meta
            state = "true" if move.to is True else str(move.to)
            name = move_email_name(model, move.key)
            yield EmailKind(
                name=name,
                title=f"{str(meta.verbose_name).capitalize()}: {state.replace('_', ' ')}",
                describe=f"Sent to the row's {move.notify.replace('__', ' ')} when the "
                f"{meta.verbose_name} moves to {state}.",
                source="rules",
                editable=keeps and bool(getattr(find_kind(name), "fields", None)),
            )


def move_email_name(model: Any, key: str) -> str:
    """Experimental. The email kind of a move's email: ``<app_label>.<model>_<key>``."""
    meta = model._meta
    return f"{meta.app_label}.{meta.model_name}_{key.replace(':', '_')}".lower()


def find_section(key: str) -> SectionSpec | None:
    """Experimental. The section registered as ``key``, or ``None``."""
    ensure_discovered()
    return _registry.sections.get(key)


def find_connection(name: str) -> Connection | None:
    """Experimental. The connection declared as ``name``, or ``None``."""
    ensure_discovered()
    return _registry.connections.get(name)


def find_email(name: str) -> EmailKind | None:
    """Experimental. The email kind ``name`` (declared, or a move's), or ``None``."""
    return next((kind for kind in emails() if kind.name == name), None)


def unregister(*, section: str | None = None, connection: str | None = None) -> None:
    """Experimental. Remove a section or a connection (a project replaces a part's)."""
    if section is not None:
        found = _registry.sections.pop(section, None)
        if found is not None:
            found.model.spec = None
    if connection is not None:
        _registry.connections.pop(connection, None)


_discovered: list[bool] = []


def autodiscover() -> None:
    """Import ``<app>.preferences`` and ``<app>.connections`` of every installed app.

    Run by the app's ``ready()``, and on the first read when ``karni.preferences``
    is not installed, so a part's connections keep their defaults without it.
    Idempotent (Python's import cache).
    """
    from django.utils.module_loading import autodiscover_modules

    _discovered.append(True)
    autodiscover_modules("preferences", "connections")


def ensure_discovered() -> None:
    """Experimental. :func:`autodiscover` once the app registry is ready, if not done yet."""
    from django.apps import apps
    from django.conf import settings

    if _discovered or not apps.ready:
        return
    if getattr(settings, "KARNI_PREFERENCES_AUTODISCOVER", True):
        autodiscover()
    else:
        _discovered.append(True)
