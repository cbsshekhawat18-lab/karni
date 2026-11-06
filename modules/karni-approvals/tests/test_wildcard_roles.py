"""A wildcard role is never a checker: only a grant that names approve or reject is.

Every scaffold carries ``user`` and ``customer`` (``"*": "own"``) and
``staff`` (``"*": "all"``). Before ``Karni.explicit_actions`` those wildcards
reached ``approve`` and ``reject``, so the owner of a row could approve a
change someone else proposed to it, and every member was emailed as a checker.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from karni.accounts.roles import sync_roles, user_can
from rest_framework.test import APIClient

from karni_approvals.models import PendingChange
from karni_approvals.notify import checkers_for
from karni_approvals.services import APPROVE_PERMISSION, REJECT_PERMISSION
from tests.conftest import make_user
from tests.testapp.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wildcard_roles(settings: Any) -> None:
    settings.KARNI_ROLES = {
        **settings.KARNI_ROLES,
        "user": {"name": "User", "grants": {"*": "own"}},
        "customer": {"name": "Customer", "grants": {"*": "own"}},
        "deciders": {"name": "Deciders", "grants": {"karni_approvals.pendingchange:*": "all"}},
    }
    sync_roles()


def client_for(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("role", ["user", "customer", "staff", "deciders"])
def test_a_wildcard_role_cannot_decide(role: str, maker: Any, checker: Any) -> None:
    owner = make_user("owner@example.com", role)
    invoice = Invoice.objects.create(number="INV-9", amount=Decimal("10.00"), created_by=owner)
    held = client_for(maker).patch(
        f"/api/invoices/{invoice.pk}/", {"amount": "99.00"}, format="json"
    )
    assert held.status_code == 202, held.content
    pk = held.json()["id"]
    assert not user_can(owner, APPROVE_PERMISSION) and not user_can(owner, REJECT_PERMISSION)
    for verdict in ("approve", "reject"):
        answer = client_for(owner).post(f"/api/pending-changes/{pk}/{verdict}/", {}, format="json")
        assert answer.status_code == 403, answer.content
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("10.00")
    # Nobody in the wildcard role is emailed as a checker; a named grant still decides.
    checkers = list(checkers_for(PendingChange.objects.get(pk=pk)))
    assert owner not in checkers and checker in checkers
    approved = client_for(checker).post(f"/api/pending-changes/{pk}/approve/", {}, format="json")
    assert approved.status_code == 200, approved.content
    invoice.refresh_from_db()
    assert invoice.amount == Decimal("99.00")
