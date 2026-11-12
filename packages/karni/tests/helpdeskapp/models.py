"""Support profiles, tickets, and notes on any record."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from karni.models import BaseModel


class SupportProfile(BaseModel):
    """The part's profile of a person: their support plan."""

    person = models.OneToOneField(
        "people.Person", on_delete=models.CASCADE, related_name="support_profile"
    )
    plan = models.CharField(max_length=20, default="basic")

    class Meta(BaseModel.Meta):
        app_label = "helpdeskapp"


class Ticket(BaseModel):
    """A support request. The contact's name and email are copied at the time."""

    person = models.ForeignKey("people.Person", on_delete=models.PROTECT, related_name="tickets")
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=20, default="open")
    contact_name = models.CharField(max_length=200, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    class Meta(BaseModel.Meta):
        app_label = "helpdeskapp"

    class Karni:
        audit = True
        owner_field = "person__user"


class Note(BaseModel):
    """A note on any record: a person, a ticket, an organisation."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64)
    subject = GenericForeignKey("content_type", "object_id")
    text = models.TextField()

    class Meta(BaseModel.Meta):
        app_label = "helpdeskapp"
