"""``POST /api/ai/extract/`` end to end with the test provider: text, URL and PDF into a preview."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import override_settings
from karni.api.throttling import ActionRateThrottle
from karni.transfer.models import ImportJob
from rest_framework.test import APIClient

from karni_ai.exceptions import ProviderError
from karni_ai.models import AICall
from karni_ai.providers.base import Usage
from karni_ai.providers.test import TestProvider
from karni_ai.services.fetch import Fetched, Fetcher
from tests.conftest import PRODUCTS
from tests.pdfs import make_pdf
from tests.testapp.models import Product

URL = "/api/ai/extract/"

pytestmark = pytest.mark.usefixtures("catalog")


def extract(client: APIClient, **body: Any) -> Any:
    body.setdefault("resource", "products")
    if "file" in body:
        return client.post(URL, body, format="multipart")
    return client.post(URL, body, format="json")


# the happy path


def test_text_becomes_a_preview_and_nothing_is_written(editor_client: APIClient) -> None:
    response = extract(editor_client, text=PRODUCTS)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "previewed" and body["resource"] == "products"
    assert body["rows"] == [
        {
            "name": "Garden hose",
            "sku": "GH-100",
            "price": "19.90",
            "stock": 12,
            "status": "active",
            "category": "Garden",
            "tags": ["outdoor", "water"],
        },
        {"name": "Rake", "sku": "RK-200", "price": "24.50", "category": "Garden"},
    ]
    assert body["problems"] == []
    assert body["result"]["created"] == 2 and body["result"]["errors"] == 0
    assert body["commit"] == f"/api/products/import/{body['id']}/commit/"
    assert body["job"]["id"] == body["id"] and body["job"]["file_name"] == "Extracted from text"
    assert body["source"] == {"kind": "text", "label": "text"}
    # The preview rolled everything back: no product exists until the commit.
    assert Product.objects.count() == 0
    job = ImportJob.objects.get(pk=body["id"])
    assert job.status == ImportJob.Status.PREVIEWED and job.created_by_id is not None


def test_the_import_commit_saves_the_previewed_rows(editor_client: APIClient) -> None:
    body = extract(editor_client, text=PRODUCTS).json()
    assert Product.objects.count() == 0
    committed = editor_client.post(body["commit"], {}, format="json")
    assert committed.status_code == 200 and committed.json()["status"] == "done"
    hose = Product.objects.get(sku="GH-100")
    assert hose.price == Decimal("19.90") and hose.category is not None
    assert sorted(tag.name for tag in hose.tags.all()) == ["outdoor", "water"]
    assert Product.objects.count() == 2


def test_another_user_cannot_commit_the_preview(editor_client: APIClient, client_for: Any) -> None:
    from tests.conftest import make_user

    body = extract(editor_client, text=PRODUCTS).json()
    other = client_for(make_user("second@example.com", "editor"))
    assert other.post(body["commit"], {}, format="json").status_code == 404
    assert Product.objects.count() == 0


def test_a_known_key_updates_the_existing_row(editor_client: APIClient) -> None:
    from tests.testapp.models import Category

    Product.objects.create(
        name="Old hose", sku="GH-100", price=Decimal("9.00"), category=Category.objects.get()
    )
    body = extract(editor_client, text="SKU: GH-100\nPrice: 21.00").json()
    assert body["result"]["updated"] == 1 and body["result"]["created"] == 0
    assert Product.objects.get().price == Decimal("9.00")


def test_a_url_is_fetched_and_read(editor_client: APIClient, monkeypatch: Any) -> None:
    page = b"<html><head><title>x</title><script>var a = 'Name: Hidden';</script></head><body>"
    page += b"<p>Name: Watering can</p><p>SKU: WC-1</p><p>Price: 7.25</p></body></html>"
    fetched: list[str] = []

    def fake_fetch(self: Fetcher, url: str) -> Fetched:
        fetched.append(url)
        return Fetched(url=url, content_type="text/html", charset="utf-8", body=page)

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    response = extract(editor_client, url="https://shop.example.com/can")
    assert response.status_code == 201, response.content
    body = response.json()
    assert fetched == ["https://shop.example.com/can"]
    assert body["rows"] == [{"name": "Watering can", "sku": "WC-1", "price": "7.25"}]
    assert body["source"] == {"kind": "url", "label": "https://shop.example.com/can"}
    assert "Hidden" not in TestProvider.calls[0].source
    assert AICall.objects.get().source == "url"


def test_a_pdf_is_read(editor_client: APIClient) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    pdf = make_pdf(["Name: Seed tray", "SKU: ST-9", "Price: 3.10"])
    upload = SimpleUploadedFile("trays.pdf", pdf, content_type="application/pdf")
    response = extract(editor_client, file=upload)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["rows"] == [{"name": "Seed tray", "sku": "ST-9", "price": "3.10"}]
    assert body["source"] == {"kind": "pdf", "label": "trays.pdf"}
    assert body["job"]["file_name"] == "Extracted from trays.pdf"


# problems


def test_schema_and_preview_problems_are_reported_per_field(editor_client: APIClient) -> None:
    TestProvider.answer_with(
        {
            "rows": [
                {"name": "Hose", "sku": "H-1", "price": "abc", "colour": "green"},
                {"name": "Rake", "sku": "R-1", "price": "5.00", "category": "Kitchen"},
                {"name": "Hoe", "sku": "O-1", "price": "6.00", "status": "Active"},
                "not a record",
                {"name": None, "sku": "S-1", "price": "2.00"},
            ]
        }
    )
    body = extract(editor_client, text="anything").json()
    problems = {(p["row"], p["field"], p["source"]) for p in body["problems"]}
    assert (1, "price", "schema") in problems
    assert (1, "colour", "schema") in problems
    assert (2, "category", "preview") in problems
    assert (3, "status", "schema") in problems
    assert (4, "", "schema") in problems
    # A missing required field is the preview's to report, for a new row only.
    assert (5, "name", "preview") in problems
    assert (1, "price", "preview") in problems  # left out by the schema, so missing
    assert body["rows"][0] == {"name": "Hose", "sku": "H-1"}
    assert body["rows"][3] == {}
    assert body["result"]["rows_total"] == 4  # the empty record is not a row of the file
    messages = {p["field"]: p["message"] for p in body["problems"] if p["row"] == 3}
    assert "not one of the choices" in messages["status"]


def test_rows_past_the_limit_are_left_out(editor_client: APIClient) -> None:
    rows = [{"name": f"P{n}", "sku": f"P-{n}", "price": "1.00"} for n in range(5)]
    TestProvider.answer_with({"rows": rows})
    with override_settings(KARNI_AI_MAX_ROWS=3):
        body = extract(editor_client, text="anything").json()
    assert len(body["rows"]) == 3 and body["result"]["rows_total"] == 3
    assert body["problems"][-1]["row"] == 4 and "2 more rows" in body["problems"][-1]["message"]


def test_an_answer_of_the_wrong_shape_is_ai007_and_logged(editor_client: APIClient) -> None:
    TestProvider.answer_with(["not", "rows"])
    response = extract(editor_client, text="anything")
    assert response.status_code == 502 and response.json()["code"] == "AI007"
    call = AICall.objects.get()
    assert call.status == AICall.Status.FAILED and call.error_code == "AI007"
    assert call.input_tokens > 0 and ImportJob.objects.count() == 0


def test_a_failed_provider_call_is_logged_with_its_tokens(editor_client: APIClient) -> None:
    TestProvider.fail_with(ProviderError("declined", code="AI007", usage=Usage(40, 3)))
    response = extract(editor_client, text="anything")
    assert response.status_code == 502
    assert response.json() == {"code": "AI007", "detail": "declined"}
    call = AICall.objects.get()
    assert (call.input_tokens, call.output_tokens, call.error_code) == (40, 3, "AI007")
    assert call.cost == Decimal("0.000104")


def test_no_rows_is_an_empty_preview(editor_client: APIClient) -> None:
    body = extract(editor_client, text="Nothing to see here.").json()
    assert body["rows"] == [] and body["result"]["rows_total"] == 0


# the source


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({}, "exactly one source"),
        ({"text": "Name: A", "url": "https://example.com/"}, "got text, url"),
        ({"text": "   "}, "no text"),
    ],
)
def test_one_source_is_required(
    editor_client: APIClient, body: dict[str, str], fragment: str
) -> None:
    response = extract(editor_client, **body)
    assert response.status_code == 400
    assert response.json()["code"] == "AI010" and fragment in response.json()["detail"]
    assert AICall.objects.count() == 0


def test_a_text_over_the_limit_is_refused_not_cut(editor_client: APIClient) -> None:
    with override_settings(KARNI_AI_MAX_SOURCE_CHARS=10):
        response = extract(editor_client, text="Name: a long product name")
    assert response.status_code == 400 and response.json()["code"] == "AI010"
    assert TestProvider.calls == []


def test_a_refused_url_never_reaches_the_provider(editor_client: APIClient) -> None:
    response = extract(editor_client, url="http://127.0.0.1/admin/")
    assert response.status_code == 400 and response.json()["code"] == "AI011"
    assert TestProvider.calls == [] and AICall.objects.count() == 0


# the resource and the user's right to it


def test_anonymous_callers_are_refused(client_for: Any) -> None:
    response = extract(client_for(None), text=PRODUCTS)
    assert response.status_code in (401, 403)
    assert TestProvider.calls == []


def test_a_user_who_may_not_create_is_refused(reader: Any, client_for: Any) -> None:
    response = extract(client_for(reader), text=PRODUCTS)
    assert response.status_code == 403 and response.json()["code"] == "AI009"
    assert TestProvider.calls == [] and AICall.objects.count() == 0


def test_any_resource_the_user_may_create_works(reader: Any, client_for: Any) -> None:
    response = extract(client_for(reader), resource="categories", text="Name: Kitchen")
    assert response.status_code == 201, response.content
    assert response.json()["rows"] == [{"name": "Kitchen"}]


@pytest.mark.parametrize(
    ("resource", "fragment"),
    [("product", "No resource is routed"), ("regions", "import turned off")],
)
def test_a_resource_that_cannot_be_extracted_into(
    editor_client: APIClient, resource: str, fragment: str
) -> None:
    response = extract(editor_client, resource=resource, text=PRODUCTS)
    assert response.status_code == 400
    assert response.json()["code"] == "AI008" and fragment in response.json()["detail"]


# the provider's settings


@pytest.mark.parametrize(
    ("settings", "code"),
    [
        ({"KARNI_AI_PROVIDER": ""}, "AI001"),
        ({"KARNI_AI_PROVIDER": "no.such.Provider"}, "AI002"),
        (
            {"KARNI_AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": "m"},
            "AI004",
        ),
        ({"KARNI_AI_PROVIDER": "openai", "OPENAI_API_KEY": "k", "OPENAI_MODEL": ""}, "AI005"),
    ],
)
def test_a_provider_that_is_not_set_up_is_503(
    editor_client: APIClient, settings: dict[str, str], code: str
) -> None:
    with override_settings(**settings):
        response = extract(editor_client, text=PRODUCTS)
    assert response.status_code == 503 and response.json()["code"] == code


# usage, cost, limits and budgets


def test_every_call_is_logged_with_tokens_and_cost(editor: Any, editor_client: APIClient) -> None:
    body = extract(editor_client, text=PRODUCTS).json()
    call = AICall.objects.get()
    assert (call.user, call.provider, call.model, call.resource) == (
        editor,
        "test",
        "test",
        "products",
    )
    assert call.status == AICall.Status.OK and str(call.import_job_id) == body["id"]
    assert call.input_tokens > 0 and call.output_tokens > 0
    expected = (Decimal(call.input_tokens) * 2 + Decimal(call.output_tokens) * 8) / 1_000_000
    assert call.cost == expected.quantize(Decimal("0.000001"))
    assert body["usage"] == {
        "provider": "test",
        "model": "test",
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cost": str(call.cost),
    }


def test_a_model_without_a_price_logs_no_cost(editor_client: APIClient) -> None:
    with override_settings(KARNI_AI_PRICES={}):
        body = extract(editor_client, text=PRODUCTS).json()
    assert body["usage"]["cost"] is None and AICall.objects.get().cost is None


def test_the_rate_limit_is_per_user(
    editor_client: APIClient, reader: Any, client_for: Any, monkeypatch: Any
) -> None:
    monkeypatch.setitem(ActionRateThrottle.THROTTLE_RATES, "ai.extract", "2/min")
    assert extract(editor_client, text=PRODUCTS).status_code == 201
    assert extract(editor_client, text=PRODUCTS).status_code == 201
    third = extract(editor_client, text=PRODUCTS)
    assert third.status_code == 429 and "Retry-After" in third.headers
    # Another user has a history of their own.
    response = extract(client_for(reader), resource="categories", text="Name: Tools")
    assert response.status_code == 201


def test_the_monthly_budget_per_user(
    editor: Any, editor_client: APIClient, client_for: Any
) -> None:
    from tests.conftest import make_user

    AICall.objects.create(
        user=editor,
        provider="test",
        model="test",
        resource="products",
        source="text",
        input_tokens=900,
        output_tokens=100,
    )
    with override_settings(KARNI_AI_MONTHLY_TOKENS_PER_USER=1000):
        refused = extract(editor_client, text=PRODUCTS)
        other = extract(client_for(make_user("other@example.com", "editor")), text=PRODUCTS)
    assert refused.status_code == 429 and refused.json()["code"] == "AI013"
    assert other.status_code == 201
    assert len(TestProvider.calls) == 1


def test_last_months_tokens_do_not_count(editor: Any, editor_client: APIClient) -> None:
    from datetime import timedelta

    from karni_ai.usage import month_start

    old = AICall.objects.create(
        user=editor,
        provider="test",
        model="test",
        resource="products",
        source="text",
        input_tokens=5000,
        output_tokens=0,
    )
    AICall.objects.filter(pk=old.pk).update(created_at=month_start() - timedelta(seconds=1))
    with override_settings(KARNI_AI_MONTHLY_TOKENS_PER_USER=1000):
        assert extract(editor_client, text=PRODUCTS).status_code == 201


def test_the_project_monthly_budget(editor_client: APIClient, reader: Any) -> None:
    AICall.objects.create(
        user=reader,
        provider="test",
        model="test",
        resource="products",
        source="text",
        input_tokens=50,
        output_tokens=50,
    )
    with override_settings(KARNI_AI_MONTHLY_TOKENS=100):
        refused = extract(editor_client, text=PRODUCTS)
    assert refused.status_code == 429 and refused.json()["code"] == "AI014"
    assert TestProvider.calls == []


# the usage log through the API


def test_each_user_lists_their_own_calls(editor: Any, reader: Any, client_for: Any) -> None:
    extract(client_for(editor), text=PRODUCTS)
    extract(client_for(reader), resource="categories", text="Name: Tools")
    mine = client_for(reader).get("/api/ai/").json()
    rows = mine["results"] if isinstance(mine, dict) else mine
    assert [row["resource"] for row in rows] == ["categories"]


def test_the_usage_log_is_read_only(editor: Any, client_for: Any) -> None:
    extract(client_for(editor), text=PRODUCTS)
    call = AICall.objects.get()
    client = client_for(editor)
    assert client.post("/api/ai/", {}, format="json").status_code == 405
    assert (
        client.patch(f"/api/ai/{call.pk}/", {"input_tokens": 1}, format="json").status_code == 405
    )
    assert client.delete(f"/api/ai/{call.pk}/").status_code == 405
