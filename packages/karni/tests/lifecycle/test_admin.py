"""The admin: legal states only in the menu, model errors on the form, conflicts as messages."""

from __future__ import annotations

import re
from typing import Any

import pytest
from django import forms
from django.contrib.admin.models import LogEntry
from django.db import connection
from django.test import Client
from django.urls import reverse

from tests.lifecycleapp.models import HAS_RANGES, Order, Room

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.lifecycleapp.urls")]


def _options(html: str, name: str) -> list[str]:
    select = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    assert select is not None, f"no <select name={name}>"
    return re.findall(r'<option value="([^"]*)"', select.group(0))


def test_the_change_form_offers_the_current_and_the_legal_next_states(admin_client: Client) -> None:
    order = Order.objects.create(title="o")
    order.transition("status", "confirmed")
    page = admin_client.get(reverse("admin:lifecycleapp_order_change", args=[order.pk]))
    assert page.status_code == 200
    assert _options(page.content.decode(), "status") == ["confirmed", "cancelled", "refunded"]


def test_the_add_form_offers_the_initial_states(admin_client: Client) -> None:
    page = admin_client.get(reverse("admin:lifecycleapp_order_add"))
    assert _options(page.content.decode(), "status") == ["draft"]
    page = admin_client.get(reverse("admin:lifecycleapp_ticket_add"))
    assert _options(page.content.decode(), "status") == ["open", "triaged"]


def test_a_model_form_reports_an_illegal_transition_on_the_field() -> None:
    form_class = forms.modelform_factory(Order, fields=["title", "status"])
    order = Order.objects.create(title="o")
    order.transition("status", "cancelled")
    form = form_class(data={"title": "o", "status": "draft"}, instance=order)
    assert not form.is_valid()
    (message,) = form.errors["status"]
    assert message.startswith("E980: ") and "terminal state" in message


def test_a_conflict_while_saving_is_an_error_message_and_nothing_is_logged(
    admin_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = Order.objects.create(title="o")
    from karni import guards

    real = guards.plan_write

    def racing(instance: Any, update_fields: Any = None) -> Any:
        plan = real(instance, update_fields)
        if isinstance(instance, Order) and not instance._state.adding:
            Order.objects.filter(pk=instance.pk).update(status="cancelled")  # someone else
        return plan

    monkeypatch.setattr(guards, "plan_write", racing)
    url = reverse("admin:lifecycleapp_order_change", args=[order.pk])
    response = admin_client.post(url, {"title": "o", "status": "confirmed"}, follow=True)
    assert response.redirect_chain[-1][0] == url
    shown = [str(message) for message in response.context["messages"]]
    assert any(text.startswith("E981: ") for text in shown), shown
    assert Order.objects.get(pk=order.pk).status == "cancelled"
    assert not LogEntry.objects.filter(object_id=str(order.pk)).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="EXCLUDE needs PostgreSQL")
@pytest.mark.skipif(not HAS_RANGES, reason="range columns need psycopg")
def test_an_overlapping_booking_is_a_form_error_naming_the_existing_one(
    admin_client: Client,
) -> None:
    import datetime as dt

    from psycopg.types.range import Range

    from tests.lifecycleapp.models import Reservation

    room = Room.objects.create(name="Blue")
    start = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)
    existing = Reservation.objects.create(
        room=room, during=Range(start, start + dt.timedelta(hours=2))
    )
    response = admin_client.post(
        reverse("admin:lifecycleapp_reservation_add"),
        {
            "room": str(room.pk),
            "during_0": "2026-10-21 11:00:00",
            "during_1": "2026-10-21 13:00:00",
            "status": "held",
        },
    )
    assert response.status_code == 200  # the form again, with the error
    assert f"E984: This overlaps Reservation {existing.pk}" in response.content.decode()
    assert Reservation.objects.count() == 1
