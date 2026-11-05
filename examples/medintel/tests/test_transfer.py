"""Import and export: a list exports under the user's grants, and the file imports back."""

import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from intel.models import Company, Trial

pytestmark = pytest.mark.django_db


def export(client, resource: str, **params) -> list[dict[str, str]]:
    response = client.get(f"/api/{resource}/export/", {"format": "csv", **params})
    assert response.status_code == 200
    body = b"".join(response.streaming_content).decode()
    return list(csv.DictReader(io.StringIO(body)))


def run_import(client, resource: str, rows: list[dict[str, str]]) -> dict:
    """Upload, preview, then commit a CSV: the preview is the dry run the commit must repeat."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    upload = client.post(
        f"/api/{resource}/import/",
        {"file": SimpleUploadedFile("rows.csv", out.getvalue().encode(), content_type="text/csv")},
        format="multipart",
    )
    assert upload.status_code in (200, 201), upload.content
    job = upload.json()
    base = f"/api/{resource}/import/{job['id']}"
    mapping = job.get("mapping") or job["suggested_mapping"]
    preview = client.post(f"{base}/preview/", {"mapping": mapping}, format="json")
    assert preview.status_code == 200, preview.content
    committed = client.post(f"{base}/commit/", {}, format="json")
    assert committed.status_code == 200, committed.content
    return {"preview": preview.json()["result"], "commit": committed.json()["result"], "problems": committed.json()["problems"]}


def test_a_customers_export_holds_only_their_rows(client_for):
    rows = export(client_for("oncology@example.com"), "trials")
    assert 0 < len(rows) < Trial.objects.count()
    assert export(client_for("demo@example.com"), "trials", page_size=1)  # staff: every row


def test_an_export_names_relations_and_tags_by_their_keys(client_for):
    row = export(client_for("demo@example.com"), "trials", search="MT-0001")[0]
    trial = Trial.objects.get(code="MT-0001")
    assert row["sponsor"] == trial.sponsor.name
    assert set(row["conditions"].split("|")) == {c.code for c in trial.conditions.all()}
    assert set(row["interventions"].split("|")) == {i.code for i in trial.interventions.all()}


def test_an_export_imports_back_unchanged(client_for):
    client = client_for("demo@example.com")
    rows = export(client, "trials")
    assert len(rows) == 300
    result = run_import(client, "trials", rows)
    assert result["commit"]["created"] == 0 and result["commit"]["updated"] == 0
    assert result["commit"]["unchanged"] == 300 and result["commit"]["errors"] == 0


def test_a_changed_row_updates_and_a_new_row_creates(client_for):
    client = client_for("demo@example.com")
    rows = export(client, "trials")
    rows[0]["title"] = "Retitled by import"
    rows[0]["conditions"] = rows[1]["conditions"]
    new = dict(rows[2], code="MT-9001", title="A trial made by import", id="")
    result = run_import(client, "trials", [rows[0], new])
    assert result["preview"]["updated"] == 1 and result["preview"]["created"] == 1
    assert result["commit"]["updated"] == 1 and result["commit"]["created"] == 1
    changed = Trial.objects.get(code=rows[0]["code"])
    assert changed.title == "Retitled by import"
    assert {c.code for c in changed.conditions.all()} == set(rows[1]["conditions"].split("|"))
    made = Trial.objects.get(code="MT-9001")
    assert made.sponsor.name == new["sponsor"] and made.interventions.count() == len(new["interventions"].split("|"))


def test_a_row_naming_an_unknown_tag_is_reported_not_imported(client_for):
    client = client_for("demo@example.com")
    row = dict(export(client, "trials", search="MT-0002")[0], conditions="C99.9", code="MT-9002", id="")
    result = run_import(client, "trials", [row])
    assert result["commit"]["created"] == 0 and result["commit"]["errors"] == 1 and result["problems"]
    assert not Trial.objects.filter(code="MT-9002").exists()


def test_a_customer_cannot_import(client_for):
    row = export(client_for("demo@example.com"), "companies", search="Alder")[0]
    response = client_for("vaccines@example.com").post(
        "/api/companies/import/",
        {"file": SimpleUploadedFile("rows.csv", f"name\n{row['name']}\n".encode(), content_type="text/csv")},
        format="multipart",
    )
    assert response.status_code == 403
    assert Company.objects.filter(name=row["name"]).count() == 1
