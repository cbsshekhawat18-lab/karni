"""The CRM rules: sales see their own deals, managers all, contacts import by email."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from crm.models import Contact, Deal
from django.core.files.uploadedfile import SimpleUploadedFile
from karni.testing.factories import create

pytestmark = pytest.mark.django_db


def test_the_pipeline_counts_the_deals_each_role_may_see(client_as: Any) -> None:
    sales = client_as("sales")
    create(Deal, salesperson=sales.user, value=Decimal("100.00"))
    create(Deal, salesperson=sales.user, value=Decimal("50.00"))
    create(Deal, value=Decimal("900.00"))  # another salesperson's
    mine = sales.get("/api/deals/pipeline/")
    assert mine.status_code == 200, mine.content
    assert mine.json() == [{"stage": "lead", "deals": 2, "value": "150.00"}]
    every = client_as("manager").get("/api/deals/pipeline/").json()
    assert every == [{"stage": "lead", "deals": 3, "value": "1050.00"}]


def test_an_import_updates_contacts_by_their_email(
    client_as: Any, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(
        tmp_path
    )  # the uploaded file is kept until the import is done
    client = client_as("sales")
    create(Contact, email="ada@example.com", first_name="Ada", last_name="Old")
    rows = (
        "first_name,last_name,email\n"
        "Ada,Lovelace,ada@example.com\n"
        "Alan,Turing,alan@example.com\n"
    )
    upload = SimpleUploadedFile("contacts.csv", rows.encode(), content_type="text/csv")
    job = client.post(
        "/api/contacts/import/", {"file": upload}, format="multipart"
    ).json()
    preview = client.post(
        f"/api/contacts/import/{job['id']}/preview/",
        {"mapping": job["mapping"]},
        format="json",
    )
    assert (
        preview.json()["result"]["updated"] == 1
        and preview.json()["result"]["created"] == 1
    )
    committed = client.post(
        f"/api/contacts/import/{job['id']}/commit/", {}, format="json"
    )
    assert committed.json()["status"] == "done", committed.content
    assert Contact.objects.get(email="ada@example.com").last_name == "Lovelace"
    exported = client.get("/api/contacts/export/?format=csv")
    assert exported.status_code == 200 and b"alan@example.com" in b"".join(exported)
