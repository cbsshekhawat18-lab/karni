"""The email of a move (``moves.<state>.notify`` in karni.yaml), as a message kind.

While ``karni.notify`` is installed, each move that names a recipient is a
declared message kind, ``<app_label>.<model>_<key>`` (``bookings.booking_confirmed``):
Settings, Emails lists it with its merge fields, a business may rewrite it, the
recipient may switch it off for themselves, and it goes to the channels in
``KARNI_NOTIFY_MOVE_CHANNELS`` (an email and the inbox by default).
:func:`karni.rules.send_move_email` sends it through :func:`send_move`.
The kinds are declared when ``karni.mail`` imports each app's ``messages.py``
(``karni/notify/messages.py`` calls :func:`declare_move_kinds`).

Override / escape hatch: a model's ``notify_move(key)`` replaces the sending,
``karni.mail.register_kind`` of the same name in the part's ``messages.py``
replaces the declaration (a part's own wins), and the template
``<app>/email/<model>_<key>_*.txt`` replaces the text, one part at a time as
before (an own subject with Karni's default body is fine).
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import models
from django.template import TemplateDoesNotExist
from django.template.loader import get_template, render_to_string, select_template

from karni.mail import (
    Rendered,
    base_context,
    edited_template,
    find_kind,
    merge_values,
    register_kind,
    render_edited,
)

__all__ = [
    "MOVE_FIELDS",
    "declare_move_kinds",
    "move_context",
    "move_template",
    "render_move",
    "send_move",
]

#: What an edited move email may use, and what each means.
MOVE_FIELDS: dict[str, str] = {
    "row": "The record, as its name reads",
    "model": "What the record is (a booking)",
    "state": "The state it moved to",
    "recipient.first_name": "The recipient's first name",
    "recipient.email": "The recipient's email address",
    "frontend": "The app's address",
}
#: The template every move email falls back to.
DEFAULT_TEMPLATE = "karni/email/move"


def move_template(model: type[models.Model], key: str) -> str:
    """``<app>/email/<model>_<key>`` when the project has it, else Karni's."""
    meta = model._meta
    own = f"{meta.app_label}/email/{meta.model_name}_{key.replace(':', '_')}"
    try:
        get_template(f"{own}_subject.txt")
    except TemplateDoesNotExist:
        return DEFAULT_TEMPLATE
    return own


def _channels() -> tuple[str, ...]:
    chosen = getattr(settings, "KARNI_NOTIFY_MOVE_CHANNELS", ("email", "inbox"))
    return tuple(chosen or ("email",))


def declare_move_kinds() -> None:
    """Declare each move's email as a message kind (a part's own declaration wins)."""
    from karni.preferences.registry import move_email_name
    from karni.rules import rules_of

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
            register_kind(
                move_email_name(model, move.key),
                title=f"{str(meta.verbose_name).capitalize()}: {state.replace('_', ' ')}",
                template=move_template(model, move.key),
                audience=f"the row's {move.notify.replace('__', ' ')}",
                describe=f"Sent to the row's {move.notify.replace('__', ' ')} when the "
                f"{meta.verbose_name} moves to {state}.",
                fields=MOVE_FIELDS,
                samples={
                    "row": f"{meta.verbose_name} 1001",
                    "model": meta.verbose_name,
                    "state": state,
                },
                channels=_channels(),
                replace=False,
            )


def move_context(instance: models.Model, key: str, recipient: Any) -> dict[str, Any]:
    """What a move's email renders with."""
    from karni.rules import rules_of

    move = next(item for item in rules_of(type(instance)).moves if item.key == key)
    return {
        "row": instance,
        "key": key,
        "state": "true" if move.to is True else move.to,
        "recipient": recipient,
        "frontend": str(getattr(settings, "KARNI_FRONTEND_URL", "")).rstrip("/"),
        "model": instance._meta.verbose_name,
    }


def render_move(instance: models.Model, key: str, context: dict[str, Any]) -> Rendered:
    """A move's email rendered: the text a business edited, else the files.

    Each file is ``<app>/email/<model>_<key>_<part>``, else Karni's
    ``karni/email/move_<part>``, part by part, and the HTML part only from the
    project's own ``_body.html``.
    """
    from karni.preferences.registry import move_email_name

    model = type(instance)
    name = move_email_name(model, key)
    edited = edited_template(name)
    declared = find_kind(name)
    if edited is not None and declared is not None:
        return render_edited(edited, merge_values(declared.fields, context))
    meta = model._meta
    own = f"{meta.app_label}/email/{meta.model_name}_{key.replace(':', '_')}"
    values = {**base_context(), **context}

    def part(name: str) -> str:
        return str(select_template([f"{own}_{name}", f"{DEFAULT_TEMPLATE}_{name}"]).render(values))

    try:
        html: str | None = render_to_string(f"{own}_body.html", values)
    except TemplateDoesNotExist:
        html = None
    return Rendered(" ".join(part("subject.txt").split()), part("body.txt"), html)


def send_move(instance: models.Model, key: str, recipient: Any) -> int:
    """Send the email of ``instance``'s move ``key`` to ``recipient`` (a user).

    Returns the emails sent. The inbox gets it too when the kind's channels
    name it, and the recipient's own switch for the kind holds.
    """
    from karni.notify.services import deliver_kind, recipients
    from karni.preferences.registry import move_email_name

    model = type(instance)
    name = move_email_name(model, key)
    context = move_context(instance, key, recipient)
    sent = deliver_kind(
        find_kind(name),
        name,
        move_template(model, key),
        recipients([recipient]),
        context,
        rendered=render_move(instance, key, context),
    )
    return sent.email
