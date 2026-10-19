"""The rules: the explicit permission, no escalation, the reason, the record, the limit."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.core import mail
from django.utils import timezone
from karni.audit.models import ChangeBatch, ChangeLog

from karni_impersonation import services
from karni_impersonation.models import ImpersonationSession
from tests.conftest import make_user

pytestmark = pytest.mark.django_db


class TestWhoMayImpersonateWhom:
    def test_the_permission_is_explicit_never_staff_status(self, customer: Any) -> None:
        staff_without_grant = make_user("admin@example.com", staff=True)
        allowed, why = services.can_impersonate(staff_without_grant, customer)
        assert not allowed and "impersonate" in why
        with pytest.raises(services.ImpersonationError, match="IMP001"):
            services.start(staff_without_grant, customer, "help")
        assert not ImpersonationSession.objects.exists()

    def test_support_may_impersonate_a_customer(self, support: Any, customer: Any) -> None:
        assert services.can_impersonate(support, customer) == (True, "")

    def test_no_privilege_escalation_ever(self, support: Any, customer: Any, finance: Any) -> None:
        # A grant the actor lacks (finance holds testapp.secret:view; support does not).
        allowed, why = services.can_impersonate(support, finance)
        assert not allowed and "testapp.secret:view" in why
        with pytest.raises(services.ImpersonationError, match="IMP002"):
            services.start(support, finance, "help")
        # A superuser target.
        root = make_user("root@example.com", superuser=True)
        assert services.privilege_gap(support, root) == "the target is a superuser"
        # A Django permission the actor lacks.
        customer.user_permissions.add(Permission.objects.get(codename="delete_note"))
        assert (
            services.privilege_gap(support, customer) is None
        )  # support holds every Note permission
        customer.user_permissions.add(Permission.objects.get(codename="view_logentry"))
        customer = type(customer).objects.get(pk=customer.pk)
        assert "admin.view_logentry" in (services.privilege_gap(support, customer) or "")
        # A superuser actor may impersonate anyone active.
        assert services.privilege_gap(root, finance) is None
        with pytest.raises(services.ImpersonationError, match="IMP004"):
            services.start(support, support, "myself")

    def test_a_reason_is_required_by_default(
        self, support: Any, customer: Any, settings: Any
    ) -> None:
        with pytest.raises(services.ImpersonationError, match="IMP003"):
            services.start(support, customer, "   ")
        settings.KARNI_IMPERSONATION_REQUIRE_REASON = False
        session = services.start(support, customer, "")
        assert session.reason == ""


class TestTheSession:
    def test_start_records_everything_and_notifies_the_target(
        self, support: Any, customer: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            session = services.start(support, customer, "ticket #42")
        assert session.actor == support and session.target == customer
        assert session.reason == "ticket #42" and session.ended_at is None and session.is_active
        assert session.expires_at - session.started_at == timedelta(minutes=60)
        batch = ChangeBatch.objects.get(pk=session.batch_id)
        assert batch.kind == "impersonation" and batch.actor == support
        assert (
            batch.meta["target_email"] == "customer@example.com"
            and batch.meta["reason"] == "ticket #42"
        )
        entry = ChangeLog.objects.for_object(session).get()
        assert entry.action == "create" and entry.actor == support
        assert [m.to for m in mail.outbox] == [["customer@example.com"]]
        assert "support@example.com" in mail.outbox[0].body and "ticket #42" in mail.outbox[0].body

    def test_stop_and_sweep(self, support: Any, customer: Any) -> None:
        session = services.start(support, customer, "ticket")
        stopped = services.stop(session, services.STOPPED)
        assert stopped.ended_at is not None and stopped.end_reason == "stopped"
        assert services.stop(stopped, "again") is stopped  # idempotent
        assert services.active_session(session.pk) is None
        other = make_user("other@example.com", "customer")
        overdue = services.start(support, other, "ticket")
        ImpersonationSession.objects.filter(pk=overdue.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert services.sweep() == 1
        overdue.refresh_from_db()
        assert overdue.end_reason == "swept"

    def test_an_expired_session_is_ended_when_resolved(self, support: Any, customer: Any) -> None:
        session = services.start(support, customer, "ticket")
        ImpersonationSession.objects.filter(pk=session.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert services.active_session(session.pk) is None
        session.refresh_from_db()
        assert session.end_reason == "expired"

    def test_writes_inside_the_session_join_its_batch(self, support: Any, customer: Any) -> None:
        from karni.middleware import current_user

        from tests.testapp.models import Note

        session = services.start(support, customer, "ticket")
        with services.impersonating(session), current_user(customer):
            note = Note.objects.create(text="hello")
        entry = ChangeLog.objects.for_object(note).get()
        assert entry.actor == customer and entry.batch_id == session.batch_id
        # The batch holds the session record's own creation and the note.
        assert (
            ChangeLog.objects.filter(batch__kind="impersonation", batch__actor=support).count() == 2
        )


class TestTheBlockedList:
    def test_patterns_match_actions_permissions_models_and_paths(self) -> None:
        assert services.is_blocked({"destroy", "testapp.note:destroy"}) == "destroy"
        assert services.is_blocked({"change", "testapp.note:delete"}) == "*:delete"
        assert (
            services.is_blocked(
                {"refund", "karni_payments.payment", "karni_payments.payment:refund"}
            )
            == "karni_payments.*"
        )
        assert services.is_blocked({"list", "testapp.note", "testapp.note:view"}) is None
        assert services.is_blocked_path("/api/auth/password/change/") == "/api/auth/password/*"
        assert services.is_blocked_path("/api/notes/") is None
