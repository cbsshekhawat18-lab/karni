"""Admin integration for the Karni user model and the roles (accounts contract amendment A10).

Exposes :class:`KarniUserAdmin`, an email-based ``UserAdmin`` built on
``karni.admin.KarniModelAdmin`` with working add/change forms (no username
field anywhere). When the project has not swapped the user model
(``AUTH_USER_MODEL == "karni_accounts.User"``) the default user is registered
here explicitly — ``karni.admin``'s autodiscover deliberately skips
``AbstractBaseUser`` subclasses (its amendment C5). Its change form carries
the **Effective permissions** button (ADR 0002, P5).

Sign-in with an ID token (experimental) links provider identities in
``SocialIdentity``: they are listed read-only on each user's change page (an
inline) and in their own read-only changelist. Links are written only by the
sign-in flow.

Sign-in with a code (experimental) keeps each emailed code in ``LoginCode``,
listed read-only under *Login codes* so support can see that a code went out,
when it expires and how many guesses it took. The code itself is not there:
only its HMAC is stored, and the admin does not show even that.

Terms acceptance (experimental) records each user's acceptance of a version
of ``KARNI_TERMS`` in ``TermsAcceptance``: listed read-only under *Terms
acceptances*, filtered by version, exported with the changelist's *Export
selected* actions (there is no import), and shown read-only on each user's
change page while ``KARNI_TERMS`` is set. The table is append-only.

Per-user grants (experimental) live in ``UserGrant``. While
``KARNI_USER_GRANTS`` is on, each user's change page lists their grants in
an editable inline (add, edit, expire with *Expire now*, delete), and *User
grants* lists every grant, with *Expire selected* and the History tab. Both
need the grants ``karni_accounts.usergrant:<action>``, fill in
``granted_by`` and refuse a grant the operator does not hold (``E363``).

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


def _unfold_tabular_inline() -> type[Any]:
    """django-unfold's ``TabularInline``, or Django's on another ``KARNI_ADMIN_BASE``."""
    try:
        from unfold.admin import TabularInline
    except ImportError:  # pragma: no cover - unfold is a core dependency
        from django.contrib.admin import TabularInline
    return TabularInline


#: The ``SocialIdentity`` columns the admin shows, all read-only.
_IDENTITY_FIELDS = ("provider", "subject", "email_at_link", "created_at", "last_used_at")


def _build_identity_inline() -> type[Any]:
    """The read-only list of a user's linked provider identities (experimental)."""
    from karni.accounts.models import SocialIdentity

    class SocialIdentityInline(_unfold_tabular_inline()):  # type: ignore[misc]
        """Provider identities linked by sign-in with an ID token. Read-only."""

        model = SocialIdentity
        fk_name = "user"
        fields = _IDENTITY_FIELDS
        readonly_fields = _IDENTITY_FIELDS
        extra = 0
        can_delete = False
        show_change_link = False
        verbose_name_plural = "linked sign-in identities"

        def has_add_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    return SocialIdentityInline


#: The ``TermsAcceptance`` columns the admin shows, all read-only.
_ACCEPTANCE_FIELDS = ("version", "accepted_at", "ip", "user_agent", "client")


def _build_acceptance_inline() -> type[Any]:
    """The read-only list of a user's terms acceptances (experimental)."""
    from karni.accounts.models import TermsAcceptance

    class TermsAcceptanceInline(_unfold_tabular_inline()):  # type: ignore[misc]
        """The versions of the terms this user accepted. Read-only: the record is permanent."""

        model = TermsAcceptance
        fk_name = "user"
        fields = _ACCEPTANCE_FIELDS
        readonly_fields = _ACCEPTANCE_FIELDS
        extra = 0
        can_delete = False
        show_change_link = False
        verbose_name_plural = "terms acceptances"

        def has_add_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    return TermsAcceptanceInline


#: The ``UserGrant`` fields the admin edits, and the ones it shows read-only.
_GRANT_FIELDS = ("permission", "scope", "targets", "expires_at", "reason")
_GRANT_SHOWN = ("status", "granted_by", "created_at")


def grant_form(operator: Any) -> type[Any]:
    """Experimental. The admin's ``UserGrant`` form for ``operator``.

    ``targets`` is a comma-separated text field. *Expire now* sets
    ``expires_at`` to now. A new grant, or a change that gives more, is
    checked by :func:`karni.accounts.grants.check` (through the model's
    ``clean()``) and refused when ``operator`` does not hold it (``E363``).
    The saved row has ``granted_by = operator`` when the operator gave it.
    """
    from django import forms
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    from karni.accounts import grants
    from karni.accounts.models import UserGrant
    from karni.exceptions import KarniError

    class UserGrantForm(forms.ModelForm):  # type: ignore[type-arg]
        targets = forms.CharField(
            required=False,
            help_text="Row ids, separated by commas, for a related:<key> or tree:<path> scope.",
        )
        expire_now = forms.BooleanField(required=False, label="Expire now")

        class Meta:
            model = UserGrant
            fields = _GRANT_FIELDS

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.initial["targets"] = ", ".join(str(t) for t in self.instance.targets or ())
            self._gives = False

        def clean_targets(self) -> list[str]:
            raw = str(self.cleaned_data.get("targets") or "")
            return [part.strip() for part in raw.split(",") if part.strip()]

        def clean(self) -> dict[str, Any]:
            data: dict[str, Any] = super().clean() or {}
            if data.get("expire_now"):
                data["expires_at"] = timezone.now()
            if self.errors or not self.has_changed():
                return data
            changed = {name: data.get(name) for name in self.changed_data if name in _GRANT_FIELDS}
            if data.get("expire_now"):
                changed["expires_at"] = data["expires_at"]
            self._gives = self.instance._state.adding or grants.widens(self.instance, changed)
            if not self._gives:
                return data
            try:
                checked = grants.check(
                    data.get("permission", ""), data.get("scope", ""), data.get("targets")
                )
            except KarniError:
                return data  # the model's clean() reports it on its field
            reasons = grants.refusals(operator, checked)
            if reasons:
                raise ValidationError([f"E363: {reason}" for reason in reasons], code="E363")
            return data

        def save(self, commit: bool = True) -> Any:
            row = super().save(commit=False)
            if self.cleaned_data.get("expire_now"):
                row.expires_at = self.cleaned_data["expires_at"]
            if self._gives:
                row.granted_by = operator
            if commit:
                row.save()
            return row

    return UserGrantForm


def _grant_allowed(request: Any, action: str, obj: Any = None) -> bool:
    from django.db import models

    from karni.accounts.grants import GRANT_PERMISSION
    from karni.accounts.roles import user_can

    row = obj if isinstance(obj, models.Model) else None
    return user_can(request.user, f"{GRANT_PERMISSION}:{action}", row)


def _grant_status(obj: Any) -> str:
    if obj is None or obj.pk is None:
        return "-"
    if obj.is_live:
        return "live" if obj.expires_at is None else f"live until {obj.expires_at:%Y-%m-%d %H:%M}"
    return f"expired {obj.expires_at:%Y-%m-%d %H:%M}"


def _build_grant_inline() -> type[Any]:
    """The editable list of one user's grants on their change page (experimental)."""
    from karni.accounts.models import UserGrant

    class UserGrantInline(_unfold_tabular_inline()):  # type: ignore[misc]
        """A user's per-user grants: add, edit, expire, delete. ``granted_by`` is filled in."""

        model = UserGrant
        fk_name = "user"
        fields = (*_GRANT_FIELDS, "expire_now", *_GRANT_SHOWN)
        readonly_fields = _GRANT_SHOWN
        extra = 0
        show_change_link = True
        verbose_name_plural = "user grants"

        def get_formset(self, request: Any, obj: Any = None, **kwargs: Any) -> Any:
            kwargs["form"] = grant_form(request.user)
            return super().get_formset(request, obj, **kwargs)

        @admin.display(description="status")
        def status(self, obj: Any) -> str:
            return _grant_status(obj)

        def has_view_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "view") or _grant_allowed(request, "change")

        def has_add_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "add")

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "change")

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "delete")

    return UserGrantInline


def _build_grant_admin() -> type[Any]:
    """``UserGrantAdmin``: every per-user grant, editable, with *Expire selected* (experimental)."""
    from karni.admin import KarniModelAdmin

    class StatusFilter(admin.SimpleListFilter):
        title = "status"
        parameter_name = "status"

        def lookups(self, request: Any, model_admin: Any) -> Any:
            return (("live", "Live"), ("expired", "Expired"))

        def queryset(self, request: Any, queryset: Any) -> Any:
            if self.value() == "live":
                return queryset.live()
            if self.value() == "expired":
                return queryset.expired()
            return queryset

    class UserGrantAdmin(KarniModelAdmin):
        """Per-user grants. ``?user=<id>`` lists one user's. History is read-only."""

        list_display = ("user", "permission", "scope", "status", "granted_by", "created_at")
        list_select_related = ("user", "granted_by")
        list_filter = (StatusFilter,)
        search_fields = ("user__email", "permission", "scope", "reason")
        raw_id_fields = ("user",)
        fields = ("user", *_GRANT_FIELDS, "expire_now", *_GRANT_SHOWN)
        readonly_fields = _GRANT_SHOWN
        actions = ["expire_selected"]

        def get_form(
            self, request: Any, obj: Any = None, change: bool = False, **kwargs: Any
        ) -> Any:
            kwargs["form"] = grant_form(request.user)
            kwargs["fields"] = ("user", *_GRANT_FIELDS, "expire_now")
            return super().get_form(request, obj, change, **kwargs)

        @admin.display(description="status")
        def status(self, obj: Any) -> str:
            return _grant_status(obj)

        @admin.action(description="Expire selected grants now")
        def expire_selected(self, request: Any, queryset: Any) -> None:
            from karni.accounts.grants import expire

            count = 0
            for row in queryset.live():
                expire(request.user, row)
                count += 1
            self.message_user(request, f"{count} grant(s) expired.")

        def has_view_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "view", obj) or _grant_allowed(request, "change", obj)

        def has_add_permission(self, request: Any) -> bool:
            return _grant_allowed(request, "add")

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "change", obj)

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return _grant_allowed(request, "delete", obj)

    return UserGrantAdmin


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
        inlines = (_build_identity_inline(), _build_acceptance_inline(), _build_grant_inline())
        actions_detail = ["effective_permissions"]

        #: Fields only a superuser changes: anyone else sees them read-only.
        superuser_fields: tuple[str, ...] = ("is_superuser", "user_permissions")

        def get_readonly_fields(self, request: Any, obj: Any = None) -> Any:
            """``superuser_fields`` are read-only unless the editor is a superuser.

            A role's grant on the user model opens this page. Without this, a
            user holding that grant could make themselves a superuser.
            """
            names = list(super().get_readonly_fields(request, obj))
            if not getattr(request.user, "is_superuser", False):
                names.extend(name for name in self.superuser_fields if name not in names)
            return names

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            """Only a superuser changes a superuser's account (email, password, roles)."""
            if self._guards_superuser(request, obj):
                return False
            return bool(super().has_change_permission(request, obj))

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            """Only a superuser deletes a superuser's account."""
            if self._guards_superuser(request, obj):
                return False
            return bool(super().has_delete_permission(request, obj))

        @staticmethod
        def _guards_superuser(request: Any, obj: Any) -> bool:
            return bool(
                getattr(obj, "is_superuser", False)
                and not getattr(request.user, "is_superuser", False)
            )

        def get_inlines(self, request: Any, obj: Any = None) -> Any:
            """The acceptances inline while ``KARNI_TERMS`` is set, the grants inline while
            ``KARNI_USER_GRANTS`` is on (both experimental)."""
            from karni.accounts import grants, terms

            found = list(super().get_inlines(request, obj))
            if not terms.configured():
                found = [i for i in found if i.__name__ != "TermsAcceptanceInline"]
            if not grants.enabled() or obj is None:
                found = [i for i in found if i.__name__ != "UserGrantInline"]
            return found

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


def _build_identity_admin() -> type[Any]:
    """``SocialIdentityAdmin``: every linked provider identity, read-only (experimental)."""
    from karni.admin import KarniModelAdmin

    class SocialIdentityAdmin(KarniModelAdmin):
        """Provider identities linked by sign-in with an ID token. Nothing here is editable."""

        list_display = ("user", "provider", "email_at_link", "created_at", "last_used_at")
        list_select_related = ("user",)
        list_filter = ("provider",)
        search_fields = ("user__email", "email_at_link", "subject")
        fields = ("user", *_IDENTITY_FIELDS)
        readonly_fields = ("user", *_IDENTITY_FIELDS)

        def has_add_permission(self, request: Any) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    return SocialIdentityAdmin


def _build_login_code_admin() -> type[Any]:
    """``LoginCodeAdmin``: every stored sign-in code, read-only, without its hash (experimental)."""
    from karni.admin import KarniModelAdmin

    shown = ("email", "user", "created_at", "expires_at", "attempts", "used_at")

    class LoginCodeAdmin(KarniModelAdmin):
        """Sign-in codes sent by email. Nothing here is editable, and the hash is never shown."""

        list_display = shown
        list_select_related = ("user",)
        search_fields = ("email", "user__email")
        fields = shown
        readonly_fields = shown

        def has_add_permission(self, request: Any) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    return LoginCodeAdmin


def _build_acceptance_admin() -> type[Any]:
    """``TermsAcceptanceAdmin``: every terms acceptance, read-only, exportable (experimental)."""
    from karni.admin import KarniModelAdmin

    class TermsAcceptanceAdmin(KarniModelAdmin):
        """Who accepted which version of the terms, when and from where. Nothing is editable.

        The changelist's *Export selected as CSV / XLSX* actions export the
        record. There is no import: a row is written only by accepting.
        """

        list_display = ("user", "version", "accepted_at", "ip")
        list_select_related = ("user",)
        list_filter = ("version",)
        search_fields = ("user__email", "version", "ip")
        date_hierarchy = "accepted_at"
        fields = ("user", *_ACCEPTANCE_FIELDS)
        readonly_fields = ("user", *_ACCEPTANCE_FIELDS)

        def has_add_permission(self, request: Any) -> bool:
            return False

        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return False

        def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return False

    return TermsAcceptanceAdmin


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
    """Register the role tables, identities, codes, acceptances and user grants (idempotent)."""
    from karni.accounts.models import (
        LoginCode,
        Permission,
        Role,
        RolePermission,
        SocialIdentity,
        TermsAcceptance,
        UserGrant,
    )

    site_path: str = getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
    from karni.imports import import_setting

    site: admin.AdminSite = import_setting("KARNI_ADMIN_SITE", site_path)
    classes = _get_role_admin_classes()
    for model, model_admin in zip((Role, Permission, RolePermission), classes, strict=True):
        if not site.is_registered(model):
            site.register(model, model_admin)
    if not site.is_registered(SocialIdentity):
        site.register(SocialIdentity, _build_identity_admin())
    if not site.is_registered(LoginCode):
        site.register(LoginCode, _build_login_code_admin())
    if not site.is_registered(TermsAcceptance):
        site.register(TermsAcceptance, _build_acceptance_admin())
    if not site.is_registered(UserGrant):
        site.register(UserGrant, _build_grant_admin())


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
