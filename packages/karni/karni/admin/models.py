"""The admin's one table: who dismissed the *Getting started* panel (:mod:`karni.admin.guide`)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

__all__ = ["GuideDismissal"]


class GuideDismissal(models.Model):
    """A user who closed the *Getting started* panel on the admin home page.

    One row per user. The user menu's *Show the getting started guide* deletes
    it. Not registered in the admin and not part of the API.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    dismissed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "karni_admin"

    class AdminMeta:
        exclude = True

    def __str__(self) -> str:
        return f"guide dismissed by {self.user_id}"
