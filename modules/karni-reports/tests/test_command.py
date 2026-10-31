"""``manage.py karni_pregenerate``: all rows, given ids, stale ones, in batches, with counts."""

from __future__ import annotations

from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from karni.exceptions import KarniCommandError

from karni_reports.models import GeneratedReport
from karni_reports.rendering import FakeRenderer
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db


@pytest.fixture
def products(owner: Any) -> list[Product]:
    return [
        Product.objects.create(owner=owner, name=f"Lamp {n}", price=Decimal("10.00"))
        for n in range(5)
    ]


def _run(*args: str) -> list[str]:
    out = StringIO()
    call_command("karni_pregenerate", *args, stdout=out)
    return out.getvalue().splitlines()


def test_every_row_in_batches_then_cached(products: list[Product]) -> None:
    lines = _run("product-sheet", "--batch-size", "2")
    assert [line.split(" in ")[0] for line in lines] == [
        "batch 1: 2 rows, 2 rendered, 0 cached, 0 failed",
        "batch 2: 2 rows, 2 rendered, 0 cached, 0 failed",
        "batch 3: 1 rows, 1 rendered, 0 cached, 0 failed",
        "product-sheet: 5 rows, 5 rendered, 0 cached, 0 failed",
    ]
    assert lines[-1].endswith("s") and GeneratedReport.objects.filter(status="ready").count() == 5
    again = _run("product-sheet")
    assert again[-1].startswith("product-sheet: 5 rows, 0 rendered, 5 cached, 0 failed in ")
    assert len(FakeRenderer.rendered) == 5


def test_given_ids_only(products: list[Product]) -> None:
    ids = [str(products[0].pk), str(products[3].pk)]
    lines = _run("product-sheet", "--ids", *ids)
    assert lines[-1].startswith("product-sheet: 2 rows, 2 rendered")
    assert sorted(GeneratedReport.objects.values_list("object_id", flat=True)) == sorted(ids)


def test_stale_renders_only_the_rows_that_changed_since(products: list[Product]) -> None:
    _run("product-sheet", "--ids", str(products[0].pk), str(products[1].pk))
    products[0].price = Decimal("11.00")
    products[0].save()
    lines = _run("product-sheet", "--stale")
    assert lines[-1].startswith("product-sheet: 2 rows, 1 rendered, 1 cached, 0 failed")
    assert "11.00" in FakeRenderer.rendered[-1]
    rows = GeneratedReport.objects.filter(object_id=str(products[0].pk))
    assert rows.count() == 1 and rows.get().is_ready  # the old file was pruned


def test_force_renders_current_files_again(products: list[Product]) -> None:
    _run("product-sheet", "--ids", str(products[0].pk))
    first = GeneratedReport.objects.get()
    old_name = first.file.name
    lines = _run("product-sheet", "--ids", str(products[0].pk), "--force")
    assert lines[-1].startswith("product-sheet: 1 rows, 1 rendered, 0 cached")
    again = GeneratedReport.objects.get()
    assert again.pk == first.pk and again.file.name != old_name
    assert not again.file.storage.exists(old_name)


def test_failures_are_counted_not_raised(
    products: list[Product], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: Any, html: str, **kwargs: Any) -> bytes:
        raise ValueError("no fonts")

    monkeypatch.setattr(FakeRenderer, "render", broken)
    lines = _run("product-sheet")
    assert lines[-1].startswith("product-sheet: 5 rows, 0 rendered, 0 cached, 5 failed")
    assert GeneratedReport.objects.filter(status="failed").count() == 5


def test_list_and_unknown_names() -> None:
    assert _run("--list") == [
        "category  testapp.Category  products/category_sheet.html",
        "product-sheet  testapp.Product  products/product_sheet.html",
    ]
    for args in (("nope",), ()):
        with pytest.raises(KarniCommandError) as caught:
            _run(*args)
        assert caught.value.code == "REPORT001"
