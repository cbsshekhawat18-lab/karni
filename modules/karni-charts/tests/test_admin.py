"""Charts in the admin: the source choice, the checks on save and the preview."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory

from karni_charts.admin import ChartAdmin, ChartForm, preview
from karni_charts.models import Chart

pytestmark = pytest.mark.django_db


def _client(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_the_chart_admin_is_registered() -> None:
    assert isinstance(admin.site._registry[Chart], ChartAdmin)


def test_the_form_offers_the_sources_and_the_buckets() -> None:
    form = ChartForm()
    assert [value for value, _ in form.fields["source"].choices] == ["products"]
    assert [value for value, _ in form.fields["x_bucket"].choices] == [
        "",
        "year",
        "quarter",
        "month",
    ]
    kept = ChartForm(instance=Chart(source="gone"))
    assert "gone" in [value for value, _ in kept.fields["source"].choices]


def test_the_change_form_shows_a_preview_of_the_data(
    chart: Chart, catalog: dict[str, Any], staff: Any
) -> None:
    page = _client(staff).get(f"/admin/karni_charts/chart/{chart.pk}/change/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Preview" in html
    assert '<th scope="row">2024</th>' in html
    assert '<th scope="col">Online</th>' in html


def test_the_add_form_saves_a_valid_chart_and_refuses_one_that_cannot_run(staff: Any) -> None:
    client = _client(staff)
    assert client.get("/admin/karni_charts/chart/add/").status_code == 200
    data = {
        "name": "By channel",
        "slug": "by-channel",
        "description": "",
        "kind": "bar",
        "position": "0",
        "source": "products",
        "x_field": "channel",
        "x_bucket": "",
        "x_label": "",
        "y_metric": "count",
        "y_value": "",
        "y_label": "",
        "z_field": "",
        "z_bucket": "",
        "z_mode": "stack",
        "top": "",
        "default_filters": "{}",
        "allowed_filters": "[]",
    }
    saved = client.post("/admin/karni_charts/chart/add/", data)
    assert saved.status_code == 302, saved.content.decode()[:2000]
    assert Chart.objects.filter(slug="by-channel").exists()
    refused = client.post(
        "/admin/karni_charts/chart/add/", {**data, "slug": "x", "x_field": "name"}
    )
    assert refused.status_code == 200
    assert "CHART004" in refused.content.decode()


def test_the_preview_shows_what_the_signed_in_user_may_see(
    chart: Chart, catalog: dict[str, Any], owner: Any, staff: Any
) -> None:
    request = RequestFactory().get("/")
    request.user = owner
    mine = preview(chart, request)
    assert mine["series"] == ["Online"]
    assert [row["label"] for row in mine["rows"]] == ["2024", "2025"]
    request.user = staff
    assert preview(chart, request)["series"] == ["Online", "Store"]
    broken = Chart(name="Broken", slug="broken", source="products", x_field="name")
    assert "E382" in preview(broken, request)["error"]
    gone = Chart(name="Gone", slug="gone", source="notes", x_field="text")
    assert preview(gone, request)["error"].startswith("CHART001")
