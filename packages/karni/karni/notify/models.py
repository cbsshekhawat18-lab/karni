"""The notifications contract's tables: edited emails, the inbox, each person's switches.

* :class:`EmailTemplate`: a message a business rewrote in the app (Settings,
  Emails). It wins over the template files and renders with ``karni.mail``'s
  restricted engine.
* :class:`Notification`: one message in one person's inbox, read or not.
* :class:`Choice`: a person's own switch for one kind, per channel.
* :class:`Unsubscribe`: an address that asked for no more of a marketing kind,
  from the signed link in the email. Kept by address, so a guest with no account
  is honoured too, in every part that sends that kind.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from karni.fields import LiveUniqueConstraint
from karni.models import BaseModel

__all__ = ["Choice", "EmailTemplate", "Notification", "Unsubscribe"]

#: The longest title a notification keeps. A longer one is cut, ending with "...".
TITLE_LENGTH = 300


class EmailTemplate(BaseModel):
    """Experimental. An email a business rewrote in the app: its subject and text, by kind.

    It wins over the template files (``karni.mail``'s ``KARNI_MAIL_SOURCE``), and
    renders with the restricted engine: the kind's merge fields only. Deleting
    the row puts the files back.
    """

    kind = models.CharField(max_length=120)
    subject = models.CharField(max_length=300)
    text = models.TextField()

    class Meta:
        ordering = ["kind"]
        constraints = [LiveUniqueConstraint(fields=["kind"], name="notify_email_template_kind")]

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.kind


class Notification(models.Model):
    """Experimental. One message in one person's inbox.

    ``kind`` is the message kind it was sent as (``commerce.order_paid``),
    ``title`` and ``body`` the message as it was rendered, in plain text, and
    ``link`` where it leads in the app (the order's page). ``read_at`` is empty
    while it is unread.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=TITLE_LENGTH)
    body = models.TextField(blank=True, default="")
    link = models.CharField(max_length=500, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["recipient", "-created_at", "-id"], name="notify_inbox_recent"),
            models.Index(
                fields=["recipient"],
                condition=Q(read_at__isnull=True),
                name="notify_inbox_unread",
            ),
            models.Index(fields=["created_at"], name="notify_created"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind})"

    @property
    def unread(self) -> bool:
        return self.read_at is None


class Choice(models.Model):
    """Experimental. A person's own switch for one message kind: email and inbox, on or off.

    No row means both are on. A kind declared not ``switchable`` (a sign-in
    code) ignores it.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notify_choices"
    )
    kind = models.CharField(max_length=120)
    email = models.BooleanField(default=True)
    inbox = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user", "kind")
        constraints = [
            models.UniqueConstraint(fields=["user", "kind"], name="notify_one_choice_per_kind")
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.kind}: email {self.email}, inbox {self.inbox}"


class Unsubscribe(models.Model):
    """Experimental. An address that asked for no more of a marketing kind.

    ``address`` is lower-cased. A person who signs in turns the kind on again
    in their own switches (``PATCH /api/inbox/choices/<kind>/``), which deletes
    the row.
    """

    address = models.EmailField(max_length=254)
    kind = models.CharField(max_length=120)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["address", "kind"], name="notify_one_unsubscribe")
        ]

    def __str__(self) -> str:
        return f"{self.address} {self.kind}"
