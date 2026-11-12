"""The demo data karni seed writes: real-sounding, and the same on every run."""

import datetime as dt
import re
from typing import Any

import pytest
from django.apps import apps
from karni.seeding import seed, seeders

from crm.models import Activity, Company, Contact, Deal
from crm.seeds import COMPANIES

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def snapshot(app: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every model of the app, but for the times a save stamps."""
    found: dict[str, list[tuple[Any, ...]]] = {}
    for model in apps.get_app_config(app).get_models():
        names = [
            field.attname
            for field in model._meta.concrete_fields
            if not getattr(field, "auto_now", False)
            and not getattr(field, "auto_now_add", False)
        ]
        rows = model._base_manager.values_list(*names)
        found[model.__name__] = sorted(tuple(map(str, row)) for row in rows)
    return found


def without_round(name: str) -> str:
    """A name without the number a repeat is tagged with (Name 2)."""
    return re.sub(r" \d+$", "", name)


def test_the_same_seed_gives_the_same_rows_and_the_yaml_counts() -> None:
    seed(seed=7, now=NOW, reset=True)
    first = snapshot("crm")
    for model in (Company, Contact, Deal, Activity):
        assert model.objects.count() == seeders()[model].row_count(10)
    seed(seed=7, now=NOW, reset=True)
    assert snapshot("crm") == first
    seed(seed=8, now=NOW, reset=True)
    assert snapshot("crm") != first


def test_people_deals_and_activities_agree_with_their_company() -> None:
    seed(seed=3, now=NOW, reset=True)
    firms = {firm.name: firm for firm in COMPANIES}
    assert set(Company.objects.values_list("name", flat=True)) <= set(firms)
    for company in Company.objects.all():
        assert company.industry == firms[company.name].industry
    for contact in Contact.objects.select_related("company"):
        domain = firms[contact.company.name].domain
        assert contact.email.endswith("@" + domain)
    for deal in Deal.objects.select_related("company", "contact"):
        titles = [title for title, _ in firms[deal.company.name].deals]
        assert deal.title in titles
        assert deal.contact is not None and deal.contact.company_id == deal.company_id
    for activity in Activity.objects.select_related("deal"):
        assert activity.salesperson_id == activity.deal.salesperson_id
        assert activity.done == (activity.due_at < NOW)


def test_a_larger_count_never_clashes_on_a_name_or_an_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for model, count in ((Company, 45), (Contact, 200), (Deal, 90), (Activity, 30)):
        monkeypatch.setattr(seeders()[model].Meta, "count", count)
    seed(seed=1, now=NOW, reset=True)
    names = list(Company.objects.values_list("name", flat=True))
    assert len(names) == len(set(names)) == 45
    assert {without_round(name) for name in names} <= {firm.name for firm in COMPANIES}
    emails = list(Contact.objects.values_list("email", flat=True))
    assert len(emails) == len(set(emails)) == 200
    assert Deal.objects.count() == 90 and Activity.objects.count() == 30
