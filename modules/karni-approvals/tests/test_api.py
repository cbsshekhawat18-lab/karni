"""Through the API: a guarded PATCH answers 202, and deciding follows every rule."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from karni.accounts.permissions import assign_role
from rest_framework.test import APIClient

from karni_approvals.models import PendingChange
from tests.conftest import make_user
from tests.testapp.models import Contract, Invoice

pytestmark = pytest.mark.django_db


def client_for(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_a_guarded_patch_answers_202_with_the_pending_change(maker: Any, invoice: Invoice) -> None:
    response = client_for(maker).patch(
        f"/api/invoices/{invoice.pk}/", {"amount": "25.00"}, format="json"
    )
    assert response.status_code == 202, response.content
    body = response.json()
    assert body["status"] == "pending" and body["model"] == "testapp.invoice"
    assert (
        body["changes"] == {"amount": ["10.00", "25.00"]}
        and body["maker"]["email"] == "maker@example.com"
    )
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("10.00")
    plain = client_for(maker).patch(f"/api/invoices/{invoice.pk}/", {"note": "ok"}, format="json")
    assert plain.status_code == 200


def test_a_guarded_create_and_delete_answer_202(maker: Any) -> None:
    created = client_for(maker).post(
        "/api/contracts/", {"title": "Lease", "value": "9.00"}, format="json"
    )
    assert created.status_code == 202 and created.json()["action"] == "create"
    assert not Contract.objects.exists()
    contract = Contract.objects.create(title="Old")
    deleted = client_for(maker).delete(f"/api/contracts/{contract.pk}/")
    assert deleted.status_code == 202 and deleted.json()["action"] == "delete"
    assert Contract.objects.filter(pk=contract.pk).exists()


def test_the_queue_is_scoped_and_decisions_follow_the_rules(
    maker: Any, checker: Any, invoice: Invoice
) -> None:
    held = (
        client_for(maker)
        .patch(f"/api/invoices/{invoice.pk}/", {"status": "paid"}, format="json")
        .json()
    )
    pk = held["id"]
    # The checker lists it; the maker sees their own (own-scoped grant); a stranger sees nothing.
    assert [
        row["id"] for row in client_for(checker).get("/api/pending-changes/").json()["results"]
    ] == [pk]
    assert [
        row["id"] for row in client_for(maker).get("/api/pending-changes/").json()["results"]
    ] == [pk]
    stranger = make_user("stranger@example.com")
    assert client_for(stranger).get("/api/pending-changes/").status_code == 403
    assert client_for(checker).get("/api/pending-changes/count/").json() == {"pending": 1}
    assert client_for(maker).get("/api/pending-changes/count/").json() == {"pending": 0}
    # The maker cannot approve their own change — not even as a checker of everything else.
    assign_role(maker, "finance")
    delattr(maker, "_karni_grants")
    refused = client_for(maker).post(f"/api/pending-changes/{pk}/approve/", {}, format="json")
    assert refused.status_code == 403 and "APR002" in str(refused.json())
    # The checker can.
    approved = client_for(checker).post(
        f"/api/pending-changes/{pk}/approve/", {"reason": "fine"}, format="json"
    )
    assert approved.status_code == 200, approved.content
    assert (
        approved.json()["status"] == "approved"
        and approved.json()["decisions"][0]["reason"] == "fine"
    )
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    again = client_for(checker).post(f"/api/pending-changes/{pk}/reject/", {}, format="json")
    assert again.status_code == 400 and "APR005" in str(again.json())


def test_the_resource_is_read_only() -> None:
    client = client_for(make_user("staff@example.com", "staff"))  # holds add/change/delete grants
    assert client.post("/api/pending-changes/", {}, format="json").status_code == 405
    pending = PendingChange.objects.create(
        content_type_id=1, object_id="x", action="update", summary="x", changes={}
    )
    assert client.patch(f"/api/pending-changes/{pending.pk}/", {}, format="json").status_code == 405
    assert client.delete(f"/api/pending-changes/{pending.pk}/").status_code == 405
