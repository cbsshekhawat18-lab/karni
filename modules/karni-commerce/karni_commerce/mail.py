"""Experimental. ``karni.mail``'s source for a project with commerce (``KARNI_MAIL_SOURCE``).

An email the business rewrote in the app (:class:`~karni_commerce.models.EmailTemplate`,
``/api/email-templates/``) wins over the template files. The switches and the sender
are :class:`karni.mail.DefaultSource`'s: the preferences contract's (Settings, Emails
and Details) while ``karni.preferences`` is installed.

Import-light: the package's settings fragment names this class in projects that have
the package without the app, so the models are imported only when asked.

Override / escape hatch: ``KARNI_MAIL_SOURCE`` pointing at a source of your own (a
subclass of this one, or of :class:`karni.mail.DefaultSource`).
"""

from __future__ import annotations

from karni.mail import DefaultSource, EditedTemplate

__all__ = ["MailSource"]


class MailSource(DefaultSource):
    """Experimental. An email the business edited, else the files; the switches and the
    sender of the preferences contract.

    It finds no edited email while ``karni_commerce`` is not in ``INSTALLED_APPS``.
    """

    def template(self, kind: str) -> EditedTemplate | None:
        from django.apps import apps

        if not apps.is_installed("karni_commerce"):
            return None
        from karni_commerce.models import EmailTemplate

        row = EmailTemplate.objects.filter(kind=kind).first()
        return EditedTemplate(row.subject, row.text) if row is not None else None
