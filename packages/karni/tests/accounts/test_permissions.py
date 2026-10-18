"""Tests for :mod:`karni.accounts.permissions` — roles, DRF permissions, mixin hooks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from karni.accounts import permissions as perms

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model: Any) -> Any:
    return django_user_model.objects.create_user(
        email="owner@example.com", password="s3cret-pass-123"
    )


@pytest.fixture
def other_user(django_user_model: Any) -> Any:
    return django_user_model.objects.create_user(
        email="other@example.com", password="s3cret-pass-123"
    )


def _request(user: Any) -> Request:
    request = Request(APIRequestFactory().get("/"))
    request.user = user
    return request


# Roles


class TestRoles:
    def test_assign_role_creates_group_and_adds_member(self, user: Any) -> None:
        group = perms.assign_role(user, "editor")
        assert isinstance(group, Group)
        assert Group.objects.filter(name="editor").count() == 1
        assert user.groups.filter(name="editor").exists()

    def test_assign_role_is_idempotent(self, user: Any) -> None:
        perms.assign_role(user, "editor")
        perms.assign_role(user, "editor")
        assert Group.objects.filter(name="editor").count() == 1
        assert user.groups.filter(name="editor").count() == 1

    def test_user_roles_sorted(self, user: Any) -> None:
        perms.assign_role(user, "zeta")
        perms.assign_role(user, "alpha")
        assert perms.user_roles(user) == ["alpha", "zeta"]

    def test_user_roles_empty_cases(self, user: Any) -> None:
        assert perms.user_roles(user) == []
        assert perms.user_roles(AnonymousUser()) == []
        assert perms.user_roles(None) == []

    def test_has_role_any_of_semantics(self, user: Any) -> None:
        perms.assign_role(user, "editor")
        assert perms.has_role(user, "editor")
        assert perms.has_role(user, "admin", "editor")
        assert not perms.has_role(user, "admin")
        assert not perms.has_role(user)
        assert not perms.has_role(AnonymousUser(), "editor")
        assert not perms.has_role(None, "editor")

    def test_remove_role(self, user: Any) -> None:
        perms.assign_role(user, "editor")
        perms.remove_role(user, "editor")
        assert not user.groups.filter(name="editor").exists()
        # The group itself survives.
        assert Group.objects.filter(name="editor").exists()

    def test_remove_missing_role_is_noop(self, user: Any) -> None:
        perms.remove_role(user, "never-created")
        assert perms.user_roles(user) == []


# RolePermission


class TestRolePermission:
    def test_for_roles_builds_distinct_subclass(self) -> None:
        permission_class = perms.RolePermission.for_roles("editor", "admin")
        assert issubclass(permission_class, perms.RolePermission)
        assert permission_class is not perms.RolePermission
        assert permission_class.required_roles == ("editor", "admin")
        # The base class stays untouched.
        assert perms.RolePermission.required_roles == ()

    def test_grants_user_with_any_required_role(self, user: Any) -> None:
        perms.assign_role(user, "editor")
        permission = perms.RolePermission.for_roles("editor", "admin")()
        assert permission.has_permission(_request(user), APIView()) is True

    def test_denies_user_without_role(self, user: Any) -> None:
        permission = perms.RolePermission.for_roles("admin")()
        assert permission.has_permission(_request(user), APIView()) is False

    def test_denies_anonymous(self) -> None:
        permission = perms.RolePermission.for_roles("editor")()
        assert permission.has_permission(_request(AnonymousUser()), APIView()) is False

    def test_base_class_requires_authentication_only(self, user: Any) -> None:
        permission = perms.RolePermission()
        assert permission.has_permission(_request(user), APIView()) is True
        assert permission.has_permission(_request(AnonymousUser()), APIView()) is False


# IsOwner


class TestIsOwner:
    def test_owner_matches_by_fk_attname(self, user: Any) -> None:
        permission = perms.IsOwner()
        obj = SimpleNamespace(user_id=user.pk)
        view = SimpleNamespace(owner_field="user")
        assert permission.has_object_permission(_request(user), view, obj) is True

    def test_non_owner_denied(self, user: Any, other_user: Any) -> None:
        permission = perms.IsOwner()
        obj = SimpleNamespace(user_id=other_user.pk)
        view = SimpleNamespace(owner_field="user")
        assert permission.has_object_permission(_request(user), view, obj) is False

    def test_anonymous_denied(self, user: Any) -> None:
        permission = perms.IsOwner()
        obj = SimpleNamespace(user_id=user.pk)
        view = SimpleNamespace(owner_field="user")
        assert permission.has_object_permission(_request(AnonymousUser()), view, obj) is False

    def test_falls_back_to_object_attribute(self, user: Any) -> None:
        permission = perms.IsOwner()
        obj = SimpleNamespace(user=user)  # no user_id attname on this object
        view = SimpleNamespace(owner_field="user")
        assert permission.has_object_permission(_request(user), view, obj) is True

    def test_custom_owner_field(self, user: Any, other_user: Any) -> None:
        permission = perms.IsOwner()
        view = SimpleNamespace(owner_field="owner")
        mine = SimpleNamespace(owner_id=user.pk)
        theirs = SimpleNamespace(owner_id=other_user.pk)
        assert permission.has_object_permission(_request(user), view, mine) is True
        assert permission.has_object_permission(_request(user), view, theirs) is False

    def test_owner_field_with_id_suffix(self, user: Any) -> None:
        permission = perms.IsOwner()
        view = SimpleNamespace(owner_field="user_id")
        obj = SimpleNamespace(user_id=user.pk)
        assert permission.has_object_permission(_request(user), view, obj) is True

    def test_view_without_owner_field_uses_default(self, user: Any) -> None:
        permission = perms.IsOwner()
        obj = SimpleNamespace(user_id=user.pk)
        assert permission.has_object_permission(_request(user), APIView(), obj) is True

    def test_object_without_owner_denied(self, user: Any) -> None:
        permission = perms.IsOwner()
        view = SimpleNamespace(owner_field="user")
        assert permission.has_object_permission(_request(user), view, SimpleNamespace()) is False


# ObjectPermissionsMixin


class _OwnedView(perms.ObjectPermissionsMixin, APIView):
    permission_classes: ClassVar[list[Any]] = []
    object_permission_classes: ClassVar[list[Any]] = [perms.IsOwner]


class _PlainView(perms.ObjectPermissionsMixin, APIView):
    permission_classes: ClassVar[list[Any]] = []


class _ScopedView(perms.ObjectPermissionsMixin, APIView):
    permission_classes: ClassVar[list[Any]] = []

    def filter_queryset_for_user(self, queryset: Any) -> Any:
        # The docstring's owner-scoping override, adapted to the User model.
        if not self.request.user.is_authenticated:
            return queryset.none()
        return queryset.filter(pk=self.request.user.pk)


class TestObjectPermissionsMixin:
    def test_defaults_match_the_api_contract(self) -> None:
        # karni.api's BaseViewSet consumes exactly this surface.
        assert perms.ObjectPermissionsMixin.owner_field == "user"
        assert perms.ObjectPermissionsMixin.object_permission_classes == []
        assert callable(perms.ObjectPermissionsMixin.filter_queryset_for_user)
        assert callable(perms.ObjectPermissionsMixin.check_object_permissions)

    def test_object_permissions_pass_for_owner(self, user: Any) -> None:
        view = _OwnedView()
        obj = SimpleNamespace(user_id=user.pk)
        view.check_object_permissions(_request(user), obj)  # must not raise

    def test_object_permissions_deny_non_owner(self, user: Any, other_user: Any) -> None:
        view = _OwnedView()
        obj = SimpleNamespace(user_id=other_user.pk)
        with pytest.raises(PermissionDenied):
            view.check_object_permissions(_request(user), obj)

    def test_denial_uses_permission_message(self, user: Any, other_user: Any) -> None:
        view = _OwnedView()
        obj = SimpleNamespace(user_id=other_user.pk)
        with pytest.raises(PermissionDenied) as excinfo:
            view.check_object_permissions(_request(user), obj)
        assert str(excinfo.value.detail) == perms.IsOwner.message

    def test_empty_object_permissions_allow_anyone(self, user: Any, other_user: Any) -> None:
        view = _PlainView()
        obj = SimpleNamespace(user_id=other_user.pk)
        view.check_object_permissions(_request(user), obj)  # must not raise

    def test_filter_queryset_for_user_default_is_identity(
        self, user: Any, django_user_model: Any
    ) -> None:
        view = _PlainView()
        queryset = django_user_model.objects.all()
        assert view.filter_queryset_for_user(queryset) is queryset

    def test_filter_queryset_for_user_override_scopes(
        self, user: Any, other_user: Any, django_user_model: Any
    ) -> None:
        view = _ScopedView()
        view.request = _request(user)
        scoped = view.filter_queryset_for_user(django_user_model.objects.all())
        assert list(scoped) == [user]

    def test_get_object_permissions_instantiates_classes(self) -> None:
        view = _OwnedView()
        instances = view.get_object_permissions()
        assert len(instances) == 1
        assert isinstance(instances[0], perms.IsOwner)
