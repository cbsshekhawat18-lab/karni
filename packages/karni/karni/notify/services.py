"""Experimental. Sending a message kind, the inbox, each person's switches and unsubscribes.

:func:`send` is the one call a part makes to tell people something::

    from karni import notify

    notify.send("crm.task_due", to=[task.owner], context={"task": task, "link": url})

It sends the kind on each channel it declares (``karni.mail.register_kind(...,
channels=("email", "inbox"))``) that the project uses (``KARNI_NOTIFY_CHANNELS``):

* **email**: through ``karni.mail`` (an edited template wins over the files, the
  sender and the reply-to come from the details), one to each recipient with an
  address. A marketing kind (``transactional=False``) goes to one address at a
  time, with its own unsubscribe link (``unsubscribe_url`` in the context) and
  the ``List-Unsubscribe`` headers.
* **inbox**: one :class:`~karni.notify.models.Notification` per recipient with an
  account, titled with the rendered subject, with the text as its body and the
  context's ``link``.

A kind switched off in Settings, Emails (or ``KARNI_MAIL_DISABLED_KINDS``) goes
nowhere. A person's own switch (:func:`choose`) turns a switchable kind off for
them on one channel, and an address that unsubscribed from a marketing kind
gets nothing more of it, on any channel, from any part. ``karni.mail.silenced()``
holds the inbox too.

``karni.mail.send_templated(..., kind=...)`` comes here as well, through the
default ``KARNI_MAIL_SOURCE`` (:class:`karni.notify.source.NotifySource`), so a
part that sends with it keeps its call and gains the switches and the inbox.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from karni.exceptions import KarniTypeError, KarniValueError
from karni.mail import (
    CHANNELS,
    MessageKind,
    Rendered,
    deliver,
    find_kind,
    is_silenced,
    kind_enabled,
    kinds,
    render_templated,
)

__all__ = [
    "APP",
    "Recipient",
    "Sent",
    "choices",
    "receives",
    "choose",
    "deliver_kind",
    "holders",
    "installed",
    "mark_read",
    "mark_unread",
    "on_event",
    "project_channels",
    "prune",
    "read_token",
    "recipients",
    "reply_to",
    "resubscribe",
    "retention_days",
    "send",
    "send_mail",
    "unread_count",
    "unsubscribe",
    "unsubscribe_token",
    "unsubscribe_url",
    "unsubscribed",
]

#: The dotted path a project adds to ``INSTALLED_APPS``.
APP: Final = "karni.notify"
#: The salt of the unsubscribe tokens: a token signed for anything else is refused.
TOKEN_SALT: Final = "karni.notify.unsubscribe"
_ELLIPSIS: Final = "..."


def installed() -> bool:
    """Experimental. Whether ``karni.notify`` is in ``INSTALLED_APPS``."""
    return apps.is_installed(APP)


@dataclass(frozen=True)
class Recipient:
    """Experimental. Who a message goes to: an address, an account, or both."""

    email: str
    user: Any = None

    @property
    def addresses(self) -> set[str]:
        """Every address this recipient is known by, lower-cased."""
        found = {self.email.lower()} if self.email else set()
        user_email = str(getattr(self.user, "email", "") or "")
        if user_email:
            found.add(user_email.lower())
        return found


@dataclass(frozen=True)
class Sent:
    """Experimental. What :func:`send` did: the emails sent and the inbox rows written."""

    email: int = 0
    inbox: int = 0


def project_channels() -> tuple[str, ...]:
    """Experimental. The channels the project sends on (``KARNI_NOTIFY_CHANNELS``)."""
    chosen = getattr(settings, "KARNI_NOTIFY_CHANNELS", CHANNELS)
    return tuple(channel for channel in CHANNELS if channel in set(chosen or ()))


def _channels(kind: MessageKind | None) -> tuple[str, ...]:
    declared = kind.channels if kind is not None else ("email",)
    if not installed():
        return tuple(channel for channel in declared if channel == "email")
    ours = project_channels()
    return tuple(channel for channel in declared if channel in ours)


# -- who ----------------------------------------------------------------------------------


def _is_user(value: Any) -> bool:
    return isinstance(value, get_user_model())


def _saved(user: Any) -> Any:
    """``user`` when it is a saved account, else ``None`` (an unsaved one has no inbox)."""
    if user is None or getattr(getattr(user, "_state", None), "adding", True):
        return None
    return user


def recipients(to: Any) -> list[Recipient]:
    """Experimental. ``to`` as recipients: users, people, addresses, or a list of them.

    A user gives its account and its email. A person (``karni.people``) gives
    its email and its account when it has one. An address gives itself, and the
    active account with that email when there is one and its email is verified,
    so the inbox and the person's own switches reach it. Each one is listed once.

    :raises KarniTypeError: E443, something that is none of those.
    """
    items: list[Any]
    if to is None:
        items = []
    elif isinstance(to, str | models.Model) or not isinstance(to, Iterable):
        items = [to]
    else:
        items = list(to)
    found: list[Recipient] = []
    loose: list[str] = []
    for item in items:
        if item is None or item == "":
            continue
        if isinstance(item, Recipient):
            found.append(item)
        elif isinstance(item, str):
            if item.strip():
                loose.append(item.strip())
        elif _is_user(item):
            found.append(Recipient(str(getattr(item, "email", "") or ""), _saved(item)))
        elif hasattr(item, "email"):
            user = getattr(item, "user", None)
            found.append(
                Recipient(
                    str(getattr(item, "email", "") or ""), _saved(user) if _is_user(user) else None
                )
            )
        else:
            raise KarniTypeError(
                f"karni.notify: cannot send to {item!r}. Pass a user, a person, an email "
                "address, or a list of them.",
                code="E443",
            )
    if loose:
        found.extend(_with_accounts(loose))
    unique: list[Recipient] = []
    seen: set[Any] = set()
    for recipient in found:
        key = ("user", recipient.user.pk) if recipient.user is not None else recipient.email.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(recipient)
    return unique


def holders(*roles: str) -> Any:
    """Experimental. The active users who hold any of ``roles``: a role as an audience.

    ``notify.send("commerce.new_order", to=notify.holders("shop-manager"), ...)``
    tells everyone who holds the role, each on their own switches. A role is
    the group of its slug (:func:`karni.accounts.permissions.assign_role`).
    """
    model = get_user_model()
    return (
        model._default_manager.filter(groups__name__in=list(roles), is_active=True)
        .distinct()
        .order_by("pk")
    )


def _with_accounts(addresses: list[str]) -> list[Recipient]:
    """Each address with the active account of that email, in one query.

    Only an account that verified its email (``email_verified``, on a user model
    that has it): anyone may sign up with an address they do not hold, and the
    inbox must not show them what was sent to it.
    """
    lowered = {address.lower() for address in addresses}
    accounts: dict[str, Any] = {}
    if installed():
        model = get_user_model()
        field = getattr(model, "EMAIL_FIELD", "email")
        rows = model._default_manager.annotate(_notify_email=Lower(field)).filter(
            _notify_email__in=lowered, is_active=True
        )
        if any(found.name == "email_verified" for found in model._meta.get_fields()):
            rows = rows.filter(email_verified=True)
        for user in rows:
            accounts.setdefault(str(user._notify_email), user)
    return [Recipient(address, accounts.get(address.lower())) for address in addresses]


class _Wants:
    """Whether each recipient wants a kind on a channel: two queries for a whole send."""

    def __init__(self, kind: MessageKind | None, name: str, people: list[Recipient]) -> None:
        self.free = kind is None or not kind.switchable or not installed()
        self.marketing = kind is not None and kind.marketing
        self.choices: dict[Any, Any] = {}
        self.gone: set[str] = set()
        if self.free:
            return
        from karni.notify.models import Choice, Unsubscribe

        users = [person.user.pk for person in people if person.user is not None]
        if users:
            self.choices = {
                row.user_id: row for row in Choice.objects.filter(kind=name, user_id__in=users)
            }
        if self.marketing:
            addresses = set().union(*(person.addresses for person in people)) if people else set()
            if addresses:
                self.gone = set(
                    Unsubscribe.objects.filter(kind=name, address__in=addresses).values_list(
                        "address", flat=True
                    )
                )

    def __call__(self, person: Recipient, channel: str) -> bool:
        if self.free:
            return True
        if self.marketing and person.addresses & self.gone:
            return False
        choice = self.choices.get(person.user.pk) if person.user is not None else None
        return bool(getattr(choice, channel)) if choice is not None else True


# -- sending ------------------------------------------------------------------------------


def reply_to() -> list[str] | None:
    """Experimental. The details' reply-to address (Settings, Details), as a list, or ``None``."""
    if not apps.is_installed("karni.preferences"):
        return None
    from karni import preferences

    found = preferences.details().reply_to
    return [found] if found else None


def send(
    kind: str,
    *,
    to: Any,
    context: Mapping[str, Any] | None = None,
    link: str | None = None,
    from_email: str | None = None,
) -> Sent:
    """Experimental. Send the declared message ``kind`` to ``to`` (see the module docstring).

    :param to: users, people, addresses, or a list of them (:func:`recipients`).
    :param context: what the templates render with (the kind's merge fields).
    :param link: where the inbox entry leads, else the context's ``link``.
    :raises KarniValueError: E440, a kind nobody declared.
    """
    declared = find_kind(kind)
    if declared is None:
        raise KarniValueError(
            f"karni.notify: no message kind {kind!r} is declared. Declare it in the part's "
            "messages.py with karni.mail.register_kind(...).",
            code="E440",
        )
    return deliver_kind(
        declared,
        kind,
        declared.template,
        recipients(to),
        dict(context or {}),
        link=link,
        from_email=from_email,
    )


def send_mail(
    template: str,
    *,
    to: Iterable[str],
    context: Mapping[str, Any] | None = None,
    kind: str,
    from_email: str | None = None,
    reply_to: Iterable[str] | None = None,
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
) -> int:
    """Experimental. What ``karni.mail.send_templated(..., kind=...)`` does here: returns the
    emails sent. A kind nobody declared goes by email only, with no switch but the project's.
    """
    found = deliver_kind(
        find_kind(kind),
        kind,
        template,
        recipients([str(address) for address in to]),
        dict(context or {}),
        from_email=from_email,
        reply=list(reply_to) if reply_to else None,
        cc=list(cc) if cc else None,
        bcc=list(bcc) if bcc else None,
        together=True,
    )
    return found.email


def deliver_kind(
    declared: MessageKind | None,
    name: str,
    template: str,
    people: list[Recipient],
    context: dict[str, Any],
    *,
    rendered: Rendered | None = None,
    link: str | None = None,
    from_email: str | None = None,
    reply: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    together: bool = False,
) -> Sent:
    """Experimental. Send the kind ``name`` to recipients already resolved (:func:`recipients`).

    What :func:`send` and ``send_templated`` do once they know the kind and the
    people: the project's switch, the channels, each person's switch and
    unsubscribe, the inbox rows and the emails. ``declared`` is the kind's
    declaration (``None`` for a kind nobody declared: email only). ``rendered``
    replaces the rendering of ``template`` for a transactional kind (a move's
    email renders its files part by part). Each address gets its own email, so
    nobody sees who else got it: ``together=True`` sends one email to all of
    them, as ``send_templated`` always did. A marketing email is rendered per
    address, with its own unsubscribe link.
    """
    if not people or is_silenced() or not kind_enabled(name):
        return Sent()
    ways = _channels(declared)
    wants = _Wants(declared, name, people)
    marketing = declared is not None and declared.marketing and installed()
    inboxed = 0
    if "inbox" in ways:
        inboxed = _to_inbox(
            name,
            template,
            context,
            [p for p in people if p.user is not None and wants(p, "inbox")],
            link,
            rendered=None if marketing else rendered,
        )
    mailed = 0
    if "email" in ways:
        reply = reply or reply_to()
        targets = [p for p in people if p.email and wants(p, "email")]
        if marketing:
            for person in targets:
                mailed += _marketing_email(name, template, context, person, from_email, reply)
        else:
            batches = [[p.email for p in targets]] if together else [[p.email] for p in targets]
            for addresses in batches:
                if addresses:
                    mailed += deliver(
                        template,
                        to=addresses,
                        context=context,
                        from_email=from_email,
                        reply_to=reply,
                        cc=cc,
                        bcc=bcc,
                        kind=name,
                        rendered=rendered,
                    )
    return Sent(email=mailed, inbox=inboxed)


def _marketing_email(
    name: str,
    template: str,
    context: dict[str, Any],
    person: Recipient,
    from_email: str | None,
    reply: list[str] | None,
) -> int:
    """One marketing email, to one address, with its own unsubscribe link."""
    url = unsubscribe_url(person.email, name)
    return deliver(
        template,
        to=[person.email],
        context={**context, "unsubscribe_url": url},
        from_email=from_email,
        reply_to=reply,
        kind=name,
        headers={
            "List-Unsubscribe": f"<{url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _to_inbox(
    name: str,
    template: str,
    context: dict[str, Any],
    people: list[Recipient],
    link: str | None,
    *,
    rendered: Rendered | None = None,
) -> int:
    if not people:
        return 0
    from karni.notify.models import TITLE_LENGTH, Notification

    if rendered is None:
        rendered = render_templated(template, context, kind=name)
    title = rendered.subject
    if len(title) > TITLE_LENGTH:
        title = title[: TITLE_LENGTH - len(_ELLIPSIS)] + _ELLIPSIS
    target = link if link is not None else context.get("link")
    rows = [
        Notification(
            recipient=person.user,
            kind=name,
            title=title,
            body=rendered.text.strip(),
            link=str(target or "")[:500],
        )
        for person in people
    ]
    Notification.objects.bulk_create(rows)
    return len(rows)


def on_event(
    event: str,
    kind: str,
    *,
    to: Callable[[Any], Any],
    context: Callable[[Any], Mapping[str, Any]] | None = None,
    version: int = 1,
    registry: Any = None,
) -> None:
    """Experimental. Send ``kind`` each time the family event ``event`` is published.

    ``to(event)`` gives the recipients and ``context(event)`` what the message
    renders with (default: the event's declared fields). Put the call in the
    part's ``listeners.py``. A redelivered event sends nothing twice
    (:func:`karni.events.once`). ``registry`` is the events registry to
    subscribe in (the default one when ``None``).
    """
    from karni.events import once, subscribe

    def deliver_event(found: Any) -> None:
        if not once(found, f"notify:{kind}"):
            return
        values = dict(context(found)) if context is not None else dict(found.data)
        send(kind, to=to(found), context=values)

    subscribe(event, version=version, name=f"karni.notify:{kind}:{event}", registry=registry)(
        deliver_event
    )


# -- the inbox ----------------------------------------------------------------------------


def unread_count(user: Any) -> int:
    """Experimental. How many of ``user``'s notifications are unread."""
    from karni.notify.models import Notification

    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def mark_read(user: Any, ids: Iterable[Any] | None = None) -> int:
    """Experimental. Mark ``user``'s notifications ``ids`` read (every one when ``None``)."""
    from karni.notify.models import Notification

    rows = Notification.objects.filter(recipient=user, read_at__isnull=True)
    if ids is not None:
        rows = rows.filter(pk__in=list(ids))
    return rows.update(read_at=timezone.now())


def mark_unread(user: Any, ids: Iterable[Any]) -> int:
    """Experimental. Mark ``user``'s notifications ``ids`` unread again."""
    from karni.notify.models import Notification

    return Notification.objects.filter(recipient=user, pk__in=list(ids)).update(read_at=None)


def retention_days() -> int | None:
    """Experimental. ``KARNI_NOTIFY_RETENTION_DAYS``: days a notification is kept, or ``None``."""
    days = getattr(settings, "KARNI_NOTIFY_RETENTION_DAYS", None)
    return int(days) if days is not None else None


def prune(days: int | None = None) -> int:
    """Experimental. Delete notifications older than ``days`` (``KARNI_NOTIFY_RETENTION_DAYS``).

    Returns how many went. With no days given and the setting ``None``, nothing goes.
    """
    from karni.notify.models import Notification

    keep = days if days is not None else retention_days()
    if keep is None:
        return 0
    cutoff = timezone.now() - dt.timedelta(days=keep)
    deleted, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
    return int(deleted)


# -- a person's own switches ------------------------------------------------------------


def _switchable() -> list[MessageKind]:
    ours = project_channels()
    return [
        kind
        for kind in kinds()
        if kind.switchable and kind_enabled(kind.name) and set(kind.channels) & set(ours)
    ]


def receives(user: Any, kind: MessageKind) -> bool:
    """Experimental. Whether ``user`` can be in ``kind``'s audience (its ``requires``)."""
    from karni.navigation import opens

    return opens(kind.requires or "authenticated", user)


def choices(user: Any) -> list[dict[str, Any]]:
    """Experimental. Each kind ``user`` may switch, with where it goes for them now.

    The kinds the project sends (switched on in Settings, Emails) that a person
    may turn off and can receive (each kind's ``requires``: a customer never
    sees the staff's new-order email), with ``email`` and ``inbox`` as they are
    for ``user``: on, unless they switched it off, or unsubscribed from a
    marketing kind.
    """
    from karni.notify.models import Choice, Unsubscribe

    found = [kind for kind in _switchable() if receives(user, kind)]
    rows = {row.kind: row for row in Choice.objects.filter(user=user)}
    address = str(getattr(user, "email", "") or "").lower()
    gone = (
        set(Unsubscribe.objects.filter(address=address).values_list("kind", flat=True))
        if address
        else set()
    )
    ours = project_channels()
    answer: list[dict[str, Any]] = []
    for kind in found:
        row = rows.get(kind.name)
        ways = [channel for channel in kind.channels if channel in ours]
        email = "email" in ways and (row.email if row is not None else True)
        if kind.marketing and kind.name in gone:
            email = False
        answer.append(
            {
                "kind": kind.name,
                "title": kind.title,
                "describe": kind.describe,
                "audience": kind.audience,
                "marketing": kind.marketing,
                "channels": ways,
                "email": bool(email),
                "inbox": "inbox" in ways and (row.inbox if row is not None else True),
            }
        )
    return answer


def choose(
    user: Any, kind: str, *, email: bool | None = None, inbox: bool | None = None
) -> dict[str, Any]:
    """Experimental. ``user`` turns ``kind`` on or off for themselves, per channel.

    Turning a marketing kind's email on again takes back an unsubscribe of
    their address. Returns the kind as :func:`choices` lists it.

    :raises KarniValueError: E441, a kind nobody declared or one a person cannot switch.
    """
    from karni.notify.models import Choice, Unsubscribe

    declared = find_kind(kind)
    if declared is None or not declared.switchable or not receives(user, declared):
        raise KarniValueError(
            f"karni.notify: {kind!r} is not a message kind a person may switch. Their own "
            "switches cover the declared kinds that are switchable (GET /api/inbox/choices/).",
            code="E441",
        )
    with transaction.atomic():
        row, _created = Choice.objects.get_or_create(user=user, kind=kind)
        if email is not None:
            row.email = bool(email)
        if inbox is not None:
            row.inbox = bool(inbox)
        row.save()
        address = str(getattr(user, "email", "") or "").lower()
        if declared.marketing and email and address:
            Unsubscribe.objects.filter(address=address, kind=kind).delete()
    return next(
        (item for item in choices(user) if item["kind"] == kind),
        {"kind": kind, "title": declared.title, "email": row.email, "inbox": row.inbox},
    )


# -- unsubscribing ------------------------------------------------------------------------


def unsubscribe_token(address: str, kind: str) -> str:
    """Experimental. The signed token of ``address`` leaving ``kind`` (no expiry, no secret)."""
    return signing.dumps({"a": address.strip().lower(), "k": kind}, salt=TOKEN_SALT, compress=True)


def read_token(token: str) -> tuple[str, str]:
    """Experimental. ``(address, kind)`` of a token :func:`unsubscribe_token` signed.

    :raises KarniValueError: E442, a token this project did not sign.
    """
    try:
        found = signing.loads(str(token or ""), salt=TOKEN_SALT)
        address, kind = str(found["a"]), str(found["k"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise KarniValueError(
            "karni.notify: this unsubscribe link is not one this project sent. Use the link "
            "in the email as it is.",
            code="E442",
        ) from exc
    return address, kind


def unsubscribe_url(address: str, kind: str) -> str:
    """Experimental. The link a marketing email carries: ``KARNI_FRONTEND_URL`` and
    ``KARNI_NOTIFY_UNSUBSCRIBE_PATH`` with the token."""
    base = str(getattr(settings, "KARNI_FRONTEND_URL", "") or "").rstrip("/")
    path = str(
        getattr(settings, "KARNI_NOTIFY_UNSUBSCRIBE_PATH", "/api/notify/unsubscribe/?token={token}")
    )
    return base + path.format(token=quote(unsubscribe_token(address, kind), safe=""))


def unsubscribe(address: str, kind: str) -> bool:
    """Experimental. ``address`` gets no more of the marketing ``kind``. True when it is new.

    :raises KarniValueError: E441, a kind that is not a declared marketing kind.
    """
    from karni.notify.models import Unsubscribe

    declared = find_kind(kind)
    if declared is None or not declared.marketing or not declared.switchable:
        raise KarniValueError(
            f"karni.notify: {kind!r} is not a marketing message kind, so nobody unsubscribes "
            "from it. A person switches a transactional kind off in their own switches.",
            code="E441",
        )
    _row, created = Unsubscribe.objects.get_or_create(address=address.strip().lower(), kind=kind)
    return created


def resubscribe(address: str, kind: str) -> bool:
    """Experimental. Take back an unsubscribe. True when there was one."""
    from karni.notify.models import Unsubscribe

    deleted, _ = Unsubscribe.objects.filter(address=address.strip().lower(), kind=kind).delete()
    return bool(deleted)


def unsubscribed(address: str, kind: str) -> bool:
    """Experimental. Whether ``address`` left the marketing ``kind``."""
    from karni.notify.models import Unsubscribe

    return Unsubscribe.objects.filter(address=address.strip().lower(), kind=kind).exists()
