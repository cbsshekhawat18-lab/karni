"""Roles as data (ADR 0002, P1): ``KARNI_ROLES`` → tables → ``user.can`` / ``Can`` / ``@requires``.

The project here is ``tests.testapp``: ``Event`` declares ``class Karni``
(owner ``organizer``, scope path ``venue``, extra action ``approve``). The
role set under test is a project's own — nothing in Karni knows the names
``organizer`` or ``venue_manager``.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command
from django.db.models import Q
from django.test import override_settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from karni.accounts import roles as roles_mod
from karni.accounts.models import Permission, Role, RolePermission
from karni.accounts.permissions import assign_role
from karni.accounts.roles import (
    declared_roles,
    expand_grants,
    grants_for,
    permission_keys,
    register_scope,
    requires,
    rows_for,
    sync_roles,
    user_can,
)
from karni.api import Access, Authenticated, BaseViewSet, Can
from karni.api.access import AccessPermission
from karni.exceptions import KarniImproperlyConfigured, KarniValueError
from karni.introspect import roles_section
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db

PROJECT_ROLES = {
    "organizer": {
        "name": "Organizer",
        "grants": {
            "testapp.event:view": "own",
            "testapp.event:change": "own",
            "testapp.event:delete": "own",
            "testapp.event:add": "all",
            "testapp.venue:view": "all",
        },
    },
    "venue_manager": {
        "name": "Venue manager",
        "description": "Approves events at their venue.",
        "grants": {"testapp.event:view": "related:venue", "testapp.event:approve": "related:venue"},
    },
    "auditor": {"grants": {"testapp.event:view": "custom:published"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


@pytest.fixture(autouse=True)
def _published_scope() -> Any:
    register_scope("published", lambda user, model: Q(status=Event.Status.PUBLISHED))
    yield
    roles_mod._custom_scopes.pop("published", None)


@pytest.fixture
def synced() -> Any:
    with override_settings(KARNI_ROLES=PROJECT_ROLES):
        yield sync_roles()


def _user(django_user_model: Any, email: str, *role_slugs: str) -> Any:
    user = django_user_model.objects.create_user(email=email, password="s3cret-pass-123")
    for slug in role_slugs:
        assign_role(user, slug)
    return user


def _event(**kwargs: Any) -> Event:
    from django.utils import timezone

    kwargs.setdefault("title", "x")
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(**kwargs)


# --- the declaration ---------------------------------------------------------------


class TestDeclaration:
    def test_default_declaration_is_boring_and_valid(self) -> None:
        specs = {spec.slug: spec for spec in declared_roles()}
        assert set(specs) >= {"staff", "user", "customer"}
        assert specs["staff"].system and specs["staff"].grants == {"*": "all"}
        assert specs["user"].grants == {"*": "own"}

    @pytest.mark.parametrize(
        "declaration",
        [
            ["staff"],
            {"staff": "all"},
            {"staff": {"grants": ["*"]}},
            {"staff": {"grants": {"events": "all"}}},
            {"staff": {"grants": {"*": "everything"}}},
            {"staff": {"grants": {"*": "related"}}},
            {"staff": {"grants": {"*": "own:x"}}},
        ],
    )
    def test_malformed_declaration_is_e205(self, declaration: Any) -> None:
        with pytest.raises(KarniImproperlyConfigured, match="E205"):
            declared_roles(declaration)

    def test_permission_keys_include_the_models_own_actions(self) -> None:
        keys = permission_keys()
        assert keys["testapp.event:approve"] is Event
        assert {
            "testapp.event:view",
            "testapp.event:add",
            "testapp.event:change",
            "testapp.event:delete",
        } <= set(keys)
        assert "testapp.venue:approve" not in keys

    def test_specific_pattern_wins_over_wildcard(self) -> None:
        spec = declared_roles({"r": {"grants": {"*": "own", "testapp.event:approve": "all"}}})[0]
        grants = {g.permission: g for g in expand_grants(spec, permission_keys())}
        assert grants["testapp.event:approve"].scope == "all"
        assert grants["testapp.event:view"].scope == "own"

    def test_wildcard_own_skips_models_without_an_owner(self) -> None:
        spec = declared_roles({"r": {"grants": {"*": "own"}}})[0]
        keys = {g.permission for g in expand_grants(spec, permission_keys())}
        assert "testapp.event:view" in keys  # organizer
        assert "auth.group:view" not in keys  # nothing to own
        assert "auth.group:add" not in keys

    def test_explicit_own_on_unownable_model_is_e206(self) -> None:
        spec = declared_roles({"r": {"grants": {"auth.group:view": "own"}}})[0]
        with pytest.raises(KarniImproperlyConfigured, match="E206.*owner field"):
            expand_grants(spec, permission_keys())

    def test_unknown_pattern_is_e206(self) -> None:
        spec = declared_roles({"r": {"grants": {"testapp.event:aprove": "all"}}})[0]
        with pytest.raises(KarniImproperlyConfigured, match="E206.*matches no permission"):
            expand_grants(spec, permission_keys())

    def test_related_without_scope_path_is_e206(self) -> None:
        spec = declared_roles({"r": {"grants": {"testapp.venue:view": "related:city"}}})[0]
        with pytest.raises(KarniImproperlyConfigured, match="E206.*scope path"):
            expand_grants(spec, permission_keys())


# --- sync --------------------------------------------------------------------------


class TestSync:
    def test_sync_creates_roles_groups_permissions_and_grants(self, synced: Any) -> None:
        assert set(synced.created_roles) >= {"organizer", "venue_manager", "auditor", "ops"}
        role = Role.objects.get(slug="venue_manager")
        assert role.name == "Venue manager" and role.description.startswith("Approves")
        assert role.group.name == "venue_manager" and not role.is_system
        assert Role.objects.get(slug="ops").is_system
        assert Permission.objects.filter(action="approve").count() == 1
        grants = {
            g.permission.key: (g.scope, g.scope_path)
            for g in RolePermission.objects.filter(role=role).select_related(
                "permission__content_type"
            )
        }
        assert grants == {
            "testapp.event:view": ("related", "venue"),
            "testapp.event:approve": ("related", "venue"),
        }
        assert synced.grants["ops"] == len(permission_keys())

    def test_sync_is_idempotent_and_reports_updates(self, synced: Any) -> None:
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            again = sync_roles()
        assert again.created_roles == [] and again.updated_roles == []
        changed = {
            **PROJECT_ROLES,
            "auditor": {"name": "Auditor", "grants": {"testapp.event:view": "all"}},
        }
        with override_settings(KARNI_ROLES=changed):
            third = sync_roles()
        assert third.updated_roles == ["auditor"]
        grant = RolePermission.objects.get(role__slug="auditor")
        assert (grant.scope, grant.scope_path) == ("all", "")
        assert Role.objects.get(slug="auditor").name == "Auditor"

    def test_sync_never_deletes_roles_but_reports_them(self, synced: Any) -> None:
        with override_settings(KARNI_ROLES={"ops": PROJECT_ROLES["ops"]}):
            report = sync_roles()
        assert Role.objects.filter(slug="organizer").exists()
        assert Group.objects.filter(name="organizer").exists()
        assert "organizer" in report.undeclared_roles
        assert "kept" in report.render()

    def test_dry_run_writes_nothing(self) -> None:
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            report = sync_roles(dry_run=True)
        assert report.dry_run and "organizer" in report.created_roles
        assert not Role.objects.filter(slug="organizer").exists()
        assert report.render().startswith("Would sync")

    def test_management_command(self) -> None:
        out = StringIO()
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            call_command("karni_sync_roles", "--json", stdout=out)
        assert '"organizer"' in out.getvalue()
        out = StringIO()
        with override_settings(KARNI_ROLES=PROJECT_ROLES):
            call_command("karni_sync_roles", stdout=out)
        assert "unchanged" in out.getvalue()

    def test_migrate_runs_the_sync_by_default(self) -> None:
        """The post_migrate receiver ran when the test database was built."""
        assert Role.objects.filter(slug="staff", is_system=True).exists()
        assert RolePermission.objects.filter(role__slug="staff", scope="all").exists()

    def test_existing_groups_get_roles(self) -> None:
        from importlib import import_module

        from django.apps import apps

        roles_for_existing_groups = import_module(
            "karni.accounts.migrations.0002_roles"
        ).roles_for_existing_groups
        Group.objects.create(name="Branch Manager")
        Group.objects.create(name="branch-manager")
        roles_for_existing_groups(apps, None)
        slugs = set(Role.objects.values_list("slug", flat=True))
        assert {"branch-manager", "branch-manager-2"} <= slugs
        roles_for_existing_groups(apps, None)  # idempotent
        assert Role.objects.filter(slug__startswith="branch-manager").count() == 2


# --- what a user may do ---------------------------------------------------------------


class TestUserCan:
    def test_gate_without_an_object(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        assert organizer.can("testapp.event:add")
        assert organizer.can("testapp.venue:view")
        assert not organizer.can("testapp.venue:add")
        assert not organizer.can("testapp.event:approve")
        assert organizer.can("add", model=Event)
        assert not user_can(AnonymousUser(), "testapp.event:view")
        assert not user_can(None, "testapp.event:view")

    def test_bare_action_without_model_is_e207(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        with pytest.raises(KarniValueError, match="E207"):
            organizer.can("add")

    def test_own_scope_checks_the_row(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        other = _user(django_user_model, "x@example.com", "organizer")
        mine, theirs = _event(organizer=organizer), _event(organizer=other)
        assert organizer.can("change", obj=mine)
        assert not organizer.can("change", obj=theirs)
        assert organizer.can("testapp.event:delete", mine)

    def test_related_scope_follows_the_users_attribute(
        self, synced: Any, django_user_model: Any
    ) -> None:
        manager = _user(django_user_model, "m@example.com", "venue_manager")
        here, there = (
            Venue.objects.create(name="A", city="X"),
            Venue.objects.create(name="B", city="Y"),
        )
        manager.venue = here  # the user's side of the scope path, however the project models it
        at_here, at_there = _event(venue=here), _event(venue=there)
        assert manager.can("approve", obj=at_here)
        assert not manager.can("approve", obj=at_there)
        assert rows_for(manager, Event, "approve") == Q(venue=here)

    def test_related_scope_fails_closed_without_the_attribute(
        self, synced: Any, django_user_model: Any
    ) -> None:
        manager = _user(django_user_model, "m@example.com", "venue_manager")
        assert manager.can("testapp.event:approve")  # the gate: the role has it
        assert rows_for(manager, Event, "approve") is False  # no venue → no rows
        assert not manager.can(
            "approve", obj=_event(venue=Venue.objects.create(name="A", city="X"))
        )

    def test_custom_scope(self, synced: Any, django_user_model: Any) -> None:
        auditor = _user(django_user_model, "a@example.com", "auditor")
        published = _event(status=Event.Status.PUBLISHED)
        draft = _event()
        assert auditor.can("view", obj=published)
        assert not auditor.can("view", obj=draft)

    def test_unregistered_custom_scope_is_e206(self, django_user_model: Any) -> None:
        with override_settings(
            KARNI_ROLES={"r": {"grants": {"testapp.event:view": "custom:nope"}}}
        ):
            sync_roles()
        user = _user(django_user_model, "a@example.com", "r")
        with pytest.raises(KarniImproperlyConfigured, match="E206.*register_scope"):
            rows_for(user, Event, "view")

    def test_scopes_union_across_roles(self, synced: Any, django_user_model: Any) -> None:
        both = _user(django_user_model, "b@example.com", "organizer", "auditor")
        rows = rows_for(both, Event, "view")
        assert isinstance(rows, Q)
        assert both.can("view", obj=_event(status=Event.Status.PUBLISHED))
        assert both.can("view", obj=_event(organizer=both))
        assert not both.can("view", obj=_event())

    def test_all_scope_short_circuits(self, synced: Any, django_user_model: Any) -> None:
        ops = _user(django_user_model, "ops@example.com", "ops")
        assert rows_for(ops, Event, "view") is True
        assert ops.can("delete", obj=_event())

    def test_superuser_holds_everything(self, synced: Any, django_user_model: Any) -> None:
        root = django_user_model.objects.create_superuser(
            email="root@example.com", password="pw-123456"
        )
        assert root.can("testapp.event:approve") and rows_for(root, Event, "approve") is True

    def test_grants_resolve_once_per_user_instance(
        self, synced: Any, django_user_model: Any, django_assert_num_queries: Any
    ) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        organizer = django_user_model.objects.get(pk=organizer.pk)
        with django_assert_num_queries(1):
            grants_for(organizer)
        with django_assert_num_queries(0):
            for _ in range(20):
                assert organizer.can("testapp.event:add")
                assert not organizer.can("testapp.event:approve")
            assert rows_for(organizer, Event, "view") == Q(organizer=organizer)

    def test_user_roles_and_has_role(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer", "auditor")
        assert list(organizer.roles.values_list("slug", flat=True)) == ["auditor", "organizer"]
        assert organizer.has_role("organizer") and not organizer.has_role("ops")


# --- @requires ----------------------------------------------------------------------


class TestRequires:
    def test_guards_a_service_function_with_the_current_user(
        self, synced: Any, django_user_model: Any
    ) -> None:
        from karni.middleware import current_user

        @requires("testapp.event:approve")
        def approve(event: Event) -> str:
            return "approved"

        manager = _user(django_user_model, "m@example.com", "venue_manager")
        organizer = _user(django_user_model, "o@example.com", "organizer")
        event = _event()
        with current_user(manager):
            assert approve(event) == "approved"
        with current_user(organizer), pytest.raises(PermissionDenied) as info:
            approve(event)
        assert info.value.get_codes() == "E208"
        with pytest.raises(PermissionDenied):
            approve(event)  # nobody

    def test_guards_a_view_method_with_the_requests_user(
        self, synced: Any, django_user_model: Any
    ) -> None:
        class _View:
            def __init__(self, user: Any) -> None:
                self.request = Request(APIRequestFactory().post("/"))
                self.request.user = user

            @requires("approve", model=Event)
            def approve(self) -> str:
                return "ok"

        assert _View(_user(django_user_model, "m@example.com", "venue_manager")).approve() == "ok"
        with pytest.raises(PermissionDenied):
            _View(_user(django_user_model, "o@example.com", "organizer")).approve()


# --- Can in an access declaration ---------------------------------------------------


class _CanEvents(BaseViewSet):
    model = Event
    access = Access(
        read=Can("testapp.event:view"), write=Can("testapp.event:change"), create=Authenticated()
    )
    auto_register = False


def _request(user: Any, method: str = "get") -> Request:
    request = Request(getattr(APIRequestFactory(), method)("/"))
    request.user = user
    return request


class TestCanPredicate:
    def test_gate_and_rows(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        auditor = _user(django_user_model, "a@example.com", "auditor")
        nobody = _user(django_user_model, "n@example.com")
        read = _CanEvents.access.read
        assert read.allows(_request(organizer)) and read.allows(_request(auditor))
        assert not read.allows(_request(nobody)) and not read.allows(_request(AnonymousUser()))
        assert read.rows(_request(organizer)) == Q(organizer=organizer)
        assert read.rows(_request(auditor)) == Q(status=Event.Status.PUBLISHED)
        assert read.rows(_request(nobody)) is False
        assert read.rows(_request(AnonymousUser())) is False
        write = _CanEvents.access.write
        assert write.allows(_request(organizer, "patch")) and not write.allows(
            _request(auditor, "patch")
        )

    def test_through_the_viewset(self, synced: Any, django_user_model: Any) -> None:
        organizer = _user(django_user_model, "o@example.com", "organizer")
        other = _user(django_user_model, "x@example.com", "organizer")
        mine, theirs = (
            _event(organizer=organizer, title="mine"),
            _event(organizer=other, title="theirs"),
        )
        request = APIRequestFactory().get("/")
        request.user = organizer
        response = _CanEvents.as_view({"get": "list"})(request)
        assert [row["title"] for row in response.data["results"]] == ["mine"]
        request = APIRequestFactory().get("/")
        request.user = organizer
        assert _CanEvents.as_view({"get": "retrieve"})(request, pk=theirs.pk).status_code == 404
        request = APIRequestFactory().get("/")
        request.user = _user(django_user_model, "n@example.com")
        assert _CanEvents.as_view({"get": "list"})(request).status_code == 403
        assert mine.pk  # used above

    def test_access_permission_denies_before_any_query(
        self, synced: Any, django_user_model: Any
    ) -> None:
        nobody = _user(django_user_model, "n@example.com")
        view = _CanEvents()
        view.action = "list"
        view.request = _request(nobody)
        assert not AccessPermission().has_permission(view.request, view)


# --- karni context ------------------------------------------------------------------


def test_roles_section_lists_declared_roles_compactly() -> None:
    with override_settings(KARNI_ROLES=PROJECT_ROLES):
        line = roles_section()
    assert line is not None
    roles, actions = line.split("\n")
    assert roles.startswith(
        "ROLES: organizer[testapp.event:view=own,testapp.event:change=own,"
        "testapp.event:delete=own,+2]"
    )
    assert "ops![*=all]" in roles
    assert (
        "venue_manager[testapp.event:view=related:venue,testapp.event:approve=related:venue]"
        in roles
    )
    assert actions == "ACTIONS: Event(approve)"


def test_roles_section_degrades_on_a_bad_declaration(capsys: Any) -> None:
    with override_settings(KARNI_ROLES={"x": "nope"}):
        assert roles_section() is None
    assert "role inventory unavailable" in capsys.readouterr().err
