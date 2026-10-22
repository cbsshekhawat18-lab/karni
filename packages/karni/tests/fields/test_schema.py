"""``karni schema`` lists what each declaration created, and why, and checks the database has it."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection

from karni.exceptions import KarniCommandError
from karni.fields.schema import describe
from tests.fieldsapp.models import Customer, LogEntry, Product

pytestmark = pytest.mark.django_db
POSTGRES = connection.vendor == "postgresql"


def _report(*labels: str) -> list[dict[str, Any]]:
    out = StringIO()
    call_command("karni_schema", *labels, "--json", stdout=out)
    data: list[dict[str, Any]] = json.loads(out.getvalue())
    return data


def _objects(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["definition"]: item for item in report["objects"]}


def _find(report: dict[str, Any], needle: str) -> dict[str, Any]:
    matches = [item for item in report["objects"] if needle in item["definition"]]
    assert matches, f"{needle!r} not in {[i['definition'] for i in report['objects']]}"
    return matches[0]


def test_json_lists_every_karni_object_with_its_reason() -> None:
    (product,) = _report("fieldsapp.Product")
    assert product["label"] == "fieldsapp.Product" and product["introspected"] is True
    columns = {column["name"]: column for column in product["columns"]}
    assert columns["price"]["why"].startswith('MoneyField(currency="EUR"): NUMERIC(19,4)')
    assert columns["search"]["type"].endswith("(generated)")
    assert "from TimestampedModel" in columns["created_at"]["why"]

    slug = _find(product, '("slug") WHERE "deleted_at" IS NULL')
    assert slug["kind"] == "constraint" and slug["status"] == "present"
    assert "soft-deleted row's value can be reused" in slug["why"]

    stock = _find(product, '"stock" >= 0')
    assert stock["kind"] == "check" and stock["status"] == "present"
    assert stock["why"] == "QuantityField: integer, CHECK >= 0"

    gin = _find(product, "gin" if POSTGRES else "GinIndex")
    assert gin["status"] == ("present" if POSTGRES else "skipped")
    assert "SearchField" in gin["why"] or "JSONField(queried=True)" in gin["why"]

    fk = next(i for i in product["objects"] if i["columns"] == ["created_by_id"])
    assert "Django indexes every foreign key" in fk["why"] and fk["status"] == "present"
    assert product["unexplained"] == []


def test_case_insensitive_email_is_explained() -> None:
    (customer,) = _report("fieldsapp.Customer")
    unique = _find(customer, 'LOWER("email")')
    assert unique["status"] == "present"
    assert unique["why"].startswith("EmailField(unique=True): unique, lower-cased, among live")


def test_append_only_brin_replaces_the_btree() -> None:
    report = describe(LogEntry)
    kinds = {item.name: item for item in report.objects}
    assert not any(
        item.columns == ["created_at"] and "INDEX (" in item.definition for item in report.objects
    )
    brin = next(item for item in kinds.values() if item.name.endswith("_brin"))
    assert brin.why.startswith("Karni.append_only: BRIN instead of a B-tree on created_at")
    assert brin.status == ("present" if POSTGRES else "skipped")


def test_text_output_reads_like_the_json() -> None:
    out = StringIO()
    call_command("karni_schema", "fieldsapp.Customer", stdout=out)
    text = out.getvalue()
    assert text.startswith("fieldsapp.Customer  (table fieldsapp_customer,")
    assert "why: EmailField(unique=True)" in text and "[ok]" in text


def test_declared_usage_shows_what_serves_each_column() -> None:
    class ProductViewSet:
        model = Product
        search_fields = ["search"]
        filterset_fields = ["made_in", "slug"]
        ordering_fields = ["price"]

    usage = {
        (row.kind, row.field): row for row in describe(Product, viewsets=[ProductViewSet]).usage
    }
    assert usage[("search", "search")].covered_by == "SearchField search (GIN)"
    assert usage[("filter", "slug")].covered_by is not None
    assert usage[("filter", "slug")].covered_by.startswith("unique constraint")
    assert usage[("filter", "made_in")].covered_by is None
    assert 'models.Index(fields=["made_in"]' in str(usage[("filter", "made_in")].fix)
    assert usage[("order", "price")].covered_by is None


def test_without_the_database_it_reports_declarations_only() -> None:
    report = describe(Customer, introspect=False)
    assert report.introspected is False
    assert {item.status for item in report.objects} <= {"unknown", "skipped"}


def test_an_unknown_label_names_the_fix() -> None:
    with pytest.raises(KarniCommandError, match="E969"):
        call_command("karni_schema", "fieldsapp.Nope", stdout=StringIO())


def test_a_hand_made_index_is_reported_as_undeclared() -> None:
    with connection.cursor() as cursor:
        cursor.execute('CREATE INDEX "karni_fields_stray_idx" ON "fieldsapp_customer" ("name")')
    report = describe(Customer)
    assert any(
        line.startswith("karni_fields_stray_idx: index on name") for line in report.unexplained
    )
