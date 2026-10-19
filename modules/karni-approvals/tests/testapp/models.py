"""The project under test: what a real app guarding high-value changes looks like."""

from __future__ import annotations

from datetime import timedelta

from django.db import models
from karni.models import BaseModel


class Branch(BaseModel):
    name = models.CharField(max_length=100)

    class Karni:
        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Invoice(BaseModel):
    """Two guarded fields; one approval by anyone holding the approve permission."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PAID = "paid", "Paid"

    number = models.CharField(max_length=30)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(max_length=200, blank=True, default="")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)

    class Karni:
        requires_approval = ["amount", "status"]
        scope_paths = {"branch": "branch"}
        audit = True

    def __str__(self) -> str:
        return f"Invoice {self.number}"


class Contract(BaseModel):
    """Any change held — creates and deletes too — needing two finance approvals within an hour."""

    title = models.CharField(max_length=100)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Karni:
        requires_approval = True
        approvals_required = 2
        approver_roles = ["finance"]
        approval_timeout = timedelta(hours=1)
        approval_on_timeout = "escalate"
        approval_escalation_roles = ["staff"]

    def __str__(self) -> str:
        return self.title


class Memo(BaseModel):
    """No policy: never held."""

    text = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.text
