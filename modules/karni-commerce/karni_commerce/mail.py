"""Experimental. ``karni.mail``'s source that commerce once named (``KARNI_MAIL_SOURCE``).

The emails a business edits moved to the notifications contract: the table is
:class:`karni.notify.models.EmailTemplate`, the API ``/api/email-templates/`` of
``karni.notify``, and ``karni.notify.source.NotifySource`` is the default
``KARNI_MAIL_SOURCE`` of every project. :class:`MailSource` is that source under
its old name, so a deployment whose settings still name it keeps working.

Override / escape hatch: ``KARNI_MAIL_SOURCE`` pointing at a source of your own (a
subclass of :class:`karni.notify.source.NotifySource`, or of
:class:`karni.mail.DefaultSource`).
"""

from __future__ import annotations

from karni.notify.source import NotifySource

__all__ = ["MailSource"]


class MailSource(NotifySource):
    """Experimental. :class:`karni.notify.source.NotifySource` under the name commerce gave it.

    Remove ``KARNI_MAIL_SOURCE`` from the settings (the default is the same source).
    """
