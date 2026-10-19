"""Deciding: who may, what it does, and what it never does."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from karni.audit.models import ChangeLog
from karni.exceptions import KarniWriteDeferred
from karni.middleware import current_user

from karni_approvals import services
from karni_approvals.interception import bypass
from karni_approvals.models import Decision, PendingChange
from tests.conftest import make_user
from tests.testapp.models import Branch, Contract, Invoice

pytestmark = pytest.mark.django_db


def propose_amount(maker: Any, invoice: Invoice, amount: str = "20.00") -> PendingChange:
    invoice.amount = Decimal(amount)
    with current_user(maker), pytest.raises(KarniWriteDeferred):
        invoice.save()
    invoice.refresh_from_db()
    return PendingChange.objects.latest("created_at")


class TestDecide:
    def test_approval_applies_the_change_as_the_checker(
        self, maker: Any, checker: Any, invoice: Invoice
    ) -> None:
        pending = propose_amount(maker, invoice)
        decided = services.decide(pending, checker, "approve", "looks right")
        assert (
            decided.status == "approved"
            and decided.approvals == 1
            and decided.resolved_by == checker
        )
        invoice.refresh_from_db()
        assert invoice.amount == Decimal("20.00") and invoice.updated_by == checker
        entry = ChangeLog.objects.for_object(invoice).filter(action="update").get()
        assert entry.actor == checker and entry.diff["amount"] == ["10.00", "20.00"]
        decision = Decision.objects.get()
        assert (
            decision.checker == checker
            and decision.verdict == "approve"
            and decision.reason == "looks right"
        )
        assert ChangeLog.objects.for_object(decision).get().actor == checker

    def test_rejection_leaves_no_trace_on_the_row(
        self, maker: Any, checker: Any, invoice: Invoice
    ) -> None:
        stamp = invoice.updated_at
        pending = propose_amount(maker, invoice)
        decided = services.decide(pending, checker, "reject", "wrong amount")
        assert decided.status == "rejected" and decided.reason == "wrong amount"
        invoice.refresh_from_db()
        assert invoice.amount == Decimal("10.00") and invoice.updated_at == stamp
        assert not ChangeLog.objects.for_object(invoice).filter(action="update").exists()
        with pytest.raises(services.ApprovalError, match="APR005"):
            services.decide(decided, checker, "approve")

    def test_the_maker_cannot_be_the_checker(self, maker: Any, invoice: Invoice) -> None:
        pending = propose_amount(maker, invoice)
        with pytest.raises(services.ApprovalError, match="APR002"):
            services.decide(pending, maker, "approve")
        with pytest.raises(services.ApprovalError, match="APR002"):
            services.decide(pending, maker, "reject")
        # Not even a superuser who happens to be the maker.
        root = make_user("root@example.com", superuser=True)
        held = propose_amount(root, invoice, "30.00")
        with pytest.raises(services.ApprovalError, match="APR002"):
            services.decide(held, root, "approve")
        invoice.refresh_from_db()
        assert invoice.amount == Decimal("10.00")

    def test_a_checker_needs_the_permission_and_the_role(
        self, maker: Any, invoice: Invoice
    ) -> None:
        pending = propose_amount(maker, invoice)
        other_clerk = make_user("clerk2@example.com", "clerk")
        with pytest.raises(services.ApprovalError, match="APR003"):
            services.decide(pending, other_clerk, "approve")
        contract = Contract.objects.create(title="Lease")
        contract.value = Decimal("5")
        with current_user(maker), pytest.raises(KarniWriteDeferred):
            contract.save()
        held = PendingChange.objects.latest("created_at")
        staff = make_user(
            "staff@example.com", "staff"
        )  # holds every permission, not the finance role
        with pytest.raises(services.ApprovalError, match="only roles finance"):
            services.decide(held, staff, "approve")

    def test_a_checker_sees_and_decides_only_their_scope(
        self, maker: Any, invoice: Invoice
    ) -> None:
        pending = propose_amount(maker, invoice)
        south = Branch.objects.create(name="South")
        far = make_user("far@example.com", "branch_checker")
        far.branch = south
        assert services.visible_to(far, PendingChange.objects.all()).count() == 0
        with pytest.raises(services.ApprovalError, match="outside your scope"):
            services.decide(pending, far, "approve")
        near = make_user("near@example.com", "branch_checker")
        near.branch = invoice.branch
        assert services.visible_to(near, PendingChange.objects.all()).count() == 1
        assert services.pending_count(near) == 1 and services.pending_count(far) == 0
        assert services.decide(pending, near, "approve").status == "approved"

    def test_two_approvals_from_two_people(
        self, maker: Any, checker: Any, second_checker: Any
    ) -> None:
        with current_user(maker), pytest.raises(KarniWriteDeferred):
            Contract.objects.create(title="Lease", value=Decimal("1000"))
        pending = PendingChange.objects.get()
        first = services.decide(pending, checker, "approve")
        assert first.status == "pending" and first.approvals == 1 and not Contract.objects.exists()
        with pytest.raises(services.ApprovalError, match="APR004"):
            services.decide(pending, checker, "approve")
        second = services.decide(pending, second_checker, "approve")
        assert second.status == "approved" and second.approvals == 2
        contract = Contract.objects.get(title="Lease")
        assert contract.value == Decimal("1000") and contract.created_by == second_checker

    def test_a_stale_change_fails_instead_of_overwriting(
        self, maker: Any, checker: Any, invoice: Invoice
    ) -> None:
        pending = propose_amount(maker, invoice)
        with bypass("test: a concurrent edit"):
            invoice.amount = Decimal("15.00")
            invoice.save()
        with pytest.raises(services.ApprovalError, match="APR006"):
            services.decide(pending, checker, "approve")
        pending.refresh_from_db()
        assert pending.status == "failed" and "changed since" in pending.reason
        invoice.refresh_from_db()
        assert invoice.amount == Decimal("15.00")

    def test_an_approved_delete_soft_deletes_the_row(
        self, maker: Any, checker: Any, second_checker: Any
    ) -> None:
        contract = Contract.objects.create(title="Lease")
        with current_user(maker), pytest.raises(KarniWriteDeferred):
            contract.delete()
        pending = PendingChange.objects.get()
        services.decide(pending, checker, "approve")
        services.decide(pending, second_checker, "approve")
        assert not Contract.objects.filter(pk=contract.pk).exists()
        assert Contract._base_manager.get(pk=contract.pk).deleted_at is not None


class TestNotifications:
    def test_checkers_are_emailed_when_a_change_is_proposed(
        self, maker: Any, checker: Any, invoice: Invoice, django_capture_on_commit_callbacks: Any
    ) -> None:
        make_user("other-clerk@example.com", "clerk")  # not a checker: not emailed
        with django_capture_on_commit_callbacks(execute=True):
            propose_amount(maker, invoice)
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["checker@example.com"] and "Approval needed" in message.subject
        assert "amount" in message.body and "'10.00' -> '20.00'" in message.body
        assert message.from_email == "approvals@example.com"

    def test_notification_can_be_replaced_or_switched_off(
        self,
        maker: Any,
        checker: Any,
        invoice: Invoice,
        settings: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        settings.KARNI_APPROVALS_NOTIFY = ""
        with django_capture_on_commit_callbacks(execute=True):
            propose_amount(maker, invoice)
        assert mail.outbox == []
