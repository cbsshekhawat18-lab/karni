"""The endpoints: request, status and download, each checked through the row's own viewset."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from karni.api.throttling import ActionRateThrottle

from karni_reports.models import GeneratedReport
from karni_reports.rendering import FakeRenderer
from tests.testapp.models import Category, Product

pytestmark = pytest.mark.django_db

REFUSED = (401, 403)


def _paths(product: Any, report: str = "product-sheet") -> tuple[str, str, str]:
    base = f"/api/reports/{report}/{product.pk}/"
    return base, f"{base}status/", f"{base}download/"


def test_the_owner_requests_follows_and_downloads(
    client_for: Any, owner: Any, product: Product, django_capture_on_commit_callbacks: Any
) -> None:
    client = client_for(owner)
    request, status, download = _paths(product)
    before = client.get(status)
    assert before.status_code == 200 and before.json()["status"] == "none"
    with django_capture_on_commit_callbacks(execute=True):
        queued = client.post(request)
    assert queued.status_code == 202, queued.content
    assert queued.json()["status"] == "pending" and queued.json()["url"] is None
    followed = client.get(status).json()
    assert followed["status"] == "ready" and followed["url"] == download
    assert followed["object_id"] == str(product.pk) and followed["size"] > 0
    cached = client.post(request)
    assert cached.status_code == 200 and cached.json()["url"] == download
    assert len(FakeRenderer.rendered) == 1
    file = client.get(download)
    assert file.status_code == 200 and file["Content-Type"] == "application/pdf"
    assert f'filename="product-sheet-{product.pk}.pdf"' in file["Content-Disposition"]
    assert b"".join(file.streaming_content).startswith(b"%PDF")


@pytest.mark.parametrize("path", [0, 1, 2], ids=["request", "status", "download"])
def test_another_users_row_is_a_404(
    client_for: Any, other: Any, product: Product, path: int
) -> None:
    url = _paths(product)[path]
    client = client_for(other)
    response = client.post(url) if path == 0 else client.get(url)
    assert response.status_code == 404
    assert not GeneratedReport.objects.exists()


@pytest.mark.parametrize("path", [0, 1, 2], ids=["request", "status", "download"])
def test_anonymous_gets_what_the_rows_retrieve_answers(
    client_for: Any, product: Product, path: int
) -> None:
    url = _paths(product)[path]
    client = client_for()
    response = client.post(url) if path == 0 else client.get(url)
    assert response.status_code in REFUSED
    assert client.get(f"/api/products/{product.pk}/").status_code == response.status_code


def test_the_download_checks_the_row_again(
    client_for: Any,
    owner: Any,
    other: Any,
    product: Product,
    django_capture_on_commit_callbacks: Any,
) -> None:
    request, _status, download = _paths(product)
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for(owner).post(request).status_code == 202
    assert client_for(owner).get(download).status_code == 200
    assert client_for(other).get(download).status_code == 404
    assert client_for().get(download).status_code in REFUSED
    product.owner = other
    product.save()  # the row changes hands: the old owner's link opens nothing
    assert client_for(owner).get(download).status_code == 404


def test_a_role_that_reads_every_row_gets_any_report(
    client_for: Any, staff: Any, product: Product, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for(staff).post(_paths(product)[0]).status_code == 202
    assert client_for(staff).get(_paths(product)[2]).status_code == 200


def test_a_public_row_is_open_to_anonymous_callers(
    client_for: Any, category: Category, django_capture_on_commit_callbacks: Any
) -> None:
    request, status, download = _paths(category, "category")
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for().post(request).status_code == 202
    assert client_for().get(status).json()["status"] == "ready"
    assert client_for().get(download).status_code == 200


def test_unknown_reports_rows_and_files_are_404(
    client_for: Any, owner: Any, product: Product
) -> None:
    client = client_for(owner)
    assert client.post(f"/api/reports/nope/{product.pk}/").status_code == 404
    missing = "999999" if isinstance(product.pk, int) else "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/reports/product-sheet/{missing}/").status_code == 404
    early = client.get(_paths(product)[2])
    assert early.status_code == 404 and "REPORT008" in early.json()["detail"]


def test_the_generated_rows_list_follows_the_grants(
    client_for: Any,
    owner: Any,
    staff: Any,
    product: Product,
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        client_for(owner).post(_paths(product)[0])
    assert client_for(owner).get("/api/reports/").status_code == 403
    listed = client_for(staff).get("/api/reports/")
    assert listed.status_code == 200 and listed.json()["count"] == 1
    assert client_for(staff).post("/api/reports/", {}).status_code == 405


def test_a_failed_render_says_failed_without_the_error(
    client_for: Any,
    owner: Any,
    product: Product,
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: Any, html: str, **kwargs: Any) -> bytes:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(FakeRenderer, "render", broken)
    client = client_for(owner)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(_paths(product)[0])
    answer = client.get(_paths(product)[1]).json()
    assert answer["status"] == "failed" and "REPORT007" in answer["error"]
    assert "secret" not in answer["error"]
    assert "secret detail" in GeneratedReport.objects.get().error
    monkeypatch.undo()
    with django_capture_on_commit_callbacks(execute=True):
        again = client.post(_paths(product)[0])  # a failed render is queued again
    assert again.status_code == 202
    assert client.get(_paths(product)[1]).json()["status"] == "ready"


def test_requests_are_throttled_per_caller(
    client_for: Any, owner: Any, product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache.clear()
    monkeypatch.setattr(ActionRateThrottle, "THROTTLE_RATES", {"reports.request_report": "2/min"})
    client = client_for(owner)
    codes = [client.post(_paths(product)[0]).status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429
    assert client.get(_paths(product)[1]).status_code == 200  # another scope
    cache.clear()


def test_the_module_indexes_what_its_viewsets_filter_by() -> None:
    """karni.W967 on the module's own models would point a project at a model it cannot edit."""
    from karni.fields.checks import check_usage_indexes

    assert [
        message.msg
        for message in check_usage_indexes()
        if message.obj._meta.app_label == "karni_reports"
    ] == []
