"""Forms a site might have: a clinic's appointment request, a school's newsletter, a workshop's
job application, and a members-only feedback form."""

from __future__ import annotations

from django.db import models
from karni.fields import EmailField, PhoneField, StateField
from karni.models import BaseModel


class AppointmentRequest(BaseModel):
    name = models.CharField(max_length=80)
    email = EmailField()
    phone = PhoneField(blank=True)

    class Reason(models.TextChoices):
        CHECKUP = "checkup", "Check-up"
        VACCINE = "vaccine", "Vaccination"
        OTHER = "other", "Something else"

    reason = models.CharField(max_length=20, choices=Reason.choices)
    day = models.DateField()
    message = models.TextField(blank=True, help_text="Anything the doctor should know.")
    first_visit = models.BooleanField(default=False)
    status = StateField(
        states=["new", "booked", "declined"],
        transitions={"new": ["booked", "declined"]},
    )
    notes = models.TextField(blank=True)

    class Karni:
        audit = True
        field_roles = {"status": ["staff"], "notes": ["staff"]}

    def __str__(self) -> str:
        return self.name


class Subscriber(BaseModel):
    email = EmailField()

    def __str__(self) -> str:
        return self.email


class Application(BaseModel):
    name = models.CharField(max_length=80)
    cv = models.FileField(upload_to="formapp/cv/")

    def __str__(self) -> str:
        return self.name


class Feedback(BaseModel):
    message = models.TextField()

    def __str__(self) -> str:
        return self.message[:40]
