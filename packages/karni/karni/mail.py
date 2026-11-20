"""Experimental. An email from a project's own templates: the order confirmation, the reminder.

A business app sends mail at its own moments: an order is confirmed, a
booking is tomorrow, a refund went through. :func:`send_templated` renders
three templates a project can edit, and sends them with Django's mail
backend (the console in development)::

    from karni.mail import send_templated

    send_templated(
        "shop/email/order_confirmed",
        to=[order.email],
        context={"order": order},
    )

reads ``shop/email/order_confirmed_subject.txt`` (collapsed to one line, so
a value from a visitor can never add a header), ``..._body.txt`` and, when
it exists, ``..._body.html`` as the HTML part. Every template gets the
``context`` plus:

* ``frontend_url``: ``KARNI_FRONTEND_URL`` without its trailing slash, for
  links back into the app.

Send it from a listener once the data is committed, so a rolled-back
transaction sends nothing: ``@on_transition(Order, "status", to="paid",
queued=True)`` runs in a worker after the commit (docs/events.md), and
``transaction.on_commit(lambda: send_templated(...))`` does it in the request.

A message may carry a ``kind``, a stable name for what it is
(``commerce.order_paid``, ``shop.shipment_shipped``): it goes out in the
``X-Karni-Kind`` header, and a kind listed in ``KARNI_MAIL_DISABLED_KINDS``
is not sent at all, so a project switches one email off without code.

Demo data and imports should not mail anyone: inside ``with silenced():``
nothing is sent, including the messages that listeners queue with
``transaction.on_commit`` during the block (they run while the silence holds,
in the order they were queued).

**Kinds a business can edit.** A part declares each email it sends in its
``<app>/messages.py`` (imported at startup), with the merge fields a business
may use when it edits the message in the app::

    from karni.mail import register_kind

    register_kind(
        "shop.shipment_shipped",
        title="Parcel shipped",
        template="shop/email/shipment_shipped",
        audience="the buyer",
        fields={"order.number": "The order's number", "link": "The order's page"},
    )

:func:`kinds` lists them for a Settings screen. ``KARNI_MAIL_SOURCE`` names
the one place a project keeps what a business changed (an object or class
with any of ``template(kind)``, ``enabled(kind)`` and ``sender()``): a
template edited in the app (:class:`EditedTemplate`) wins over the files and
renders with a restricted engine (:func:`render_edited`) that sees the
declared merge fields only, as plain values, and has no tag that loads code
or other templates. ``enabled(kind)`` switches an email off, and ``sender()``
gives the ``From``. A source with ``send(template, to=..., context=..., kind=...,
...)`` takes over the delivery of every message with a kind: the notifications
contract's source (``karni.notify.source.NotifySource``, the default) honours
each person's own switches and unsubscribes there, and puts a kind declared with
``channels=("email", "inbox")`` in the recipient's inbox too. With
``KARNI_MAIL_SOURCE`` blank, :class:`DefaultSource` answers: the files, and the
switches and the sender of the preferences contract while ``karni.preferences``
is installed, else every email on and ``DEFAULT_FROM_EMAIL``.

Override / escape hatch: put a template of the same name earlier in
``TEMPLATES`` ``DIRS`` to change a message without code, pass
``from_email=`` (else ``DEFAULT_FROM_EMAIL``), ``reply_to=``, ``cc=`` or
``bcc=``, or build an :class:`~django.core.mail.EmailMultiAlternatives` with
:func:`render_templated` and send it yourself.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import models, transaction
from django.template import Context, Engine, Library, TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import render_to_string
from django.utils.html import escape, linebreaks, urlize
from django.utils.module_loading import autodiscover_modules, import_string

from karni.exceptions import KarniValueError

__all__ = [
    "CHANNELS",
    "KIND_HEADER",
    "SAFE_TAGS",
    "DefaultSource",
    "EditedTemplate",
    "MessageKind",
    "Rendered",
    "base_context",
    "check_edited",
    "default_source",
    "deliver",
    "edited_template",
    "find_kind",
    "is_silenced",
    "kind_enabled",
    "kinds",
    "mail_source",
    "merge_values",
    "register_kind",
    "render_edited",
    "render_templated",
    "sample_context",
    "send_templated",
    "sender",
    "silenced",
    "unregister_kind",
]

#: The header a message's kind goes out in.
KIND_HEADER = "X-Karni-Kind"
#: The channels a kind may be sent on: an email, and the recipient's inbox in the app.
CHANNELS: tuple[str, ...] = ("email", "inbox")


@dataclass(frozen=True)
class Rendered:
    """Experimental. One message, rendered: its subject, its text and its HTML (or ``None``)."""

    subject: str
    text: str
    html: str | None


@dataclass(frozen=True)
class MessageKind:
    """Experimental. One email a part sends, as a Settings screen lists it.

    ``fields`` maps each merge field (a dotted path into the context the sender
    passes: ``order.number``, ``lines.name`` for each line) to what it means.
    An edited template sees these and nothing else. ``switchable`` is false for
    an email a person cannot do without (a sign-in code).

    A preview (:func:`sample_context`) renders with real values: ``sample()``
    gives the context the sender would pass for the latest matching record
    (the last paid order), or ``None`` when there is none, and ``samples`` is a
    context of declared values for then (``{"order": {"number": 1001}}``).

    ``channels`` says where it goes: ``("email",)`` (the default), ``("inbox",)``
    (the recipient's inbox in the app, ``karni.notify``) or both. A kind that is
    not ``transactional`` is marketing: it carries an unsubscribe link while
    ``karni.notify`` is installed, and goes to nobody who unsubscribed.

    ``requires`` is who can be in its audience, read like a menu entry's
    (:func:`karni.navigation.opens`): ``authenticated`` (anyone signed in, the
    default: the buyer, a member) or a permission pattern for a message to the
    business (``karni_commerce.order:view`` for a new order). A person's own
    switches list only the kinds they can receive.
    """

    name: str
    title: str
    template: str
    audience: str = ""
    describe: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)
    transactional: bool = True
    switchable: bool = True
    sample: Callable[[], Mapping[str, Any] | None] | None = field(default=None, compare=False)
    samples: Mapping[str, Any] = field(default_factory=dict, compare=False)
    channels: tuple[str, ...] = ("email",)
    requires: str = "authenticated"

    @property
    def marketing(self) -> bool:
        """Experimental. A message a person may unsubscribe from (not ``transactional``)."""
        return not self.transactional


@dataclass(frozen=True)
class EditedTemplate:
    """Experimental. A message a business changed in the app: a subject and a text body."""

    subject: str
    text: str


_KINDS: dict[str, MessageKind] = {}
_DISCOVERED = [False]


def register_kind(
    name: str,
    *,
    title: str,
    template: str,
    audience: str = "",
    describe: str = "",
    fields: Mapping[str, str] | None = None,
    transactional: bool = True,
    switchable: bool = True,
    sample: Callable[[], Mapping[str, Any] | None] | None = None,
    samples: Mapping[str, Any] | None = None,
    channels: Iterable[str] = ("email",),
    replace: bool = True,
    requires: str = "authenticated",
) -> MessageKind:
    """Experimental. Declare the email ``name`` (registering it again replaces it).

    ``sample`` and ``samples`` feed the editor's preview (:func:`sample_context`).
    ``channels`` names where it goes: ``"email"``, ``"inbox"`` or both.
    ``replace=False`` keeps a declaration of the same name that is already there
    and returns it: a default that a part's own declaration wins over.
    ``requires`` names who can receive it (``authenticated``, or a permission
    pattern for a message to the business's people).

    :raises KarniValueError: E445, a channel that is not one of :data:`CHANNELS`, or none.
    """
    chosen = tuple(dict.fromkeys(str(channel) for channel in channels))
    unknown = [channel for channel in chosen if channel not in CHANNELS]
    if unknown or not chosen:
        raise KarniValueError(
            f"karni.mail: the kind {name!r} names the channels {list(chosen)!r}. "
            f"Name one or more of {list(CHANNELS)!r}.",
            code="E445",
        )
    if not replace and name in _KINDS:
        return _KINDS[name]
    found = MessageKind(
        name=name,
        title=title,
        template=template,
        audience=audience,
        describe=describe,
        fields=dict(fields or {}),
        transactional=transactional,
        switchable=switchable,
        sample=sample,
        samples=dict(samples or {}),
        channels=chosen,
        requires=str(requires or "authenticated"),
    )
    _KINDS[name] = found
    return found


def unregister_kind(name: str) -> None:
    """Experimental. Take the email ``name`` out of the list."""
    _KINDS.pop(name, None)


_DISCOVERING = threading.Lock()


def _discover() -> None:
    """Import each app's ``messages.py`` once (two first requests at once wait for it)."""
    if _DISCOVERED[0]:
        return
    with _DISCOVERING:
        if not _DISCOVERED[0]:
            autodiscover_modules("messages")
            import karni.accounts.emails  # noqa: F401  (declares the account emails)

            _DISCOVERED[0] = True


def kinds() -> list[MessageKind]:
    """Experimental. Every declared email, by name (each app's ``messages.py`` first)."""
    _discover()
    return sorted(_KINDS.values(), key=lambda kind: kind.name)


def find_kind(name: str) -> MessageKind | None:
    """Experimental. The declared email ``name``, or ``None``."""
    _discover()
    return _KINDS.get(name)


class DefaultSource:
    """Experimental. What a project without ``KARNI_MAIL_SOURCE`` has: the template files,
    and the switches and the sender of the preferences contract (Settings, Emails and
    Details) while ``karni.preferences`` is installed, else every email on and
    ``DEFAULT_FROM_EMAIL``. A source of your own may subclass it and add
    ``template(kind)``.
    """

    @staticmethod
    def _preferences() -> bool:
        from django.apps import apps

        return apps.is_installed("karni.preferences")

    def template(self, kind: str) -> EditedTemplate | None:
        return None

    def keeps_edits(self) -> bool:
        """Whether this source keeps emails a business rewrote (``template()`` answers)."""
        return type(self).template is not DefaultSource.template

    def enabled(self, kind: str) -> bool:
        if not self._preferences():
            return True
        from karni import preferences

        return preferences.email_on(kind)

    def sender(self) -> str | None:
        if not self._preferences():
            return None
        from karni import preferences

        return preferences.sender()


default_source = DefaultSource()


def mail_source() -> Any:
    """Experimental. The object ``KARNI_MAIL_SOURCE`` names (an instance of a class)."""
    path = str(getattr(settings, "KARNI_MAIL_SOURCE", "") or "")
    if not path:
        return default_source
    found = _import(path)
    return found() if isinstance(found, type) else found


@cache
def _import(path: str) -> Any:
    return import_string(path)


def sender() -> str | None:
    """Experimental. The ``From`` of the project's emails: the source's, else ``None``."""
    ask = getattr(mail_source(), "sender", None)
    found = ask() if callable(ask) else None
    return str(found) if found else None


# -- the restricted engine ------------------------------------------------------------------

#: The tags an edited template may use: none loads code or another template.
SAFE_TAGS = (
    "autoescape",
    "comment",
    "cycle",
    "filter",
    "firstof",
    "for",
    "if",
    "ifchanged",
    "now",
    "regroup",
    "resetcycle",
    "spaceless",
    "templatetag",
    "verbatim",
    "widthratio",
    "with",
)


@cache
def _engine() -> Engine:
    from django.template import defaultfilters, defaulttags

    engine = Engine(debug=False, libraries={}, string_if_invalid="", autoescape=False)
    safe = Library()
    safe.tags = {name: defaulttags.register.tags[name] for name in SAFE_TAGS}
    safe.filters = dict(defaultfilters.register.filters)
    engine.template_builtins = [safe]
    return engine


_CENTS = Decimal("0.01")


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal) and value.is_finite() and value == value.quantize(_CENTS):
        # Money stored with four places reads as it is written: 12.00, not 12.0000.
        return value.quantize(_CENTS)
    if value is None or isinstance(value, bool | int | float | str | Decimal | date | datetime):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)


def _many(value: Any) -> list[Any] | None:
    if isinstance(value, models.Manager):
        return list(value.all())
    if isinstance(value, list | tuple | models.QuerySet):
        return list(value)
    return None


def _get(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    found = getattr(value, name, None)
    if callable(found) and not isinstance(found, models.Manager):
        if getattr(found, "alters_data", False):
            return None
        try:
            return found()
        except TypeError:
            return None
    return found


def _build(value: Any, parts: list[str]) -> Any:
    rows = _many(value)
    if rows is not None and parts:
        return [_build(row, parts) for row in rows]
    if not parts:
        return _plain(rows if rows is not None else value)
    return {parts[0]: _build(_get(value, parts[0]), parts[1:])}


def _merge(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        for key, value in right.items():
            merged[key] = _merge(merged[key], value) if key in merged else value
        return merged
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [_merge(a, b) for a, b in zip(left, right, strict=True)]
    return right


def merge_values(fields: Iterable[str], context: Mapping[str, Any]) -> dict[str, Any]:
    """Experimental. The declared merge ``fields`` read from ``context``, as plain values.

    ``"order.number"`` gives ``{"order": {"number": ...}}``, and a path through
    a list (or a related manager) gives one entry per row: ``"lines.name"``
    gives ``{"lines": [{"name": ...}, ...]}``. Numbers, text, dates and
    booleans stay as they are (an amount with no more than two places shows
    two: ``12.00``), and anything else becomes its text.
    """
    found: dict[str, Any] = {**base_context()}
    for path in fields:
        found = _merge(found, _build(dict(context), str(path).split(".")))
    return found


def _placeholders(kind: MessageKind) -> dict[str, Any]:
    """Each merge field shown as ``[path]``: what a preview falls back to, last.

    A field whose meaning starts with "Each" is one per row: the part of its
    path before the last is a list of two rows.
    """
    found: dict[str, Any] = {}
    for path, meaning in kind.fields.items():
        parts = str(path).split(".")
        many = str(meaning).startswith("Each") and len(parts) > 1
        value: Any = f"[{path}]"
        for depth in range(len(parts) - 1, -1, -1):
            value = {parts[depth]: value}
            if many and depth == len(parts) - 1:
                value = [value, value]
        found = _merge(found, value) if isinstance(value, dict) else found
    return found


def _business() -> dict[str, Any]:
    """The business's details (``karni.preferences``) while the contract is installed."""
    from django.apps import apps

    if not apps.is_installed("karni.preferences"):
        return {}
    from karni import preferences

    return dict(preferences.details().as_dict())


def sample_context(kind: MessageKind | str) -> dict[str, Any]:
    """Experimental. What a preview of the email ``kind`` renders with: real values.

    In this order, each over the one before: each merge field as ``[path]``,
    the kind's declared ``samples``, the business's details as ``business``
    (Settings, Details), and the context of the latest matching record
    (``sample()``: the last paid order for a confirmation). Pass the result to
    :func:`merge_values` with the kind's fields.

    A name no email declares gives what every template gets (:func:`base_context`).
    """
    found = find_kind(kind) if isinstance(kind, str) else kind
    if found is None:  # no declared email: nothing but what every template gets
        return base_context()
    context = _merge(_placeholders(found), _plain(dict(found.samples)))
    business = _business()
    if business:
        context = _merge(context, {"business": business})
    record = found.sample() if found.sample is not None else None
    if record:
        context.update(dict(record))  # the sender's own context: top-level keys replace
    return context


def check_edited(subject: str, text: str) -> dict[str, str]:
    """Experimental. What is wrong with an edited message, by part (empty when nothing)."""
    problems: dict[str, str] = {}
    for part, source in (("subject", subject), ("text", text)):
        try:
            _engine().from_string(source)
        except TemplateSyntaxError as exc:
            problems[part] = str(exc)
    if not subject.strip():
        problems["subject"] = "A subject, please."
    if not text.strip():
        problems["text"] = "The message, please."
    return problems


def render_edited(edited: EditedTemplate, values: Mapping[str, Any]) -> Rendered:
    """Experimental. An edited message rendered with the restricted engine.

    ``values`` are plain (:func:`merge_values`). The HTML part is the text with
    its paragraphs and links.
    """
    engine = _engine()
    subject = " ".join(engine.from_string(edited.subject).render(Context(dict(values))).split())
    text = engine.from_string(edited.text).render(Context(dict(values)))
    html = linebreaks(urlize(escape(text), autoescape=False))
    return Rendered(subject, text, html)


def base_context() -> dict[str, Any]:
    """Experimental. What every template gets besides the caller's context."""
    return {"frontend_url": str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")}


_SILENCE = [0]


def _hush() -> None:
    _SILENCE[0] += 1


def _speak() -> None:
    _SILENCE[0] = max(_SILENCE[0] - 1, 0)


@contextmanager
def silenced() -> Iterator[None]:
    """Experimental. Send nothing inside the block, nor from what it queues for the commit.

    The silence also covers the ``transaction.on_commit`` callbacks queued
    inside the block: one callback queued first starts it again at the commit,
    and one queued last ends it. A rolled-back transaction drops them all.
    """
    _hush()
    transaction.on_commit(_hush)
    try:
        yield
    finally:
        transaction.on_commit(_speak)
        _speak()


def is_silenced() -> bool:
    """Experimental. Whether a :func:`silenced` block holds now: nothing is sent."""
    return bool(_SILENCE[0])


def kind_enabled(kind: str | None) -> bool:
    """Experimental. Whether ``kind`` goes out: not listed in ``KARNI_MAIL_DISABLED_KINDS``,
    and not switched off by ``KARNI_MAIL_SOURCE`` (an email declared not
    ``switchable`` always goes, whatever the source says)."""
    if not kind:
        return True
    if kind in set(getattr(settings, "KARNI_MAIL_DISABLED_KINDS", None) or ()):
        return False
    declared = find_kind(kind)
    if declared is not None and not declared.switchable:
        return True
    ask = getattr(mail_source(), "enabled", None)
    return bool(ask(kind)) if callable(ask) else True


def edited_template(kind: str | None) -> EditedTemplate | None:
    """Experimental. The message ``kind`` as a business edited it, or ``None``."""
    if not kind:
        return None
    ask = getattr(mail_source(), "template", None)
    found = ask(kind) if callable(ask) else None
    return found if isinstance(found, EditedTemplate) else None


def render_templated(
    template: str, context: Mapping[str, Any] | None = None, *, kind: str | None = None
) -> Rendered:
    """Experimental. ``<template>_subject.txt``, ``_body.txt`` and ``_body.html`` rendered.

    With a ``kind`` whose message a business edited (``KARNI_MAIL_SOURCE``),
    that message wins, rendered by :func:`render_edited` with the kind's
    declared merge fields only.

    :raises TemplateDoesNotExist: when the subject or the text body is missing.
        The HTML body is optional.
    """
    edited = edited_template(kind)
    declared = find_kind(kind) if edited is not None and kind else None
    if edited is not None and declared is not None:
        return render_edited(edited, merge_values(declared.fields, dict(context or {})))
    values = {**base_context(), **dict(context or {})}
    subject = " ".join(render_to_string(f"{template}_subject.txt", values).split())
    text = render_to_string(f"{template}_body.txt", values)
    try:
        html: str | None = render_to_string(f"{template}_body.html", values)
    except TemplateDoesNotExist:
        html = None
    return Rendered(subject, text, html)


def send_templated(
    template: str,
    *,
    to: Iterable[str],
    context: Mapping[str, Any] | None = None,
    from_email: str | None = None,
    reply_to: Iterable[str] | None = None,
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
    kind: str | None = None,
) -> int:
    """Experimental. Render ``template`` (see the module docstring) and send it to ``to``.

    Returns the number of messages sent: ``0`` when ``to`` holds no address,
    so a row without an email address never fails the code that saves it, and
    ``0`` when ``kind`` is switched off (``KARNI_MAIL_DISABLED_KINDS``).

    With a ``kind``, a source that has ``send()`` (``KARNI_MAIL_SOURCE``: the
    notifications contract's by default) delivers it: each person's own
    switches, unsubscribes and the inbox apply there, and the number is the
    emails it sent.
    """
    addresses = [str(address).strip() for address in to if str(address or "").strip()]
    if not addresses or _SILENCE[0]:
        return 0
    take = getattr(mail_source(), "send", None) if kind else None
    if callable(take):
        return int(
            take(
                template,
                to=addresses,
                context=dict(context or {}),
                kind=kind,
                from_email=from_email,
                reply_to=list(reply_to) if reply_to else None,
                cc=list(cc) if cc else None,
                bcc=list(bcc) if bcc else None,
            )
            or 0
        )
    if not kind_enabled(kind):
        return 0
    return deliver(
        template,
        to=addresses,
        context=context,
        from_email=from_email,
        reply_to=reply_to,
        cc=cc,
        bcc=bcc,
        kind=kind,
    )


def deliver(
    template: str,
    *,
    to: Iterable[str],
    context: Mapping[str, Any] | None = None,
    from_email: str | None = None,
    reply_to: Iterable[str] | None = None,
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
    kind: str | None = None,
    headers: Mapping[str, str] | None = None,
    rendered: Rendered | None = None,
) -> int:
    """Experimental. Render and send one message now, with no switch asked.

    What :func:`send_templated` does once it decided the message goes out, for a
    mail source's ``send()``: ``rendered`` skips the rendering, ``headers`` are
    added to the kind's header. The ``From`` is ``from_email``, else the
    source's sender, else ``DEFAULT_FROM_EMAIL``.
    """
    addresses = [str(address).strip() for address in to if str(address or "").strip()]
    if not addresses or _SILENCE[0]:
        return 0
    found = rendered if rendered is not None else render_templated(template, context, kind=kind)
    extra: dict[str, str] = {KIND_HEADER: kind} if kind else {}
    extra.update(dict(headers or {}))
    message = EmailMultiAlternatives(
        subject=found.subject,
        body=found.text,
        from_email=from_email or sender() or None,
        to=addresses,
        cc=list(cc) if cc else None,
        bcc=list(bcc) if bcc else None,
        reply_to=list(reply_to) if reply_to else None,
        headers=extra or None,
    )
    if found.html is not None:
        message.attach_alternative(found.html, "text/html")
    return int(message.send())
