# mypy: ignore-errors
# Known-good fixture for `karni rules --check`: Karni-style code, zero findings.
from django.db import models
from rest_framework.decorators import action
from rest_framework.response import Response

from karni.api import Access, Authenticated, BaseViewSet, Owned
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
    access = Access(read=Owned("created_by"), write=Authenticated())
    search_fields = ["number"]

    @action(detail=False)
    def unpaid(self, request):
        return self.paginated_response(self.get_queryset().filter(paid=False))

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        return Response({"created": len(serializer.save())})


class ArchivedInvoiceViewSet(InvoiceViewSet):
    # karni: allow(access-override): archived rows are filtered by the retention service
    def filter_queryset_for_user(self, queryset):
        return queryset


def legacy_report() -> list[Invoice]:
    # karni: allow(raw-sql): window function the ORM cannot express, reviewed 2026-10
    return list(Invoice.objects.raw("SELECT * FROM invoice"))
