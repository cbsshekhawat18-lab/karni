"""The CRM rules of karni.yaml: what sales and managers may send, or may not."""

from decimal import Decimal
from typing import Any

import pytest
from crm.models import Activity, Company, Contact, Deal
from karni.testing.api import user_with_roles
from karni.testing.factories import create

pytestmark = pytest.mark.django_db


def _code(response: Any, field: str) -> str:
    return str(response.json()[field][0])[:4]


def _deal(company: Company, **extra: Any) -> dict[str, Any]:
    return {"company": str(company.pk), "title": "Pilot", "value": "1000.00", **extra}


def test_a_company_or_contact_with_deals_is_not_deleted(client_as: Any) -> None:
    sales = client_as("sales")
    company = create(Company)
    contact = create(Contact, company=company)
    create(Deal, company=company, contact=contact, salesperson=sales.user)
    refused = sales.delete(f"/api/companies/{company.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
    refused = sales.delete(f"/api/contacts/{contact.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
    assert Company.objects.filter(pk=company.pk).exists()


def test_a_deal_takes_a_contact_of_its_own_company(client_as: Any) -> None:
    sales = client_as("sales")
    company, other = create(Company), create(Company)
    stranger = create(Contact, company=other)
    refused = sales.post(
        "/api/deals/", _deal(company, contact=str(stranger.pk)), format="json"
    )
    assert refused.status_code == 400 and _code(refused, "contact") == "E993"
    colleague = create(Contact, company=company)
    made = sales.post(
        "/api/deals/", _deal(company, contact=str(colleague.pk)), format="json"
    )
    assert made.status_code == 201, made.content


def test_a_deal_value_and_close_date_keep_their_bounds(client_as: Any) -> None:
    sales = client_as("sales")
    company = create(Company)
    negative = sales.post("/api/deals/", _deal(company, value="-50"), format="json")
    assert negative.status_code == 400 and _code(negative, "value") == "E990"
    past = sales.post(
        "/api/deals/", _deal(company, expected_close="2001-01-01"), format="json"
    )
    assert past.status_code == 400 and _code(past, "expected_close") == "E990"


def test_a_new_deal_starts_as_a_lead(client_as: Any) -> None:
    refused = client_as("sales").post(
        "/api/deals/", _deal(create(Company), stage="won"), format="json"
    )
    assert refused.status_code == 400 and _code(refused, "stage") == "E982"


def test_lost_needs_a_reason_and_a_closed_deal_says_when(client_as: Any) -> None:
    sales = client_as("sales")
    deal = sales.post("/api/deals/", _deal(create(Company)), format="json").json()
    url = f"/api/deals/{deal['id']}/"
    refused = sales.patch(url, {"stage": "lost"}, format="json")
    assert refused.status_code == 400 and _code(refused, "lost_reason") == "E996"
    lost = sales.patch(
        url, {"stage": "lost", "lost_reason": "Budget cut"}, format="json"
    )
    assert lost.status_code == 200, lost.content
    assert lost.json()["closed_at"] is not None


def test_a_won_deal_keeps_its_value(client_as: Any) -> None:
    sales = client_as("sales")
    deal = create(Deal, salesperson=sales.user, value=Decimal("500.00"))
    for stage in ("qualified", "proposal", "won"):
        deal.transition("stage", stage)
    assert Deal.objects.get(pk=deal.pk).closed_at is not None
    refused = sales.patch(f"/api/deals/{deal.pk}/", {"value": "1.00"}, format="json")
    assert refused.status_code == 400 and _code(refused, "value") == "E994"


def test_only_a_manager_deletes_or_reassigns_a_deal(client_as: Any) -> None:
    sales = client_as("sales")
    colleague = user_with_roles("sales")
    deal = create(Deal, salesperson=sales.user)
    url = f"/api/deals/{deal.pk}/"
    assert sales.delete(url).status_code == 403
    moved = sales.patch(url, {"salesperson": str(colleague.pk)}, format="json")
    assert moved.status_code == 403 and moved.json()["detail"].startswith("E135: ")
    manager = client_as("manager")
    assert (
        manager.patch(
            url, {"salesperson": str(colleague.pk)}, format="json"
        ).status_code
        == 200
    )
    assert Deal.objects.get(pk=deal.pk).salesperson == colleague
    assert manager.delete(url).status_code == 204


def test_a_deal_with_activities_is_not_deleted(client_as: Any) -> None:
    deal = create(Deal)
    create(Activity, deal=deal, salesperson=deal.salesperson)
    refused = client_as("manager").delete(f"/api/deals/{deal.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"


def test_an_activity_done_says_when(client_as: Any) -> None:
    sales = client_as("sales")
    deal = create(Deal, salesperson=sales.user)
    activity = create(Activity, salesperson=sales.user, deal=deal, done=False)
    done = sales.patch(f"/api/activities/{activity.pk}/", {"done": True}, format="json")
    assert done.status_code == 200, done.content
    assert done.json()["done_at"] is not None
