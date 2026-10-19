"""Change history (ADR 0002, P4): captured at the model layer, redacted, pruned, measured."""

from __future__ import annotations

import datetime as dt
import decimal
import time
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone

from karni.accounts.permissions import assign_role
from karni.audit import REDACTED
from karni.audit.capture import audited_fields, clear_caches, json_value, sensitive_fields
from karni.audit.models import ChangeLog
from karni.audit.tasks import prune_change_logs
from karni.middleware import current_user
from tests.testapp.models import Price, Venue

pytestmark = pytest.mark.django_db


def _entries(obj: Any) -> list[ChangeLog]:
    return list(ChangeLog.objects.for_object(obj))


@pytest.fixture(autouse=True)
def _fresh_caches() -> Any:
    yield
    clear_caches()


def test_opt_in_and_redaction_metadata() -> None:
    assert audited_fields(Venue) is None
    assert set(audited_fields(Price) or ()) == {
        "deleted_at",
        "created_by",
        "updated_by",
        "amount",
        "currency",
        "note",
        "api_token",
    }
    assert sensitive_fields(Price) == {"note", "api_token"}  # metadata + the token pattern
    assert json_value(decimal.Decimal("1.50")) == "1.50"
    assert json_value(dt.date(2026, 1, 2)) == "2026-01-02"


def test_create_update_delete_restore_and_hard_delete(django_user_model: Any) -> None:
    user = django_user_model.objects.create_user(email="u@example.com", password="x")
    with current_user(user):
        price = Price.objects.create(
            amount=decimal.Decimal("10.00"), currency="EUR", note="vip", api_token="tok"
        )
    (created,) = _entries(price)
    assert created.action == "create" and created.actor == user
    assert created.object_id == str(price.pk)
    assert created.diff["amount"] == [None, "10.00"] and created.diff["currency"] == [None, "EUR"]
    assert created.diff["note"] == [REDACTED, REDACTED]  # Karni.sensitive
    assert created.diff["api_token"] == [REDACTED, REDACTED]  # "token" in the name
    assert created.diff["created_by"] == [None, str(user.pk)]

    price.amount = decimal.Decimal("12.50")
    price.save()  # outside any request or current_user(): the shell
    updated = _entries(price)[0]
    assert updated.action == "update" and updated.actor is None
    assert updated.diff == {"amount": ["10.00", "12.50"]}

    before = ChangeLog.objects.count()
    price.save()  # nothing changed: nothing recorded
    assert ChangeLog.objects.count() == before

    price.delete()  # soft
    assert _entries(price)[0].action == "delete"
    assert _entries(price)[0].diff["deleted_at"][0] is None
    price.restore()
    assert _entries(price)[0].action == "restore"
    pk = str(price.pk)  # Django clears the pk after a hard delete
    price.hard_delete()
    gone = ChangeLog.objects.filter(object_id=pk).order_by("-id").first()
    assert gone is not None and gone.action == "delete"
    assert gone.diff["amount"] == ["12.50", None] and gone.diff["note"] == [REDACTED, REDACTED]
    assert [e.action for e in ChangeLog.objects.filter(object_id=pk).order_by("id")] == [
        "create",
        "update",
        "delete",
        "restore",
        "delete",
    ]


def test_update_fields_saves_still_diff_the_whole_row() -> None:
    price = Price.objects.create(amount=decimal.Decimal("1.00"))
    price.currency = "USD"
    price.save(update_fields=["currency"])
    assert _entries(price)[0].diff == {"currency": ["EUR", "USD"]}


def test_visible_diff_respects_field_roles(django_user_model: Any) -> None:
    price = Price.objects.create(amount=decimal.Decimal("5.00"), currency="GBP")
    entry = _entries(price)[0]
    member = django_user_model.objects.create_user(email="m@example.com", password="x")
    assign_role(member, "user")
    staff = django_user_model.objects.create_user(email="s@example.com", password="x")
    assign_role(staff, "staff")
    assert "amount" in entry.visible_diff(staff)
    assert "amount" not in entry.visible_diff(member) and "currency" in entry.visible_diff(member)
    assert "amount" not in entry.visible_diff(None)


def test_async_writes_go_through_the_task(
    django_capture_on_commit_callbacks: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from celery import current_app

    # Karni's own suite configures no Celery app; run the task inline here.
    monkeypatch.setattr(current_app.conf, "task_always_eager", True)
    monkeypatch.setattr(current_app.conf, "task_eager_propagates", True)
    with (
        override_settings(KARNI_AUDIT_ASYNC=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        price = Price.objects.create(amount=decimal.Decimal("3.00"))
    assert [e.action for e in _entries(price)] == ["create"]


def test_bulk_update_leaves_no_entry_by_design() -> None:
    price = Price.objects.create(amount=decimal.Decimal("1.00"))
    before = ChangeLog.objects.count()
    Price.objects.filter(pk=price.pk).update(amount=decimal.Decimal("9.00"))
    assert ChangeLog.objects.count() == before  # karni check flags this (audited-bulk-write)


def test_pruning_is_off_by_default_and_bounded_by_the_window() -> None:
    price = Price.objects.create(amount=decimal.Decimal("1.00"))
    old = ChangeLog.objects.for_object(price).first()
    assert old is not None
    ChangeLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - dt.timedelta(days=40))
    price.currency = "USD"
    price.save()
    assert prune_change_logs() == 0 and ChangeLog.objects.for_object(price).count() == 2
    with override_settings(KARNI_AUDIT_RETENTION_DAYS=30):
        assert prune_change_logs() == 1
    assert [e.action for e in _entries(price)] == ["update"]


def test_malformed_metadata_is_e007(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Price.Karni, "audit", ["nope"])
    clear_caches()
    with pytest.raises(ImproperlyConfigured, match="E007"):
        audited_fields(Price)
    monkeypatch.setattr(Price.Karni, "audit", True)
    monkeypatch.setattr(Price.Karni, "sensitive", "note")
    clear_caches()
    with pytest.raises(ImproperlyConfigured, match="E007"):
        sensitive_fields(Price)


def test_capture_cost_per_save_is_small() -> None:
    """The snapshot SELECT plus the INSERT, measured here against an unaudited model."""

    def timed(make: Any, change: Any, rows: int = 60) -> float:
        objects = [make() for _ in range(rows)]
        start = time.perf_counter()
        for index, obj in enumerate(objects):
            change(obj, index)
            obj.save()
        return (time.perf_counter() - start) / rows

    def set_name(venue: Venue, index: int) -> None:
        venue.name = f"v{index}"

    def set_amount(price: Price, index: int) -> None:
        price.amount = decimal.Decimal(index)

    plain = timed(lambda: Venue.objects.create(name="x", city="y"), set_name)
    audited = timed(lambda: Price.objects.create(amount=decimal.Decimal("1.00")), set_amount)
    assert audited - plain < 0.005, f"audit overhead {1000 * (audited - plain):.2f} ms per save"
