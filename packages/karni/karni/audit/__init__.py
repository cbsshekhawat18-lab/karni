"""Field-level change history (ADR 0002, P4): who changed what, from what, to what.

``AuditedModel`` records *who* touched a row; this app records *what
changed*. A model opts in once::

    class Price(BaseModel):
        class Karni:
            audit = True                      # every field
            # audit = ["amount", "currency"]  # or these only
            sensitive = ["note"]              # recorded as changed, never its value

Changes are captured at the model layer (``pre_save`` snapshot, ``post_save``
and ``post_delete``), so the API, the admin, a management command and the
shell all leave the same :class:`~karni.audit.models.ChangeLog` row: content
type, object id, actor (the current user), timestamp, action (``create`` /
``update`` / ``delete`` / ``restore``) and a JSON diff ``{field: [old, new]}``
of the changed fields only. Fields named ``password``, ``token``, ``secret``
or ``key`` are redacted without the project asking (``KARNI_AUDIT_REDACT``);
``Karni.sensitive`` adds more.

Surfaced three ways, so no project builds its own: a History tab on an
audited model's admin page, ``GET /api/<resource>/<id>/history/`` on every
``BaseViewSet`` (404 unless the model is audited; scope-aware, and a field
``Karni.field_roles`` hides from the requester is hidden here too), and
``<ChangeHistory resource= id= />`` in ``@karni/ui``.

``QuerySet.update()`` and ``bulk_update()`` bypass signals and are **not**
audited; ``karni check`` flags them on an audited model
(``audited-bulk-write``). Retention: ``KARNI_AUDIT_RETENTION_DAYS`` (off by
default) schedules :func:`karni.audit.tasks.prune_change_logs` daily.
``KARNI_AUDIT_ASYNC = True`` moves the write to a Celery task when a wide
model makes the synchronous diff too slow; history is then eventually
consistent.
"""

from __future__ import annotations

__all__ = ["REDACTED"]

REDACTED = "[redacted]"
"""The value a redacted field's old and new entries carry in a diff."""
