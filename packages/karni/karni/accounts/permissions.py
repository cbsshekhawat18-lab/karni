"""Role helpers and DRF permission utilities for :mod:`karni.accounts`.

Roles are plain Django auth ``Group`` rows — no extra models, no migrations.
The helpers here are thin, typed wrappers so project code (and Karni's own
``MeSerializer.roles`` field, amendment A15) never touches the group API
directly.

Override / escape hatch: everything is a module-level function or a small
class designed for subclassing. :class:`ObjectPermissionsMixin` is consumed by
``karni.api.BaseViewSet`` and is an explicit staged exception to the
three-occurrences rule (amendment A11).

On a ``BaseViewSet`` the ``access`` declaration (:mod:`karni.api.access`) is
the gate and the row policy; its ``HasRole`` predicate is backed by
:func:`user_roles`. :class:`RolePermission` and :class:`IsOwner` remain the
building blocks for plain DRF views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib.auth.models import Group
from rest_framework.permissions import BasePermission

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.db.models import QuerySet
    from rest_framework.request import Request
    from rest_framework.views import APIView

__all__ = [
    "IsOwner",
    "ObjectPermissionsMixin",
    "RolePermission",
    "assign_role",
    "has_role",
    "remove_role",
    "user_roles",
]


def assign_role(user: AbstractBaseUser, name: str) -> Group:
    """Add *user* to the role (Django ``Group``) called *name*, creating it if needed.

    Idempotent: assigning an already-held role is a no-op. Returns the group.
    Override / escape hatch: roles are ordinary groups — manage them with the
    stock group API or the admin whenever these helpers are too thin.
    """
    group, _created = Group.objects.get_or_create(name=name)
    user.groups.add(group)  # type: ignore[attr-defined]
    return group


def remove_role(user: AbstractBaseUser, name: str) -> None:
    """Remove *user* from the role called *name*.

    A no-op when the group does not exist or the user is not in it; the group
    itself is never deleted.
    """
    group = Group.objects.filter(name=name).first()
    if group is not None:
        user.groups.remove(group)  # type: ignore[attr-defined]


def user_roles(user: AbstractBaseUser | None) -> list[str]:
    """Return the user's role names, sorted alphabetically.

    Anonymous users and ``None`` yield ``[]``. This is the source of the
    read-only ``roles`` field on the ``me/`` endpoint (amendment A15).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    return list(user.groups.order_by("name").values_list("name", flat=True))  # type: ignore[attr-defined]


def has_role(user: AbstractBaseUser | None, *names: str) -> bool:
    """Return ``True`` when *user* holds **any** of the given role names.

    Anonymous users, ``None`` and an empty *names* list yield ``False``.
    Combine calls (``has_role(u, "a") and has_role(u, "b")``) for all-of
    semantics.
    """
    if not names or user is None or not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name__in=names).exists()  # type: ignore[attr-defined]


class RolePermission(BasePermission):
    """DRF permission granting access to users holding any of ``required_roles``.

    Usage::

        class ArticleViewSet(BaseViewSet):
            permission_classes = [RolePermission.for_roles("editor", "admin")]

    With empty ``required_roles`` (the base class) it only requires
    authentication. Override / escape hatch: subclass and override
    :meth:`has_permission`, or set ``required_roles`` directly.
    """

    required_roles: ClassVar[tuple[str, ...]] = ()
    message = "You do not have the required role for this action."

    @classmethod
    def for_roles(cls, *names: str) -> type[RolePermission]:
        """Return a :class:`RolePermission` subclass requiring any of *names*."""
        suffix = "".join("".join(ch for ch in name.title() if ch.isalnum()) for name in names)
        return type(f"{cls.__name__}For{suffix}", (cls,), {"required_roles": tuple(names)})

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        if not self.required_roles:
            return True
        return has_role(user, *self.required_roles)


class IsOwner(BasePermission):
    """Object-level permission: the requesting user must own the object.

    Ownership is read from the view's ``owner_field`` (default ``"user"``).
    The comparison prefers the FK attname (``<owner_field>_id`` against
    ``request.user.pk``, no extra query); when the object has neither the
    attname nor the field, access is denied. A view may set
    ``owner_field = "user_id"``-style names directly — the trailing ``_id`` is
    handled.

    Override / escape hatch: subclass and override ``owner_field`` or
    :meth:`has_object_permission` for indirect ownership (e.g.
    ``obj.project.owner``).
    """

    owner_field = "user"
    message = "You must be the owner of this object."

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        field = getattr(view, "owner_field", None) or self.owner_field
        attname = field if field.endswith("_id") else f"{field}_id"
        if hasattr(obj, attname):
            return getattr(obj, attname) == user.pk
        if hasattr(obj, field):
            return getattr(obj, field) == user
        return False


class ObjectPermissionsMixin:
    """Object-permission and owner-scoping hooks consumed by ``karni.api.BaseViewSet``.

    Deliberately dependency-free (nothing here imports ``karni.api``) so the
    viewset layer can build on it: ``BaseViewSet.get_queryset()`` pipes the
    access-scoped queryset through :meth:`filter_queryset_for_user` (the
    escape hatch after ``access``), and DRF's per-object check picks up
    :attr:`object_permission_classes` via the extended
    :meth:`check_object_permissions` — after the access object check.
    Declaring ``object_permission_classes`` on a ``BaseViewSet`` is
    deprecated (removed in Karni 1.0): express the rule in ``access``. Mix it
    into any :class:`rest_framework.views.APIView` subclass.

    This mixin is an explicit staged exception to the three-occurrences rule
    (amendment A11): it ships before three consumers exist because
    ``karni.api.BaseViewSet`` is contracted to consume it.
    """

    owner_field: str = "user"
    """FK name identifying the owner, used by :class:`IsOwner` and scoping hooks."""

    object_permission_classes: ClassVar[list[type[BasePermission]]] = []
    """Extra permissions run per object on top of the view's ``permission_classes``."""

    def get_object_permissions(self) -> list[BasePermission]:
        """Instantiate :attr:`object_permission_classes`.

        Override / escape hatch: override to build permissions with arguments
        or to vary them per action.
        """
        return [permission() for permission in self.object_permission_classes]

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        """Run DRF's standard object checks, then :attr:`object_permission_classes`.

        Any failing permission raises through ``self.permission_denied`` with
        the permission's ``message``/``code``, exactly like DRF's own checks.
        """
        super().check_object_permissions(request, obj)  # type: ignore[misc]
        for permission in self.get_object_permissions():
            if not permission.has_object_permission(request, self, obj):  # type: ignore[arg-type]
                self.permission_denied(  # type: ignore[attr-defined]
                    request,
                    message=getattr(permission, "message", None),
                    code=getattr(permission, "code", None),
                )

    def filter_queryset_for_user(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Hook to scope list/detail querysets to the requesting user.

        The default returns the queryset unchanged. On a ``BaseViewSet`` it
        receives the queryset already narrowed by ``access.read`` and is the
        escape hatch for row logic ``access`` cannot express; prefer
        ``Owned(...)`` / ``Where(...)`` there. Overriding it in project code
        needs ``# karni: allow(access-override): <reason>`` (architecture
        rule ``access-override``)::

            # karni: allow(access-override): rows come from the billing service
            def filter_queryset_for_user(self, queryset):
                if not self.request.user.is_authenticated:
                    return queryset.none()
                return queryset.filter(**{self.owner_field: self.request.user})
        """
        return queryset
