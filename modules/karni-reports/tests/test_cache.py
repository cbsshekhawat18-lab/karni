"""The cache key: a hit renders nothing, a changed row or template renders a new file."""

from __future__ import annotations

import copy
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.conf import LazySettings
from karni.exceptions import KarniTypeError

from karni_reports import get_report, services, versions
from karni_reports.models import GeneratedReport
from karni_reports.rendering import FakeRenderer
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db

Ready = Callable[[Product], GeneratedReport]


@pytest.fixture
def ready(django_capture_on_commit_callbacks: Any) -> Ready:
    """Request the product sheet of a product and run the queued render."""

    def _ready(product: Product) -> GeneratedReport:
        with django_capture_on_commit_callbacks(execute=True):
            row = services.request(get_report("product-sheet"), product)
        row.refresh_from_db()
        return row

    return _ready


def _templates(settings: LazySettings, directory: Path) -> None:
    """Put ``directory`` first in the template search path (a project's templates/)."""
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["DIRS"] = [str(directory)]
    settings.TEMPLATES = templates


def test_a_ready_file_is_served_again_without_rendering(product: Product, ready: Ready) -> None:
    first = ready(product)
    assert first.status == "ready" and first.file.read().startswith(b"%PDF")
    assert len(FakeRenderer.rendered) == 1 and "Desk lamp" in FakeRenderer.rendered[0]
    again = services.request(get_report("product-sheet"), product)
    assert again.pk == first.pk and again.is_ready
    assert len(FakeRenderer.rendered) == 1
    assert GeneratedReport.objects.count() == 1


def test_a_changed_row_gives_a_new_file(product: Product, ready: Ready) -> None:
    first = ready(product)
    product.price = Decimal("59.00")
    product.save()
    second = ready(product)
    assert second.pk != first.pk and second.data_version != first.data_version
    assert second.template_version == first.template_version
    assert "59.00" in FakeRenderer.rendered[-1]
    # KARNI_REPORTS_KEEP = 1: the older file and its row are gone
    assert list(GeneratedReport.objects.values_list("pk", flat=True)) == [second.pk]


def test_a_related_row_in_the_context_counts(product: Product, ready: Ready) -> None:
    first = ready(product)
    assert product.category is not None
    product.category.name = "Floor lamps"
    product.category.save()
    second = ready(Product.objects.get(pk=product.pk))
    assert second.data_version != first.data_version
    assert "Floor lamps" in FakeRenderer.rendered[-1]


def test_a_changed_template_gives_a_new_file(
    product: Product, ready: Ready, settings: LazySettings, tmp_path: Path
) -> None:
    sheet = tmp_path / "products" / "product_sheet.html"
    sheet.parent.mkdir()
    sheet.write_text('{% extends "karni_reports/base.html" %}{% block content %}v1{% endblock %}')
    _templates(settings, tmp_path)
    first = ready(product)
    assert "v1" in FakeRenderer.rendered[-1]
    sheet.write_text('{% extends "karni_reports/base.html" %}{% block content %}v2{% endblock %}')
    _templates(settings, tmp_path)  # a new engine: what a deploy gives
    second = ready(product)
    assert second.template_version != first.template_version
    assert second.data_version == first.data_version
    assert "v2" in FakeRenderer.rendered[-1] and len(FakeRenderer.rendered) == 2


def test_a_project_overrides_the_base_template_by_name(
    product: Product, ready: Ready, settings: LazySettings, tmp_path: Path
) -> None:
    report = get_report("product-sheet")
    shipped = report.get_template_version()
    base = tmp_path / "karni_reports" / "base.html"
    base.parent.mkdir()
    base.write_text(
        "<html><body><header>Our letterhead</header>{% block content %}{% endblock %}</body></html>"
    )
    _templates(settings, tmp_path)
    row = ready(product)
    assert "Our letterhead" in FakeRenderer.rendered[-1]
    assert "Desk lamp" in FakeRenderer.rendered[-1]
    assert row.template_version != shipped


def test_the_page_size_is_part_of_the_template_version(
    product: Product, settings: LazySettings
) -> None:
    report = get_report("product-sheet")
    a4 = report.get_template_version()
    settings.KARNI_REPORTS_PAGE_SIZE = "letter"
    assert report.get_template_version() != a4
    html = report.render_html(product, report.get_context(product))
    assert "size: letter;" in html


def test_the_template_version_follows_extends_and_includes() -> None:
    names = [name for name, _source in versions.template_sources("products/product_sheet.html")]
    assert names == ["products/product_sheet.html", "karni_reports/base.html"]


def test_the_data_version_is_stable_and_reads_plain_data(product: Product) -> None:
    context = {"product": product, "tags": {"b", "a"}, "rows": Product.objects.all()}
    assert versions.data_version(context) == versions.data_version(context)
    encoded = versions.encode({"product": product})
    assert encoded["product"]["$model"] == "testapp.Product"
    assert encoded["product"]["price"] == "49.00"

    class Opaque:
        pass

    with pytest.raises(KarniTypeError) as caught:
        versions.data_version({"thing": Opaque()})
    assert caught.value.code == "REPORT011"


def test_keep_zero_keeps_every_file(product: Product, ready: Ready, settings: LazySettings) -> None:
    settings.KARNI_REPORTS_KEEP = 0
    ready(product)
    product.name = "Desk lamp, brass"
    product.save()
    ready(product)
    assert GeneratedReport.objects.filter(status="ready").count() == 2


def test_keep_two_keeps_the_two_newest(
    product: Product, ready: Ready, settings: LazySettings
) -> None:
    settings.KARNI_REPORTS_KEEP = 2
    for name in ("one", "two", "three"):
        product.name = name
        product.save()
        ready(product)
    kept = GeneratedReport.objects.order_by("created_at")
    assert kept.count() == 2
    assert all(row.file.storage.exists(row.file.name) for row in kept)
