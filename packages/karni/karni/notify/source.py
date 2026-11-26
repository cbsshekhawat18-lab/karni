"""``karni.mail``'s default source (``KARNI_MAIL_SOURCE``): notifications.

:class:`NotifySource` answers ``karni.mail`` while ``karni.notify`` is installed:

* ``template(kind)``: the email a business rewrote in the app
  (:class:`~karni.notify.models.EmailTemplate`, ``/api/email-templates/``), which
  wins over the template files;
* ``enabled(kind)`` and ``sender()``: the switches and the sender of the
  preferences contract (Settings, Emails and Details), as
  :class:`karni.mail.DefaultSource` reads them;
* ``send(...)``: every message with a kind is delivered by
  :func:`karni.notify.services.send_mail`, so each person's own switches and
  unsubscribes hold, and a kind declared on the inbox lands there too.

Without the app it is :class:`karni.mail.DefaultSource` with the same
delivery as before: the files, the switches and the sender of
``karni.preferences``, email only.

Import-light: it is the default in every project, so the models are imported
only when asked.

Override / escape hatch: ``KARNI_MAIL_SOURCE`` pointing at a subclass (or any
object with the same methods), or blank for :class:`karni.mail.DefaultSource`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from karni.mail import DefaultSource, EditedTemplate, deliver, kind_enabled

__all__ = ["NotifySource"]


class NotifySource(DefaultSource):
    """Edited emails, each person's switches and the inbox (see the module)."""

    @staticmethod
    def _installed() -> bool:
        from django.apps import apps

        return apps.is_installed("karni.notify")

    def keeps_edits(self) -> bool:
        return self._installed()

    def template(self, kind: str) -> EditedTemplate | None:
        if not self._installed():
            return None
        from karni.notify.models import EmailTemplate

        row = EmailTemplate.objects.filter(kind=kind).first()
        return EditedTemplate(row.subject, row.text) if row is not None else None

    def send(
        self,
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
        """Deliver the message ``kind``: the emails sent (see the module docstring)."""
        if not self._installed():
            if not kind_enabled(kind):
                return 0
            return deliver(
                template,
                to=to,
                context=context,
                from_email=from_email,
                reply_to=reply_to,
                cc=cc,
                bcc=bcc,
                kind=kind,
            )
        from karni.notify.services import send_mail

        return send_mail(
            template,
            to=to,
            context=context,
            kind=kind,
            from_email=from_email,
            reply_to=reply_to,
            cc=cc,
            bcc=bcc,
        )
