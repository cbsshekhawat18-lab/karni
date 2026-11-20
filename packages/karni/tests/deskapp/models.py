"""A ticket that staff close: the publisher's own record."""

from __future__ import annotations

from django.db import models

from karni.models import BaseModel


class Ticket(BaseModel):
    """A request for help, open until staff close it."""

    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, default="open")
    requester = models.CharField(max_length=64, blank=True, default="")

    def __str__(self) -> str:
        return self.title
