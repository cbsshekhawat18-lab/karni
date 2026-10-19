"""The admin: a guarded change form is held with a message; the queue decides with a reason."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from karni_approvals.models import PendingChange
from tests.conftest import make_user
from tests.testapp.models import Invoice

pytestmark = pytest.mark.django_db


def staff_client(email: str, *roles: str) -> tuple[Any, Client]:
    user = make_user(email, *roles, staff=True)
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__in=[
                ContentType.objects.get_for_model(Invoice),
                ContentType.objects.get_for_model(PendingChange),
            ]
        )
    )
    client = Client()
    client.force_login(user)
    return user, client


def test_the_change_form_holds_the_change_and_says_so(invoice: Invoice) -> None:
    maker, client = staff_client("maker@example.com", "clerk")
    response = client.post(
        reverse("admin:testapp_invoice_change", args=[invoice.pk]),
        {
            "number": "INV-1",
            "amount": "50.00",
            "status": "draft",
            "note": "",
            "branch": str(invoice.branch_id),
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "sent for approval" in response.content.decode()
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("10.00")
    pending = PendingChange.objects.get()
    assert pending.maker == maker and pending.changes == {"amount": ["10.00", "50.00"]}


def test_the_queue_decides_with_a_reason_and_refuses_the_maker(invoice: Invoice) -> None:
    maker, maker_client = staff_client("maker@example.com", "clerk")
    maker_client.post(
        reverse("admin:testapp_invoice_change", args=[invoice.pk]),
        {
            "number": "INV-1",
            "amount": "50.00",
            "status": "draft",
            "note": "",
            "branch": str(invoice.branch_id),
        },
    )
    pending = PendingChange.objects.get()
    queue = reverse("admin:karni_approvals_pendingchange_changelist")
    # The maker's own change shows in their queue (own-scoped grant) but cannot be approved by them.
    page = maker_client.get(queue)
    assert page.status_code == 200 and "Invoice INV-1" in page.content.decode()
    refused = maker_client.post(
        queue,
        {
            "action": "approve_selected",
            "_selected_action": [str(pending.pk)],
            "post": "yes",
            "reason": "me",
        },
        follow=True,
    )
    assert "APR002" in refused.content.decode()
    pending.refresh_from_db()
    assert pending.status == "pending"
    # A checker gets the reason page, then the decision is recorded and applied.
    _checker, checker_client = staff_client("checker@example.com", "finance")
    ask = checker_client.post(
        queue, {"action": "approve_selected", "_selected_action": [str(pending.pk)]}
    )
    assert ask.status_code == 200 and 'name="reason"' in ask.content.decode()
    done = checker_client.post(
        queue,
        {
            "action": "approve_selected",
            "_selected_action": [str(pending.pk)],
            "post": "yes",
            "reason": "ok",
        },
        follow=True,
    )
    assert "Approve recorded for 1 change" in done.content.decode()
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("50.00")
    detail = checker_client.get(
        reverse("admin:karni_approvals_pendingchange_change", args=[pending.pk])
    )
    assert detail.status_code == 200 and "<code>amount</code>" in detail.content.decode()
