"""Transitions through the ORM: the explicit API, plain assignment, history, events, concurrency."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from karni.audit.models import ChangeLog
from karni.events import on_transition
from karni.lifecycle import (
    IllegalTransition,
    StateConflict,
    allowed_transitions,
    any_initial_state,
    state_changed,
)
from karni.middleware import current_user
from karni.testing.factories import create
from tests.lifecycleapp.models import Order, Ticket

pytestmark = pytest.mark.django_db


def _order(**values: Any) -> Order:
    return Order.objects.create(title="o", **values)


# the explicit API


def test_transition_moves_the_state_and_writes_other_fields_with_it() -> None:
    order = _order()
    when = timezone.now()
    order.transition("status", "confirmed", confirmed_at=when)
    stored = Order.objects.get(pk=order.pk)
    assert (stored.status, stored.confirmed_at) == ("confirmed", when)
    assert order.allowed_transitions("status") == ("cancelled", "refunded")


def test_an_illegal_transition_names_current_requested_and_legal_states() -> None:
    order = _order()
    order.transition("status", "confirmed")
    with pytest.raises(IllegalTransition) as raised:
        order.transition("status", "draft")
    error = raised.value
    assert error.code == "E980"
    assert (error.field, error.current, error.requested) == ("status", "confirmed", "draft")
    assert error.allowed == ("cancelled", "refunded")
    assert "cannot go from 'confirmed' to 'draft'" in error.message
    assert "'cancelled', 'refunded'" in error.message
    assert order.status == "confirmed"  # the instance keeps its state
    assert Order.objects.get(pk=order.pk).status == "confirmed"


def test_nothing_leaves_a_terminal_state() -> None:
    order = _order()
    order.transition("status", "cancelled")
    with pytest.raises(IllegalTransition, match="terminal state"):
        order.transition("status", "confirmed")
    assert order.allowed_transitions("status") == ()


def test_an_undeclared_state_is_refused_before_any_sql() -> None:
    order = _order()
    with pytest.raises(IllegalTransition, match="'shipped' is not a state of Order.status"):
        order.transition("status", "shipped")


def test_transition_needs_a_saved_row_and_a_state_field() -> None:
    with pytest.raises(Exception, match="not saved yet"):
        Order(title="x").transition("status", "confirmed")
    order = _order()
    with pytest.raises(Exception, match="title is not a StateField") as raised:
        order.transition("title", "confirmed")
    assert getattr(raised.value, "code", "") == "E983"
    with pytest.raises(Exception, match="nope") as raised:
        order.transition("status", "confirmed", nope=1)
    assert getattr(raised.value, "code", "") == "E983"


# plain assignment + save()


def test_plain_assignment_is_checked_against_the_loaded_state() -> None:
    order = _order()
    loaded = Order.objects.get(pk=order.pk)
    loaded.status = "refunded"  # draft -> refunded is not declared
    with pytest.raises(IllegalTransition, match="from 'draft' to 'refunded'"):
        loaded.save()
    loaded.status = "confirmed"
    loaded.save()
    assert Order.objects.get(pk=order.pk).status == "confirmed"
    loaded.status = "refunded"  # now legal: confirmed -> refunded
    loaded.save(update_fields=["status"])
    assert Order.objects.get(pk=order.pk).status == "refunded"


def test_a_save_that_does_not_write_the_state_is_not_checked() -> None:
    order = _order()
    order.status = "refunded"
    order.title = "renamed"
    order.save(update_fields=["title"])
    assert Order.objects.get(pk=order.pk).title == "renamed"


def test_a_deferred_state_is_loaded_before_it_is_checked() -> None:
    order = _order()
    lazy = Order.objects.only("title").get(pk=order.pk)
    lazy.title = "t"
    lazy.save()  # status is deferred: not written, not checked
    lazy.status = "refunded"  # loads the deferred column first, then assigns
    with pytest.raises(IllegalTransition):
        lazy.save()


def test_refresh_from_db_resets_the_loaded_state() -> None:
    order = _order()
    Order.objects.filter(pk=order.pk).update(status="confirmed")  # bulk: bypasses the rules
    order.refresh_from_db()
    order.status = "refunded"
    order.save()
    assert Order.objects.get(pk=order.pk).status == "refunded"


# new rows


def test_a_new_row_starts_in_an_initial_state() -> None:
    with pytest.raises(IllegalTransition) as raised:
        Order.objects.create(status="confirmed")
    assert raised.value.code == "E982"
    assert "start in 'draft'" in raised.value.message
    assert ".transition('status', 'confirmed')" in raised.value.message
    assert Order.objects.count() == 0
    Ticket.objects.create(status="triaged")  # declared initial=[open, triaged]


def test_data_loading_may_start_in_any_state_with_a_reason() -> None:
    with any_initial_state(reason="importing legacy orders"):
        order = Order.objects.create(status="refunded")
    assert order.status == "refunded"
    with pytest.raises(Exception, match="needs reason") as raised:
        with any_initial_state(reason=" "):
            pass
    assert getattr(raised.value, "code", "") == "E982"


def test_factories_create_test_rows_in_any_state() -> None:
    assert create(Order, status="cancelled").status == "cancelled"


# history and events


def test_every_transition_is_recorded_with_its_actor() -> None:
    user = get_user_model().objects.create_user(email="ada@example.com", password="x-Password-1")
    order = _order()
    with current_user(user):
        order.transition("status", "confirmed")
        order.title = "renamed"
        order.status = "cancelled"
        order.save()
    entries = list(ChangeLog.objects.for_object(order).order_by("timestamp", "id"))
    assert [(entry.action, entry.diff) for entry in entries] == [
        ("create", {"title": [None, "o"], "status": [None, "draft"]}),
        ("transition", {"status": ["draft", "confirmed"]}),
        ("update", {"title": ["o", "renamed"]}),
        ("transition", {"status": ["confirmed", "cancelled"]}),
    ]
    assert entries[1].actor_id == user.pk and entries[3].actor_id == user.pk


def test_audit_false_records_no_transition() -> None:
    ticket = Ticket.objects.create()
    ticket.transition("status", "closed")
    assert not ChangeLog.objects.for_object(ticket).filter(action="transition").exists()


def test_state_changed_fires_once_per_transition_inside_the_transaction() -> None:
    heard: list[tuple[str, str, str]] = []

    def receiver(
        sender: Any, instance: Any, field: str, source: str, target: str, **kw: Any
    ) -> None:
        heard.append((field, source, target))

    state_changed.connect(receiver, sender=Order)
    try:
        order = _order()
        order.transition("status", "confirmed")
        order.title = "no transition"
        order.save()
    finally:
        state_changed.disconnect(receiver, sender=Order)
    assert heard == [("status", "draft", "confirmed")]


def test_on_transition_filters_by_target_and_source() -> None:
    seen: list[str] = []
    saved = list(state_changed.receivers)

    @on_transition(Order, "status", to="cancelled")
    def cancelled(order: Order) -> None:
        seen.append(f"cancelled:{order.status}")

    @on_transition("lifecycleapp.Order", source=["confirmed"])
    def left_confirmed(order: Order) -> None:
        seen.append(f"left-confirmed:{order.status}")

    try:
        first = _order()
        first.transition("status", "cancelled")
        second = _order()
        second.transition("status", "confirmed")
        second.transition("status", "refunded")
    finally:
        state_changed.receivers[:] = saved  # the decorators connected with dispatch uids
        state_changed.sender_receivers_cache.clear()
    assert seen == ["cancelled:cancelled", "left-confirmed:refunded"]


def test_a_listener_that_raises_undoes_the_transition() -> None:
    order = _order()

    def refuse(sender: Any, **kw: Any) -> None:
        raise RuntimeError("no")  # karni: bare-raise-ok

    state_changed.connect(refuse, sender=Order)
    try:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                order.transition("status", "confirmed")
    finally:
        state_changed.disconnect(refuse, sender=Order)
    assert Order.objects.get(pk=order.pk).status == "draft"


# concurrency, single connection: a stale instance cannot win


def test_a_stale_instance_cannot_overwrite_a_newer_state() -> None:
    order = _order()
    stale = Order.objects.get(pk=order.pk)
    order.transition("status", "cancelled")
    stale.status = "confirmed"  # legal from what *it* loaded (draft) ...
    with pytest.raises(StateConflict) as raised, transaction.atomic():
        stale.save()
    error = raised.value
    assert error.code == "E981" and error.status == 409
    assert error.details["current"] == "cancelled" and error.details["expected"] == "draft"
    assert "is 'cancelled' in the database" in error.message
    assert Order.objects.get(pk=order.pk).status == "cancelled"


def test_a_stale_instance_cannot_quietly_revert_the_state_on_another_save() -> None:
    order = _order()
    stale = Order.objects.get(pk=order.pk)
    order.transition("status", "confirmed")
    stale.title = "edited elsewhere"  # does not touch the state, but a full save writes it
    with pytest.raises(StateConflict):
        stale.save()
    assert Order.objects.get(pk=order.pk).status == "confirmed"
    stale.save(update_fields=["title"])  # leaving the state out is always fine
    assert Order.objects.get(pk=order.pk).title == "edited elsewhere"


def test_allowed_transitions_reads_the_loaded_state() -> None:
    order = _order()
    assert allowed_transitions(order, "status") == ("confirmed", "cancelled")
    assert allowed_transitions(Order(), "status") == ("draft",)


def test_a_management_command_gets_the_same_error(capsys: pytest.CaptureFixture[str]) -> None:
    order = _order()
    order.transition("status", "cancelled")
    with pytest.raises(IllegalTransition):
        call_command(
            "shell",
            command=f"from tests.lifecycleapp.models import Order; "
            f"Order.objects.get(pk='{order.pk}').transition('status', 'draft')",
        )
