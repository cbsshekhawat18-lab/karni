"""Read side: a row's history, for the API, the admin and anything else that shows it."""

from __future__ import annotations

from typing import Any

from django.db import models

from karni.audit.capture import audited_fields
from karni.audit.models import ChangeLog, ChangeLogQuerySet

__all__ = ["audited", "history_for"]


def audited(model: type[models.Model]) -> bool:
    """Whether ``Karni.audit`` opts ``model`` in."""
    return audited_fields(model) is not None


def history_for(obj: models.Model) -> ChangeLogQuerySet:
    """The entries of ``obj``, newest first, with the actor joined.

    Visibility (``Karni.field_roles``) is applied when an entry is rendered
    for a user — :meth:`ChangeLog.visible_diff` — not here, so the queryset
    stays a queryset.
    """
    queryset: Any = ChangeLog.objects.for_object(obj).select_related("actor")
    return queryset
