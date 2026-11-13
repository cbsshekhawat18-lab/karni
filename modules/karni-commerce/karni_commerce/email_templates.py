"""Experimental. The emails a business edits in the app (``/api/email-templates/``).

Each declared email (:func:`karni.mail.kinds`) shows its merge fields, its
switch and its text now: the edited one (:class:`~karni_commerce.models.EmailTemplate`)
or the template files, read as they are. An edit is checked by the restricted
engine before it is kept (:func:`karni.mail.check_edited`), and a preview renders
a draft with sample values made from the merge fields' names.

Until the family's notifications contract keeps them: this module, the table
and the API go then, and ``KARNI_MAIL_SOURCE`` points at the contract.
"""

from __future__ import annotations

from typing import Any

from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from karni.mail import EditedTemplate, MessageKind, check_edited, render_edited
from rest_framework.exceptions import ValidationError

from karni_commerce import preferences_seam as preferences
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
    """Values for a preview: each merge field shows its own name, and a list two rows."""
    found: dict[str, Any] = {}
    for path in kind.fields:
        parts = path.split(".")
        target: Any = found
        for depth, part in enumerate(parts):
            last = depth == len(parts) - 1
            if part in ("lines", "tax_lines") and not last:
                rows = target.setdefault(part, [{}, {}])
                for row in rows:
                    row[".".join(parts[depth + 1 :])] = f"[{path}]"
                break
            if last:
                target[part] = f"[{path}]"
            else:
                target = target.setdefault(part, {})
    return _nest(found)


def _nest(values: Any) -> Any:
    """``{"a.b": 1}`` inside list rows as ``{"a": {"b": 1}}``."""
    if isinstance(values, list):
        return [_nest(row) for row in values]
    if not isinstance(values, dict):
        return values
    nested: dict[str, Any] = {}
    for key, value in values.items():
        target = nested
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = _nest(value)
    return nested


def preview(kind: MessageKind, subject: str, text: str) -> dict[str, Any]:
    """A draft rendered with :func:`sample_values` (or its problems)."""
    problems = check_edited(subject, text)
    if problems:
        raise ValidationError({part: [problem] for part, problem in problems.items()})
    rendered = render_edited(EditedTemplate(subject, text), sample_values(kind))
    return {"subject": rendered.subject, "text": rendered.text, "html": rendered.html}
