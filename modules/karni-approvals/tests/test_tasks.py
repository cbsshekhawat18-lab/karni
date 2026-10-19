"""Timeouts: expire or escalate, by policy; the sweep is the hourly task."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from karni.exceptions import KarniWriteDeferred
from karni.middleware import current_user

from karni_approvals.models import PendingChange
from karni_approvals.tasks import sweep_pending
from tests.conftest import make_user
from tests.testapp.models import Contract, Invoice

pytestmark = pytest.mark.django_db


def test_expire_and_escalate(
    maker: Any, invoice: Invoice, django_capture_on_commit_callbacks: Any
) -> None:
    make_user("staff@example.com", "staff")  # the escalation role
    invoice.amount = Decimal("20.00")
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        invoice.save()
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        Contract.objects.create(title="Lease", value=Decimal("1"))
    held_invoice = PendingChange.objects.get(action="update")
    held_contract = PendingChange.objects.get(action="create")
    assert held_invoice.expires_at is None  # Invoice: no timeout
    assert held_contract.expires_at is not None  # Contract: one hour

    past = timezone.now() - timedelta(hours=2)
    PendingChange.objects.filter(pk=held_invoice.pk).update(expires_at=past)
    PendingChange.objects.filter(pk=held_contract.pk).update(expires_at=past)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        counts = sweep_pending()
    assert counts == {"expired": 1, "escalated": 1}
    held_invoice.refresh_from_db()
    held_contract.refresh_from_db()
    assert held_invoice.status == "expired" and held_invoice.reason == "timed out"
    assert held_contract.status == "pending" and held_contract.escalated_at is not None
    assert held_contract.expires_at > timezone.now()
    assert [m.to for m in mail.outbox] == [["staff@example.com"]] and "overdue" in mail.outbox[
        0
    ].subject
