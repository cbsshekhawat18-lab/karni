"""The admin: the generated files with status, size and versions, failures, Regenerate."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from karni_reports import get_report, services
from karni_reports.models import GeneratedReport
from karni_reports.rendering import FakeRenderer
from tests.conftest import make_user
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db

CHANGELIST = "admin:karni_reports_generatedreport_changelist"


@pytest.fixture
def admin_client() -> Client:
    admin = get_user_model().objects.create_superuser(
        email="admin@example.com", password="s3cret-pass-123"
    )
    client = Client()
    client.force_login(admin)
    return client


@pytest.fixture
def rows(product: Product, django_capture_on_commit_callbacks: Any) -> list[GeneratedReport]:
    with django_capture_on_commit_callbacks(execute=True):
        ready = services.request(get_report("product-sheet"), product)
    failed = GeneratedReport.objects.create(
        report="product-sheet",
        content_type=ready.content_type,
        object_id="gone",
        template="products/product_sheet.html",
        template_version="t",
        data_version="d",
        status="failed",
        error="DoesNotExist: Product matching query does not exist.",
    )
    ready.refresh_from_db()
    return [ready, failed]


def test_the_list_shows_status_size_versions_and_times(
    admin_client: Client, rows: list[GeneratedReport]
) -> None:
    page = admin_client.get(reverse(CHANGELIST))
    assert page.status_code == 200
    text = page.content.decode()
    ready = rows[0]
    for shown in ("product-sheet", "Ready", "Failed", ready.data_version[:12], "bytes"):
        assert shown in text, shown
    assert f"testapp.product {ready.object_id}" in text


def test_failed_renders_are_listed_with_their_error(
    admin_client: Client, rows: list[GeneratedReport]
) -> None:
    page = admin_client.get(reverse(CHANGELIST), {"status__exact": "failed"})
    text = page.content.decode()
    assert "DoesNotExist: Product matching query does not exist." in text
    assert rows[0].data_version[:12] not in text
    detail = admin_client.get(
        reverse("admin:karni_reports_generatedreport_change", args=[rows[1].pk])
    )
    assert detail.status_code == 200 and "matching query does not exist" in detail.content.decode()


def test_regenerate_queues_the_selected_rows_again(
    admin_client: Client, rows: list[GeneratedReport], django_capture_on_commit_callbacks: Any
) -> None:
    ready = rows[0]
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse(CHANGELIST),
            {"action": "regenerate_selected", "_selected_action": [str(ready.pk)]},
            follow=True,
        )
    assert "1 report(s) queued to render again." in response.content.decode()
    ready.refresh_from_db()
    assert ready.status == "ready" and len(FakeRenderer.rendered) == 2


def test_regenerate_needs_the_change_permission(rows: list[GeneratedReport]) -> None:
    from django.contrib.auth.models import Permission

    viewer = make_user("viewer@example.com")
    viewer.is_staff = True
    viewer.save()
    viewer.user_permissions.add(Permission.objects.get(codename="view_generatedreport"))
    client = Client()
    client.force_login(viewer)
    page = client.get(reverse(CHANGELIST))
    assert page.status_code == 200 and "regenerate_selected" not in page.content.decode()
    assert not admin_can_add(client)


def admin_can_add(client: Client) -> bool:
    return client.get(reverse("admin:karni_reports_generatedreport_add")).status_code == 200
