"""The render task, with the fake renderer: claim, render, store, and what goes wrong."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from karni_reports import get_report, services
from karni_reports.models import GeneratedReport
from karni_reports.rendering import FakeRenderer
from karni_reports.tasks import render_report
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db


def _queued(product: Product) -> GeneratedReport:
    return services.request(get_report("product-sheet"), product, queue=False)


def test_the_task_renders_a_pending_row_once(product: Product) -> None:
    row = _queued(product)
    assert row.status == "pending" and not row.file
    assert render_report.delay(str(row.pk)).get() == "ready"
    row.refresh_from_db()
    assert row.is_ready and row.size == len(row.file.read()) and row.rendered_at is not None
    assert row.file.name.startswith("karni/reports/product-sheet/")
    assert render_report.delay(str(row.pk)).get() == "skipped"  # no longer pending
    assert len(FakeRenderer.rendered) == 1


def test_a_request_queues_the_task_on_commit(
    product: Product, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks() as callbacks:
        row = services.request(get_report("product-sheet"), product)
    assert len(callbacks) == 1 and not FakeRenderer.rendered
    callbacks[0]()
    row.refresh_from_db()
    assert row.status == "ready"


def test_a_failure_is_stored_on_the_row(product: Product, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: Any, obj: Any) -> dict[str, Any]:
        raise KeyError("price_band")

    monkeypatch.setattr(type(get_report("product-sheet")), "get_context", broken)
    row = GeneratedReport.objects.create(
        report="product-sheet",
        content_type_id=_content_type_id(),
        object_id=str(product.pk),
        template="products/product_sheet.html",
        template_version="t",
        data_version="d",
    )
    assert render_report.delay(str(row.pk)).get() == "failed"
    row.refresh_from_db()
    assert row.status == "failed" and "KeyError" in row.error and "price_band" in row.error


def test_a_deleted_row_fails_the_render(product: Product) -> None:
    row = _queued(product)
    product.delete()  # soft delete: the default manager no longer finds it
    assert render_report.delay(str(row.pk)).get() == "failed"
    row.refresh_from_db()
    assert "DoesNotExist" in row.error


def test_the_file_holds_the_row_as_it_is_when_rendered(product: Product) -> None:
    row = _queued(product)
    product.price = Decimal("12.50")
    product.save()  # changed between the request and the render
    render_report.delay(str(row.pk)).get()
    row.refresh_from_db()
    assert "12.50" in FakeRenderer.rendered[-1]
    current = services.key_for(get_report("product-sheet"), product)
    assert row.data_version == current.data_version  # the key follows what the file holds
    assert services.request(get_report("product-sheet"), product).pk == row.pk


def test_a_stuck_render_is_queued_again(
    product: Product, django_capture_on_commit_callbacks: Any
) -> None:
    row = _queued(product)
    GeneratedReport.objects.filter(pk=row.pk).update(
        status="rendering", updated_at=timezone.now() - timedelta(hours=1)
    )
    with django_capture_on_commit_callbacks(execute=True):
        again = services.request(get_report("product-sheet"), product)
    assert again.pk == row.pk
    again.refresh_from_db()
    assert again.status == "ready"


def test_a_recent_render_in_flight_is_not_queued_twice(
    product: Product, django_capture_on_commit_callbacks: Any
) -> None:
    _queued(product)
    with django_capture_on_commit_callbacks() as callbacks:
        services.request(get_report("product-sheet"), product)
    assert callbacks == []


def _content_type_id() -> int:
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(Product).pk
