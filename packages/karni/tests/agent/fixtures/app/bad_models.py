# mypy: ignore-errors
# ruff: noqa
# Known-bad fixture for `karni rules --check`: every line marked "K###" must be
# reported with that code. Never imported; parsed only.
import requests  # K105
from django.contrib import admin
from django.db import connection, models
from karni.api import BaseViewSet
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


class Invoice(models.Model):  # K101
    number = models.CharField(max_length=20)


class InvoiceAdmin(admin.ModelAdmin):  # K103
    list_display = ["number"]


admin.site.register(Invoice)  # K103


class InvoiceSerializer(serializers.ModelSerializer):  # K106
    class Meta:
        model = Invoice
        fields = "__all__"


class InvoiceViewSet(viewsets.ModelViewSet):  # K102
    queryset = Invoice.objects.all()


class ReceiptViewSet(BaseViewSet):  # K109
    model = Invoice

    def filter_queryset_for_user(self, queryset):  # K110
        return queryset

    @action(detail=False)
    def recent(self, request):
        rows = self.get_queryset()[:500]
        return Response(InvoiceSerializer(rows, many=True).data)  # K111


def totals() -> list[object]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")  # K104
    return list(Invoice.objects.raw("SELECT * FROM invoice"))  # K104


def ping() -> None:
    requests.get("https://example.com")  # karni: allow(http-client)
