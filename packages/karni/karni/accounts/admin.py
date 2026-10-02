"""Admin integration for the Karni user model (accounts contract amendment A10).

Exposes :class:`KarniUserAdmin`, an email-based ``UserAdmin`` built on
``karni.admin.KarniModelAdmin`` with working add/change forms (no username
field anywhere). When the project has not swapped the user model
(``AUTH_USER_MODEL == "karni_accounts.User"``) the default user is registered
here explicitly — ``karni.admin``'s autodiscover deliberately skips
``AbstractBaseUser`` subclasses (its amendment C5).

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
from django.utils.module_loading import import_string

__all__ = ["KarniUserAdmin"]  # noqa: F822 - provided lazily via module __getattr__

_user_admin_class: type[Any] | None = None


def _build_user_admin() -> type[Any]:
    """Construct the concrete ``KarniUserAdmin`` class.

    Deferred so ``karni.admin`` (written for the active ``KARNI_ADMIN_BASE``,
    default django-unfold) and the active user model are only imported when
    the admin is actually used.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
    from django.contrib.auth.forms import UserChangeForm, UserCreationForm

    from karni.admin import KarniModelAdmin

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

    return KarniUserAdmin


def _get_user_admin_class() -> type[Any]:
    global _user_admin_class
    if _user_admin_class is None:
        _user_admin_class = _build_user_admin()
    return _user_admin_class


def __getattr__(name: str) -> Any:
    """Lazily expose :class:`KarniUserAdmin` (mirrors ``karni.admin``'s C6 pattern)."""
    if name == "KarniUserAdmin":
        return _get_user_admin_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    site: admin.AdminSite = import_string(site_path)
    user_model = get_user_model()
    if not site.is_registered(user_model):
        site.register(user_model, _get_user_admin_class())


_register_default_user_admin()
