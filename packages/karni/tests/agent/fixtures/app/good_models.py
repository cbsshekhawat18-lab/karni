# mypy: ignore-errors
# Known-good fixture for `karni rules --check`: Karni-style code, zero findings.
from django.db import models

from karni.api import BaseViewSet
from karni.models import BaseModel, TimestampedModel, UUIDModel


class Invoice(BaseModel):
    number = models.CharField(max_length=20)

    class AdminMeta:
        list_display = ["number"]


class AccessLog(UUIDModel, TimestampedModel):
    path = models.CharField(max_length=200)


class Base(models.Model):
    class Meta:
        abstract = True


class InvoiceViewSet(BaseViewSet):
    model = Invoice
    search_fields = ["number"]


def legacy_report() -> list[Invoice]:
    # karni: allow(raw-sql): window function the ORM cannot express, reviewed 2026-10
    return list(Invoice.objects.raw("SELECT * FROM invoice"))
