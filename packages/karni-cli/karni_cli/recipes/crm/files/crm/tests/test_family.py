"""The CRM part in a family: its settings section and its connection, on and off."""

import datetime as dt
from typing import Any

import pytest
from crm.models import Deal
from django.apps import apps
from django.utils import timezone
from karni import preferences
from karni.testing.factories import create

pytestmark = pytest.mark.django_db


def _proposal() -> Deal:
    deal = create(Deal)  # a new deal starts as a lead
    deal.transition("stage", "qualified")
    deal.transition("stage", "proposal")
    return deal


def _age(deal: Deal, days: int) -> None:
    """Backdate a deal's last change: a test row, so nothing to record."""
    when = timezone.now() - dt.timedelta(days=days)
    rows = Deal.objects.filter(pk=deal.pk)
    rows.update(
        updated_at=when
    )  # karni: allow(audited-bulk-write): backdates a test row


def test_stale_deals_follow_the_setting(client_as: Any) -> None:
    manager = client_as("crm-manager")
    old = create(Deal)
    _age(old, 40)
    _age(create(Deal), 10)
    found = manager.get("/api/deals/stale/").json()
    rows = found["results"] if isinstance(found, dict) else found
    assert [row["id"] for row in rows] == [str(old.pk)]
    with preferences.override(crm={"stale_after_days": 5}):
        found = manager.get("/api/deals/stale/").json()
    rows = found["results"] if isinstance(found, dict) else found
    assert len(rows) == 2


def test_managers_change_the_setting_and_reps_may_not(client_as: Any) -> None:
    url = "/api/preferences/sections/crm/"
    manager = client_as("crm-manager")
    assert manager.patch(url, {"stale_after_days": 7}, format="json").status_code == 200
    assert preferences.value("crm.stale_after_days", 0) == 7
    rep = client_as("crm-rep")
    assert rep.patch(url, {"stale_after_days": 9}, format="json").status_code == 403


def test_a_won_deal_goes_on_its_timeline_while_the_connection_is_on() -> None:
    if not apps.is_installed("karni.timeline"):  # alone: the connection stays off
        assert not preferences.active("crm.deal_timeline")
        return
    from karni.timeline.models import TimelineEntry

    deal = _proposal()
    deal.transition("stage", "won")
    entry = TimelineEntry.objects.get(kind="crm.deal.won")
    assert entry.title == f"Deal won: {deal.title}"
    other = _proposal()
    with preferences.override(connections={"crm.deal_timeline": False}):
        other.transition("stage", "won")
    assert TimelineEntry.objects.filter(kind="crm.deal.won").count() == 1
