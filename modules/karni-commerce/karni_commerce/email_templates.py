"""Experimental. The emails a business edits in the app (``/api/email-templates/``).

Each declared email (:func:`karni.mail.kinds`) shows its merge fields, its
switch and its text now: the edited one (:class:`~karni_commerce.models.EmailTemplate`)
or the template files, read as they are. An edit is checked by the restricted
engine before it is kept (:func:`karni.mail.check_edited`), and a preview renders
a draft with real values: the business's details and the latest matching record, or
the kind's declared samples when there is none yet (:func:`karni.mail.sample_context`).

:class:`karni_commerce.mail.MailSource` is ``karni.mail``'s ``KARNI_MAIL_SOURCE``
for a project with commerce: an edited email from here, its switch and the sender
from ``karni.preferences`` (Settings, Emails and Details).

Until the family's notifications contract keeps them: this module, the table
and the API go then, and ``KARNI_MAIL_SOURCE`` points at the contract.
"""

from __future__ import annotations

from typing import Any

from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from karni import preferences
from karni.mail import (
    EditedTemplate,
    MessageKind,
    check_edited,
    merge_values,
    render_edited,
    sample_context,
)
from rest_framework.exceptions import ValidationError

from karni_commerce.models import EmailTemplate

__all__ = ["describe", "file_source", "preview", "sample_values", "save"]


def file_source(stem: str, part: str) -> str:
    """The text of a template file as a project has it (its own copy first)."""
    try:
        template = get_template(f"{stem}_{part}.txt")
    except TemplateDoesNotExist:
        return ""
    inner = getattr(template, "template", template)
    return str(getattr(inner, "source", "") or "")


def describe(kind: MessageKind, row: EmailTemplate | None) -> dict[str, Any]:
    """One email as the editor shows it."""
    return {
        "kind": kind.name,
        "title": kind.title,
        "describe": kind.describe,
        "audience": kind.audience,
        "switchable": kind.switchable,
        "on": preferences.email_on(kind.name),
        "fields": [{"name": name, "meaning": meaning} for name, meaning in kind.fields.items()],
        "edited": row is not None,
        "subject": row.subject
        if row is not None
        else file_source(kind.template, "subject").strip(),
        "text": row.text if row is not None else file_source(kind.template, "body"),
        "updated_at": row.updated_at.isoformat() if row is not None else None,
    }


def save(kind: MessageKind, subject: str, text: str) -> EmailTemplate:
    """Keep an edited email, once the restricted engine accepts it."""
    problems = check_edited(subject, text)
    if problems:
        raise ValidationError({part: [problem] for part, problem in problems.items()})
    row, _created = EmailTemplate.objects.update_or_create(
        kind=kind.name, defaults={"subject": subject.strip(), "text": text}
    )
    return row


def sample_values(kind: MessageKind) -> dict[str, Any]:
    """The values a preview renders with: real ones (:func:`karni.mail.sample_context`).

    The business's details, and the latest matching record (the last paid order for
    the confirmation), or the kind's declared samples when there is none yet.
    """
    return merge_values(kind.fields, sample_context(kind))


def preview(kind: MessageKind, subject: str, text: str) -> dict[str, Any]:
    """A draft rendered with :func:`sample_values` (or its problems)."""
    problems = check_edited(subject, text)
    if problems:
        raise ValidationError({part: [problem] for part, problem in problems.items()})
    rendered = render_edited(EditedTemplate(subject, text), sample_values(kind))
    return {"subject": rendered.subject, "text": rendered.text, "html": rendered.html}
