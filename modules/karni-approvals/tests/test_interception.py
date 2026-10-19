"""A maker's guarded change becomes a pending change; the row is not touched."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from karni.audit.models import ChangeLog
from karni.exceptions import KarniWriteDeferred
from karni.middleware import current_user

from karni_approvals.interception import bypass
from karni_approvals.models import PendingChange
from tests.testapp.models import Contract, Invoice, Memo

pytestmark = pytest.mark.django_db


def test_a_guarded_update_is_held_and_the_row_untouched(maker: Any, invoice: Invoice) -> None:
    before = invoice.updated_at
    invoice.amount = Decimal("20.00")
    invoice.note = "raised"
    with current_user(maker), pytest.raises(KarniWriteDeferred) as caught:
        invoice.save()
    assert caught.value.code == "APR001" and caught.value.status == 202
    assert caught.value.payload["status"] == "pending" and "sent for approval" in str(caught.value)
    pending = PendingChange.objects.get()
    assert pending.action == "update" and pending.object_id == str(invoice.pk)
    assert pending.changes == {
        "amount": ["10.00", "20.00"],
        "note": ["", "raised"],
    }  # the whole change
    assert pending.maker == maker and pending.required == 1 and pending.expires_at is None
    assert pending.summary == "Invoice INV-1"
    invoice.refresh_from_db()
    assert (
        invoice.amount == Decimal("10.00") and invoice.note == "" and invoice.updated_at == before
    )
    assert not ChangeLog.objects.for_object(invoice).filter(action="update").exists()


def test_an_unguarded_change_is_written(maker: Any, invoice: Invoice) -> None:
    invoice.note = "just a note"
    with current_user(maker):
        invoice.save()
    invoice.refresh_from_db()
    assert invoice.note == "just a note" and not PendingChange.objects.exists()
    invoice.amount = Decimal("99.00")
    with current_user(maker):
        invoice.save(update_fields=["note", "updated_at"])  # the guarded field is not in this write
    assert not PendingChange.objects.exists()


def test_unattended_code_and_bypass_write_directly(maker: Any, invoice: Invoice) -> None:
    invoice.amount = Decimal("30.00")
    invoice.save()  # no current user: migrations, seeds, commands
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("30.00")
    invoice.amount = Decimal("40.00")
    with current_user(maker), bypass("data repair ticket #12"):
        invoice.save()
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("40.00") and not PendingChange.objects.exists()
    with pytest.raises(ValueError, match="reason"), bypass(""):
        pass


def test_any_change_policy_holds_create_update_and_delete(maker: Any) -> None:
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        Contract.objects.create(title="Lease", value=Decimal("1000"))
    assert not Contract.objects.exists()
    pending = PendingChange.objects.get()
    assert pending.action == "create" and pending.object_id == "" and pending.required == 2
    assert pending.changes["title"] == [None, "Lease"] and pending.changes["value"] == [
        None,
        "1000",
    ]
    assert pending.expires_at is not None and pending.summary.startswith("new contract")

    contract = Contract.objects.create(title="Lease", value=Decimal("1000"))  # unattended
    contract.title = "Lease 2"
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        contract.save()
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        contract.delete()
    contract.refresh_from_db()
    assert contract.title == "Lease" and contract.deleted_at is None
    assert list(PendingChange.objects.values_list("action", flat=True)) == [
        "delete",
        "update",
        "create",
    ]


def test_a_create_is_held_only_when_a_guarded_field_leaves_its_default(maker: Any) -> None:
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        Invoice.objects.create(number="INV-2", amount=Decimal("5.00"))  # amount has no default
    assert not Invoice.objects.filter(number="INV-2").exists()
    with current_user(maker):
        Memo.objects.create(text="no policy here")
    assert Memo.objects.count() == 1


def test_the_held_change_is_itself_history(maker: Any, invoice: Invoice) -> None:
    invoice.status = Invoice.Status.PAID
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        invoice.save()
    pending = PendingChange.objects.get()
    entry = ChangeLog.objects.for_object(pending).get()
    assert (
        entry.action == "create"
        and entry.actor == maker
        and entry.diff["status"] == [None, "pending"]
    )
