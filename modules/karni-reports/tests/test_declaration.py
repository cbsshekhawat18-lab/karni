"""Declaring a report: the class, the registry, discovery and the checks."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from karni.exceptions import KarniImproperlyConfigured, KarniLookupError

from karni_reports import Report, get_report, register, reports, unregister
from karni_reports.checks import run_checks
from tests.testapp.models import Category, Product


@pytest.fixture
def cleanup() -> Iterator[list[str]]:
    names: list[str] = []
    yield names
    for name in names:
        unregister(name)


def test_the_apps_reports_are_found_at_startup() -> None:
    assert {"category", "product-sheet"} <= set(reports())
    sheet = get_report("product-sheet")
    assert sheet.model is Product and sheet.title == "Product Sheet"
    assert get_report("category").model is Category


def test_an_unknown_report_is_refused_with_the_known_names() -> None:
    with pytest.raises(KarniLookupError, match="category, product-sheet") as caught:
        get_report("nope")
    assert caught.value.code == "REPORT001"


def test_a_report_needs_a_model_and_a_template(cleanup: list[str]) -> None:
    class NoModel(Report):
        template = "x.html"

    class NoTemplate(Report):
        model = Product

    class BadName(Report):
        name = "Bad Name"
        model = Product
        template = "x.html"

    for incomplete in (NoModel, NoTemplate, BadName):
        with pytest.raises(KarniImproperlyConfigured) as caught:
            register(incomplete)
        assert caught.value.code == "REPORT002"


def test_two_reports_cannot_share_a_name(cleanup: list[str]) -> None:
    class Twin(Report):
        name = "product-sheet"
        model = Product
        template = "products/product_sheet.html"

    with pytest.raises(KarniImproperlyConfigured) as caught:
        register(Twin)
    assert caught.value.code == "REPORT003"
    assert get_report("product-sheet").__class__.__name__ == "ProductSheet"


def test_registering_returns_the_class_with_its_derived_name(cleanup: list[str]) -> None:
    @register
    class PriceList(Report):
        model = Category
        template = "products/category_sheet.html"

    cleanup.append("price-list")
    assert PriceList.name == "price-list" and get_report("price-list").title == "Price List"


def test_karni_check_names_a_report_without_viewset_or_template(cleanup: list[str]) -> None:
    assert run_checks() == []

    @register
    class ContentTypes(Report):
        model = ContentType
        template = "missing/content_types.html"

    cleanup.append("content-types")
    failures = run_checks()
    assert [failure.split(":")[0] for failure in failures] == ["REPORT004", "REPORT010"]
    assert "no viewset serves contenttypes.ContentType" in failures[0]
    assert "missing/content_types.html" in failures[1]


def test_get_viewset_takes_a_class_or_a_dotted_path(cleanup: list[str]) -> None:
    from tests.testapp.viewsets import ProductViewSet

    class ByPath(Report):
        model = Product
        template = "products/product_sheet.html"
        viewset = "tests.testapp.viewsets.ProductViewSet"

    assert ByPath().get_viewset() is ProductViewSet
    assert get_report("product-sheet").get_viewset() is ProductViewSet


def test_the_default_context_and_file_name(product: Any) -> None:
    class Plain(Report):
        name = "plain"
        model = Product
        template = "products/category_sheet.html"

    plain = Plain()
    assert plain.get_context(product) == {"object": product}
    assert plain.get_filename(product) == f"plain-{product.pk}.pdf"
