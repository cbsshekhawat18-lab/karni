"""Karni's own signals.

``pre_write`` is sent by :class:`karni.models.BaseModel` before a row is
created, updated or deleted — before any SQL, outside any transaction the
save would open — with ``instance``, ``action`` (``"create"``, ``"update"``
or ``"delete"``) and ``update_fields``. A receiver may **stop the write** by
raising :class:`karni.exceptions.KarniWriteDeferred`: the API then answers
202 with the exception's payload, the admin shows its message and redirects,
and plain code gets the exception. That is how ``karni-approvals`` turns a
maker's change into a pending change instead of a write.

Unlike Django's ``pre_save`` it is never sent for bulk operations
(``QuerySet.update()``, ``bulk_create()``), raw saves or fixture loading —
the ``audited-bulk-write`` architecture rule exists for that gap — and it
fires once per ``delete()`` (not again for the ``deleted_at`` save a soft
delete performs).

Override / escape hatch: a receiver decides for itself which models it
cares about (``sender``); nothing here filters. Connect with
``dispatch_uid`` so a reload never doubles it.
"""

from __future__ import annotations

from django.dispatch import Signal

__all__ = ["pre_write"]

#: ``send(sender=<model class>, instance=, action=, update_fields=)``.
pre_write = Signal()
