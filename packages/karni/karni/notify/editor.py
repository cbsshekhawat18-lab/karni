"""Experimental. The emails a business edits in the app (``/api/email-templates/``).

Each declared message kind (:func:`karni.mail.kinds`) shows its merge fields, its
switch and its text now: the edited one (:class:`~karni.notify.models.EmailTemplate`)
or the template files, read as they are. An edit is checked by the restricted
engine before it is kept (:func:`karni.mail.check_edited`), and a preview renders
a draft with real values: the business's details and the latest matching record, or
the kind's declared samples when there is none yet (:func:`karni.mail.sample_context`).

Override / escape hatch: subclass :class:`karni.notify.viewsets.EmailTemplateViewSet`
and route it yourself (``KARNI_NOTIFY_API = False``), or call these functions from
a view of your own.
"""

from __future__ import annotations

from typing import Any

from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from rest_framework.exceptions import ValidationError

from karni.mail import (
    EditedTemplate,
    MessageKind,
    check_edited,
    kind_enabled,
    merge_values,
    render_edited,
    sample_context,
)
from karni.notify.models import EmailTemplate

__all__ = ["describe", "file_source", "preview", "sample_values", "save"]


def file_source(stem: str, part: str) -> str:
    """Experimental. The text of a template file as a project has it (its own copy first)."""
    try:
        template = get_template(f"{stem}_{part}.txt")
    except TemplateDoesNotExist:
        return ""
    inner = getattr(template, "template", template)
    return str(getattr(inner, "source", "") or "")


def describe(kind: MessageKind, row: EmailTemplate | None) -> dict[str, Any]:
    """Experimental. One email as the editor shows it."""
    return {
        "kind": kind.name,
        "title": kind.title,
        "describe": kind.describe,
        "audience": kind.audience,
        "switchable": kind.switchable,
        "on": kind_enabled(kind.name),
        "channels": list(kind.channels),
        "marketing": kind.marketing,
        "fields": [{"name": name, "meaning": meaning} for name, meaning in kind.fields.items()],
        "edited": row is not None,
        "subject": row.subject
        if row is not None
        else file_source(kind.template, "subject").strip(),
        "text": row.text if row is not None else file_source(kind.template, "body"),
        "updated_at": row.updated_at.isoformat() if row is not None else None,
    }


def save(kind: MessageKind, subject: str, text: str) -> EmailTemplate:
    """Experimental. Keep an edited email, once the restricted engine accepts it."""
    problems = check_edited(subject, text)
    if problems:
        raise ValidationError({part: [problem] for part, problem in problems.items()})
    row, _created = EmailTemplate.objects.update_or_create(
        kind=kind.name, defaults={"subject": subject.strip(), "text": text}
    )
    return row


def sample_values(kind: MessageKind) -> dict[str, Any]:
    """Experimental. The values a preview renders with: real ones
    (:func:`karni.mail.sample_context`), read through the kind's merge fields."""
    return merge_values(kind.fields, sample_context(kind))


def preview(kind: MessageKind, subject: str, text: str) -> dict[str, Any]:
    """Experimental. A draft rendered with :func:`sample_values` (or its problems)."""
    problems = check_edited(subject, text)
    if problems:
        raise ValidationError({part: [problem] for part, problem in problems.items()})
    rendered = render_edited(EditedTemplate(subject, text), sample_values(kind))
    return {"subject": rendered.subject, "text": rendered.text, "html": rendered.html}
