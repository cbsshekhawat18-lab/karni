"""Admin integration for the Karni user model and the roles (accounts contract amendment A10).

Exposes :class:`KarniUserAdmin`, an email-based ``UserAdmin`` built on
``karni.admin.KarniModelAdmin`` with working add/change forms (no username
field anywhere). When the project has not swapped the user model
(``AUTH_USER_MODEL == "karni_accounts.User"``) the default user is registered
here explicitly — ``karni.admin``'s autodiscover deliberately skips
``AbstractBaseUser`` subclasses (its amendment C5). Its change form carries
the **Effective permissions** button (ADR 0002, P5).

The role tables are registered here too: :class:`RoleAdmin` (editable, with
the **Permission matrix** and **Effective permissions** pages as changelist
buttons — ``admin:karni_accounts_role_permission_matrix`` and
``..._effective_permissions``), and read-only admins for ``Permission`` and
``RolePermission`` — grants change through the matrix and its guard rails,
never by editing a row.

Override / escape hatch — swapped user models reuse the class as a base::

    # myapp/admin.py
    from django.contrib import admin
    from karni.accounts.admin import KarniUserAdmin
    from myapp.models import User

    @admin.register(User)
    class UserAdmin(KarniUserAdmin):
        list_display = (*KarniUserAdmin.list_display, "plan")

The class (and therefore ``karni.admin`` / django-unfold) is built lazily on
first attribute access, so importing this module never drags the admin stack
in at app-populate time.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import admin
from django.urls import path

__all__ = ["KarniUserAdmin", "RoleAdmin"]  # noqa: F822 - provided lazily via module __getattr__

_user_admin_class: type[Any] | None = None
_role_admin_classes: tuple[type[Any], type[Any], type[Any]] | None = None


def _unfold_action() -> Any:
    """django-unfold's ``@action`` (a button plus a URL on its ``ModelAdmin``), or a stand-in.

    On another ``KARNI_ADMIN_BASE`` the stand-in only records ``url_path`` so
    :func:`_fallback_urls` can route the page; there is no button, the URL is
    the documented way in.
    """
    try:
        from unfold.decorators import action
    except ImportError:  # pragma: no cover - unfold is a core dependency

        def action(**options: Any) -> Any:
            def decorate(fn: Any) -> Any:
                fn.url_path = options.get("url_path", fn.__name__)
                return fn

            return decorate

    return action


def _fallback_urls(
    model_admin: Any, *, list_actions: tuple[str, ...] = (), detail_actions: tuple[str, ...] = ()
) -> list[Any]:
    """Routes for the page methods when the base admin is not django-unfold's.

    Unfold's ``get_urls`` already routes every ``actions_list`` /
    ``actions_detail`` method; a plain ``ModelAdmin`` does not, so these
    patterns (same names, same paths) fill in.
    """
    if hasattr(model_admin, "_get_base_actions_list"):
        return []
    opts = model_admin.model._meta
    wrap = model_admin.admin_site.admin_view
    urls = []
    for name in list_actions:
        method = getattr(model_admin, name)
        route = getattr(method, "url_path", name)
        urls.append(
            path(f"{route}/", wrap(method), name=f"{opts.app_label}_{opts.model_name}_{name}")
        )
    for name in detail_actions:
        method = getattr(model_admin, name)
        route = getattr(method, "url_path", name)
        urls.append(
            path(
                f"<path:object_id>/{route}/",
                wrap(method),
                name=f"{opts.app_label}_{opts.model_name}_{name}",
            )
        )
    return urls


def _build_user_admin() -> type[Any]:
    """Construct the concrete ``KarniUserAdmin`` class.

    Deferred so ``karni.admin`` (written for the active ``KARNI_ADMIN_BASE``,
    default django-unfold) and the active user model are only imported when
    the admin is actually used.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
    from django.contrib.auth.forms import UserChangeForm, UserCreationForm
    from django.http import Http404

    from karni.admin import KarniModelAdmin

    action = _unfold_action()
    user_model = get_user_model()

    class KarniUserCreationForm(UserCreationForm):
        """Add form asking for email + password pair only (no username)."""

        class Meta(UserCreationForm.Meta):
            model = user_model
            fields = ("email",)

    class KarniUserChangeForm(UserChangeForm):
        """Change form bound to the active (possibly swapped) user model."""

        class Meta(UserChangeForm.Meta):
            model = user_model
            fields = "__all__"

    class KarniUserAdmin(KarniModelAdmin, DjangoUserAdmin):
        """Email-based user admin for ``AbstractKarniUser`` models.

        Reusable base for swapped user models: subclass, extend the class
        attributes (``list_display``, ``fieldsets``, ...) and register it for
        your model. Every attribute is a plain Django ``UserAdmin`` knob.
        """

        add_form = KarniUserCreationForm
        form = KarniUserChangeForm
        ordering = ("email",)
        list_display = (
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "email_verified",
            "date_joined",
        )
        list_filter = ("is_staff", "is_superuser", "is_active", "email_verified", "groups")
        search_fields = ("email", "first_name", "last_name")
        readonly_fields = ("last_login", "date_joined", "created_at", "updated_at")
        fieldsets = (
            (None, {"fields": ("email", "password")}),
            ("Personal info", {"fields": ("first_name", "last_name")}),
            ("Status", {"fields": ("is_active", "email_verified")}),
            (
                "Permissions",
                {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
            ),
            (
                "Important dates",
                {"fields": ("last_login", "date_joined", "created_at", "updated_at")},
            ),
        )
        add_fieldsets = (
            (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
        )
        actions_detail = ["effective_permissions"]

        @action(
            description="Effective permissions",
            url_path="permissions",
            permissions=["view"],
            icon="shield_person",
        )
        def effective_permissions(self, request: Any, object_id: str) -> Any:
            """What this user may do, and why (ADR 0002, P5)."""
            from karni.accounts.matrix_admin import effective_view

            obj = self.get_object(request, object_id)
            if obj is None:
                raise Http404
            return effective_view(self, request, user=obj)

        def get_urls(self) -> Any:
            return [
                *_fallback_urls(self, detail_actions=("effective_permissions",)),
                *super().get_urls(),
            ]

    return KarniUserAdmin


def _build_role_admins() -> tuple[type[Any], type[Any], type[Any]]:
    """Construct ``RoleAdmin``, ``PermissionAdmin`` and ``RolePermissionAdmin`` (ADR 0002, P5)."""
    from django.contrib.auth.models import Group
    from django.db.models import Count, Q

    from karni.admin import KarniModelAdmin

    action = _unfold_action()

    class RoleAdmin(KarniModelAdmin):
        """Roles, with the permission matrix and effective-permissions pages as buttons.

        ``slug`` and ``is_system`` of a declared role follow ``KARNI_ROLES``;
        a role added here gets its Django group on save. Grants are not
        edited on this form — the matrix has the guard rails.
        """

        list_display = ("slug", "name", "is_system", "grant_count")
        search_fields = ("slug", "name")
        fields = ("slug", "name", "description", "is_system")
        readonly_fields = ("is_system",)
        actions_list = ["permission_matrix", "effective_permissions"]

        def get_queryset(self, request: Any) -> Any:
            alive = Q(grants__deleted_at__isnull=True) & ~Q(grants__scope="none")
            return (
                super().get_queryset(request).annotate(_grant_count=Count("grants", filter=alive))
            )

        @admin.display(description="grants", ordering="_grant_count")
        def grant_count(self, obj: Any) -> int:
            return int(getattr(obj, "_grant_count", 0))

        def get_readonly_fields(self, request: Any, obj: Any = None) -> Any:
            names = list(super().get_readonly_fields(request, obj))
            if obj is not None and obj.is_system and "slug" not in names:
                names.append("slug")
            return names

        def save_model(self, request: Any, obj: Any, form: Any, change: bool) -> None:
            if not obj.group_id:
                obj.group, _ = Group.objects.get_or_create(name=obj.slug)
            super().save_model(request, obj, form, change)

        @action(
            description="Permission matrix",
            url_path="matrix",
            permissions=["view"],
            icon="grid_view",
        )
        def permission_matrix(self, request: Any) -> Any:
            """Roles × models × actions, one scope selector per cell."""
            from karni.accounts.matrix_admin import matrix_view

            return matrix_view(self, request)

        @action(
            description="Effective permissions",
            url_path="effective",
            permissions=["view"],
            icon="shield_person",
        )
        def effective_permissions(self, request: Any) -> Any:
            """Pick a user, see what they may do and why."""
            from karni.accounts.matrix_admin import effective_view

            return effective_view(self, request)

        def get_urls(self) -> Any:
            return [
                *_fallback_urls(self, list_actions=("permission_matrix", "effective_permissions")),
                *super().get_urls(),
            ]

    class _ReadOnlyAdmin(KarniModelAdmin):
        """A changelist and a detail page, nothing editable: rows are managed elsewhere."""

        def has_add_permission(self, request: Any) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    class PermissionAdmin(_ReadOnlyAdmin):
        """``app.model:action`` rows, written by ``karni sync-roles``."""

        list_display = ("__str__", "content_type", "action")
        list_select_related = ("content_type",)
        search_fields = ("action", "content_type__app_label", "content_type__model")
        list_filter = ("action",)

    class RolePermissionAdmin(_ReadOnlyAdmin):
        """Grant rows, read-only here: change them in the permission matrix."""

        list_display = ("role", "permission", "scope", "scope_path", "origin")
        list_select_related = ("role", "permission", "permission__content_type")
        list_filter = ("origin", "scope", "role")
        search_fields = ("role__slug", "permission__action", "permission__content_type__model")
        actions_list = ["permission_matrix"]

        @action(
            description="Permission matrix",
            url_path="matrix",
            permissions=["view"],
            icon="grid_view",
        )
        def permission_matrix(self, request: Any) -> Any:
            from karni.accounts.matrix_admin import matrix_view

            return matrix_view(self, request)

        def get_urls(self) -> Any:
            return [
                *_fallback_urls(self, list_actions=("permission_matrix",)),
                *super().get_urls(),
            ]

    return RoleAdmin, PermissionAdmin, RolePermissionAdmin


def _get_user_admin_class() -> type[Any]:
    global _user_admin_class
    if _user_admin_class is None:
        _user_admin_class = _build_user_admin()
    return _user_admin_class


def _get_role_admin_classes() -> tuple[type[Any], type[Any], type[Any]]:
    global _role_admin_classes
    if _role_admin_classes is None:
        _role_admin_classes = _build_role_admins()
    return _role_admin_classes


def __getattr__(name: str) -> Any:
    """Lazily expose the admin classes (mirrors ``karni.admin``'s C6 pattern)."""
    if name == "KarniUserAdmin":
        return _get_user_admin_class()
    if name == "RoleAdmin":
        return _get_role_admin_classes()[0]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _register_role_admins() -> None:
    """Register the role tables on the configured admin site (idempotent)."""
    from karni.accounts.models import Permission, Role, RolePermission

    site_path: str = getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
    from karni.imports import import_setting

    site: admin.AdminSite = import_setting("KARNI_ADMIN_SITE", site_path)
    classes = _get_role_admin_classes()
    for model, model_admin in zip((Role, Permission, RolePermission), classes, strict=True):
        if not site.is_registered(model):
            site.register(model, model_admin)


def _register_default_user_admin() -> None:
    """Register the default user on the configured admin site.

    Runs at import time (``django.contrib.admin`` autodiscovers this module)
    but only when the project kept ``AUTH_USER_MODEL = "karni_accounts.User"``
    — a swapped model registers its own subclass instead (see the module
    docstring). Idempotent: an existing registration is left untouched.
    """
    if settings.AUTH_USER_MODEL != "karni_accounts.User":
        return

    from django.contrib.auth import get_user_model

    site_path: str = getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
    from karni.imports import import_setting

    site: admin.AdminSite = import_setting("KARNI_ADMIN_SITE", site_path)
    user_model = get_user_model()
    if not site.is_registered(user_model):
        site.register(user_model, _get_user_admin_class())


_register_default_user_admin()
_register_role_admins()
