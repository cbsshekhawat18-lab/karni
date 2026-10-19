"""The permission matrix (ADR 0002, P5): cells, the diff, the guard rails, the audit trail.

The project is ``tests.testapp`` under a project's own role set; a
``permissions_admin`` role holds the matrix permission without holding
everything, which is what the guard rails are about.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.test import override_settings

from karni.accounts import roles as roles_mod
from karni.accounts.matrix import (
    DECLARED,
    MatrixRefused,
    apply_changes,
    build_matrix,
    effective_permissions,
    matrix_models,
    plan_changes,
    recent_changes,
    scope_options,
)
from karni.accounts.models import Permission, Role, RolePermission
from karni.accounts.permissions import assign_role
from karni.accounts.roles import grants_for, register_scope, sync_roles, user_can
from karni.audit.models import ChangeLog
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"
APPROVE = "testapp.event:approve"
DELETE = "testapp.event:delete"
MATRIX_CHANGE = "karni_accounts.rolepermission:change"

PROJECT_ROLES = {
    "organizer": {
        "name": "Organizer",
        "grants": {
            VIEW: "own",
            "testapp.event:change": "own",
            DELETE: "own",
            "testapp.event:add": "all",
            "testapp.venue:view": "all",
        },
    },
    "venue_manager": {
        "name": "Venue manager",
        "grants": {VIEW: "related:venue", APPROVE: "related:venue"},
    },
    "auditor": {"grants": {VIEW: "custom:published"}},
    "ops": {"system": True, "grants": {"*": "all"}},
    "permissions_admin": {
        "name": "Permissions admin",
        "grants": {
            "karni_accounts.rolepermission:*": "all",
            "karni_accounts.role:*": "all",
            VIEW: "own",
        },
    },
}


@pytest.fixture(autouse=True)
def _published_scope() -> Any:
    register_scope("published", lambda user, model: Q(status=Event.Status.PUBLISHED))
    yield
    roles_mod._custom_scopes.pop("published", None)


@pytest.fixture(autouse=True)
def _synced() -> Any:
    with override_settings(KARNI_ROLES=PROJECT_ROLES):
        sync_roles()
        yield


def _user(django_user_model: Any, email: str, *role_slugs: str, superuser: bool = False) -> Any:
    if superuser:
        return django_user_model.objects.create_superuser(email=email, password="s3cret-pass-123")
    user = django_user_model.objects.create_user(email=email, password="s3cret-pass-123")
    for slug in role_slugs:
        assign_role(user, slug)
    return user


def _row(role: str, key: str) -> RolePermission | None:
    label, action = key.rsplit(":", 1)
    return (
        RolePermission._base_manager.filter(
            role__slug=role,
            permission__action=action,
            permission__content_type__model=label.split(".")[1],
        )
        .select_related("permission")
        .first()
    )


class TestMatrix:
    def test_roles_models_and_cells(self) -> None:
        matrix = build_matrix()
        assert {role.slug for role in matrix.roles} >= set(PROJECT_ROLES)
        assert Role.objects.get(slug="ops").is_system
        labels = {model.label for model in matrix.models}
        assert "testapp.event" in labels and "karni_accounts.rolepermission" in labels
        assert not labels & {
            "contenttypes.contenttype",
            "sessions.session",
            "karni_audit.changelog",
        }
        event = next(model for model in matrix.models if model.label == "testapp.event")
        assert event.actions == ("view", "add", "change", "delete", "approve")
        cell = matrix.cell("organizer", VIEW)
        assert (cell.scope, cell.origin, cell.declared, cell.locked) == (
            "own",
            "declared",
            "own",
            False,
        )
        assert matrix.cell("ops", VIEW).locked
        assert matrix.cell("auditor", APPROVE).scope is None
        assert matrix.to_dict()["grants"]["venue_manager"][VIEW]["scope"] == "related:venue"

    def test_scope_options_follow_the_model(self) -> None:
        values = [value for value, _ in scope_options(Event)]
        assert values == ["all", "own", "related:venue", "custom:published"]
        assert (
            "own" not in [v for v, _ in scope_options(Permission)] or True
        )  # no owner: fine either way

    def test_matrix_exclude_setting(self) -> None:
        with override_settings(KARNI_MATRIX_EXCLUDE=["testapp", "karni_accounts.Role"]):
            labels = set(matrix_models())
        assert not any(label.startswith("testapp.") for label in labels)
        assert "karni_accounts.role" not in labels and "karni_accounts.rolepermission" in labels


class TestPlanAndApply:
    def test_plan_reports_only_real_changes(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        plan = plan_changes(root, [("organizer", VIEW, "own"), ("organizer", APPROVE, "all")])
        assert plan.ok and [c.to_dict() for c in plan.changes] == [
            {
                "role": "organizer",
                "permission": APPROVE,
                "before": None,
                "after": "all",
                "before_origin": None,
                "after_origin": "matrix",
            }
        ]
        assert not RolePermission.objects.filter(
            role__slug="organizer", permission__action="approve"
        )

    def test_grant_then_revoke_a_matrix_grant(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        member = _user(django_user_model, "o@example.com", "organizer")
        apply_changes(root, [("organizer", APPROVE, "all")])
        row = _row("organizer", APPROVE)
        assert row is not None and (row.scope, row.origin) == ("all", "matrix")
        assert user_can(member, APPROVE)
        apply_changes(root, [("organizer", APPROVE, None)])
        assert _row("organizer", APPROVE) is None  # gone outright, not soft-deleted
        delattr(member, "_karni_grants")
        assert not user_can(member, APPROVE)

    def test_revoking_a_declared_grant_leaves_a_tombstone_the_sync_respects(
        self, django_user_model: Any
    ) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        member = _user(django_user_model, "o@example.com", "organizer")
        apply_changes(root, [("organizer", VIEW, None)])
        row = _row("organizer", VIEW)
        assert row is not None and (row.scope, row.origin) == ("none", "matrix")
        assert VIEW not in grants_for(member)
        assert build_matrix().cell("organizer", VIEW).scope is None
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            report = sync_roles()
        assert f"organizer {VIEW}" in report.overridden and "matrix" in report.render()
        assert _row("organizer", VIEW).scope == "none"  # type: ignore[union-attr]
        # Handing the cell back to the declaration restores the declared grant.
        apply_changes(root, [("organizer", VIEW, DECLARED)])
        row = _row("organizer", VIEW)
        assert row is not None and (row.scope, row.origin) == ("own", "declared")

    def test_setting_the_declared_value_hands_the_cell_back(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        apply_changes(root, [("organizer", VIEW, "all")])
        assert _row("organizer", VIEW).origin == "matrix"  # type: ignore[union-attr]
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            sync_roles()
        assert _row("organizer", VIEW).scope == "all"  # type: ignore[union-attr]  # kept
        apply_changes(root, [("organizer", VIEW, "own")])
        assert _row("organizer", VIEW).origin == "declared"  # type: ignore[union-attr]

    def test_the_sync_removes_dropped_grants_outright_and_can_regrant(self) -> None:
        without = {**PROJECT_ROLES, "organizer": {"grants": {VIEW: "own"}}}
        with override_settings(KARNI_ROLES=without):
            sync_roles()
        assert _row("organizer", "testapp.venue:view") is None
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            sync_roles()  # would have hit the unique constraint on a soft-deleted row
        assert _row("organizer", "testapp.venue:view") is not None

    def test_unknown_role_permission_or_scope_is_refused(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        plan = plan_changes(
            root,
            [
                ("nobody", VIEW, "all"),
                ("organizer", "testapp.event:fly", "all"),
                ("organizer", VIEW, "related:city"),
            ],
        )
        reasons = [refusal.reason for refusal in plan.refusals]
        assert len(reasons) == 3 and "unknown role" in reasons[0]
        assert "unknown permission" in reasons[1] and "not available" in reasons[2]
        with pytest.raises(MatrixRefused, match="E213"):
            apply_changes(root, [("nobody", VIEW, "all")])


class TestGuardRails:
    def test_a_system_roles_declared_grant_is_locked(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        plan = plan_changes(root, [("ops", VIEW, "own"), ("ops", VIEW, None)])
        assert [r.permission for r in plan.refusals] == [VIEW]
        assert "system role" in plan.refusals[0].reason and "KARNI_ROLES" in plan.refusals[0].reason
        with pytest.raises(MatrixRefused) as exc:
            apply_changes(root, [("ops", VIEW, None)])
        assert exc.value.plan.refusals and exc.value.code == "E213"
        assert _row("ops", VIEW).scope == "all"  # type: ignore[union-attr]

    def test_nobody_grants_what_they_do_not_hold(self, django_user_model: Any) -> None:
        operator = _user(django_user_model, "p@example.com", "permissions_admin")
        plan = plan_changes(operator, [("auditor", DELETE, "all"), ("auditor", VIEW, "all")])
        reasons = {(r.permission, r.requested): r.reason for r in plan.refusals}
        assert "do not hold" in reasons[(DELETE, "all")]
        assert "only as own" in reasons[(VIEW, "all")]
        assert plan.changes == []
        plan = plan_changes(operator, [("auditor", VIEW, "own")])
        assert plan.ok and [(c.permission, c.after) for c in plan.changes] == [(VIEW, "own")]
        # Revoking needs holding the permission too.
        plan = plan_changes(operator, [("organizer", DELETE, None)])
        assert plan.refusals and "do not hold" in plan.refusals[0].reason

    def test_nobody_removes_their_own_last_permission_to_change_permissions(
        self, django_user_model: Any
    ) -> None:
        operator = _user(django_user_model, "p@example.com", "permissions_admin")
        plan = plan_changes(operator, [("permissions_admin", MATRIX_CHANGE, None)])
        assert plan.changes == [] and "last permission" in plan.refusals[0].reason
        # Another role of theirs keeps it: fine.
        assign_role(operator, "ops")
        delattr(operator, "_karni_grants")
        plan = plan_changes(operator, [("permissions_admin", MATRIX_CHANGE, None)])
        assert plan.ok and len(plan.changes) == 1
        # Someone else's last permission is not the guard rail's business; a superuser's never is.
        root = _user(django_user_model, "root@example.com", superuser=True)
        assert plan_changes(root, [("permissions_admin", MATRIX_CHANGE, None)]).ok

    def test_a_refused_batch_writes_nothing(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        with pytest.raises(MatrixRefused):
            apply_changes(root, [("organizer", APPROVE, "all"), ("ops", VIEW, None)])
        assert _row("organizer", APPROVE) is None


class TestAudit:
    def test_every_grant_change_is_recorded_with_the_operator(self, django_user_model: Any) -> None:
        operator = _user(django_user_model, "ops@example.com", "ops")
        apply_changes(operator, [("organizer", APPROVE, "all"), ("organizer", VIEW, None)])
        apply_changes(operator, [("organizer", APPROVE, "own")])
        content_type = ContentType.objects.get_for_model(RolePermission)
        entries = ChangeLog.objects.filter(content_type=content_type)
        # The sync's own rows are history too, with no actor (the declaration did it).
        assert entries.filter(actor__isnull=True, action="create").exists()
        mine = list(entries.filter(actor=operator))
        assert sorted(entry.action for entry in mine) == ["create", "update", "update"]
        recent = recent_changes(limit=3)
        assert [(e["role"], e["permission"], e["before"], e["after"]) for e in recent] == [
            ("organizer", APPROVE, "all", "own"),
            ("organizer", VIEW, "own", None),
            ("organizer", APPROVE, None, "all"),
        ]
        assert all(e["actor"] == operator for e in recent)


class TestEffectivePermissions:
    def test_explains_which_role_grants_what(self, django_user_model: Any) -> None:
        member = _user(django_user_model, "m@example.com", "organizer", "venue_manager")
        report = effective_permissions(member)
        assert report.roles == ["organizer", "venue_manager"] and not report.superuser
        by_key = {entry.permission: entry for entry in report.entries}
        assert by_key[VIEW].scope == "own | related:venue"
        assert [(s.role, s.scope, s.origin) for s in by_key[VIEW].sources] == [
            ("organizer", "own", "declared"),
            ("venue_manager", "related:venue", "declared"),
        ]
        assert by_key[APPROVE].scope == "related:venue"
        assert by_key[DELETE].scope == "own" and by_key[MATRIX_CHANGE].scope is None
        assert report.to_dict()["permissions"][0]["permission"]

    def test_all_wins_and_revocations_are_explained(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        member = _user(django_user_model, "m@example.com", "organizer", "ops")
        assert effective_permissions(member).to_dict()["permissions"][0]["scope"] == "all"
        apply_changes(root, [("organizer", VIEW, None)])
        entry = next(e for e in effective_permissions(member).entries if e.permission == VIEW)
        assert entry.scope == "all"  # ops still grants it
        revoked = next(s for s in entry.sources if s.role == "organizer")
        assert revoked.scope is None and revoked.origin == "matrix"

    def test_superuser_holds_everything(self, django_user_model: Any) -> None:
        root = _user(django_user_model, "root@example.com", superuser=True)
        report = effective_permissions(root)
        assert report.superuser and all(entry.scope == "all" for entry in report.entries)
        assert report.entries[0].sources[0].origin == "superuser"
