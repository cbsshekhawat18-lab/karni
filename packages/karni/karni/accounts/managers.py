"""Managers for Karni's email-based user model.

Override / escape hatch: subclass :class:`KarniUserManager` and bind it as
``objects`` on your swapped user model to change how users are created; the
rest of Karni (services, serializers, admin) only ever goes through
``create_user`` / ``create_superuser``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

from karni.managers import BaseQuerySet, SoftDeleteManagerMixin

if TYPE_CHECKING:
    from karni.accounts.models import AbstractKarniUser


class KarniUserManager(SoftDeleteManagerMixin, BaseUserManager.from_queryset(BaseQuerySet)):  # type: ignore[misc]
    """Creates users keyed by email — there is no username field.

    Soft-delete aware like every ``BaseModel`` manager: deleted users are
    invisible to ``get_by_natural_key``, so they cannot authenticate, and
    ``objects.all_with_deleted()`` reaches them. A deleted user's email stays
    reserved (``USERNAME_FIELD`` must be unique) — ``restore()`` the user, or
    ``hard_delete()`` to free the address.

    ``use_in_migrations`` is True (like Django's own ``UserManager``) so data
    migrations can call ``create_user`` on historical models.
    """

    use_in_migrations = True

    def _create_user(
        self,
        email: str,
        password: str | None,
        **extra_fields: Any,
    ) -> AbstractKarniUser:
        """Shared implementation behind ``create_user`` and ``create_superuser``."""
        if not email:
            raise ValueError("Users require an email address.")
        email = self.normalize_email(email)
        user: AbstractKarniUser = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> AbstractKarniUser:
        """Create a regular user with a normalized email address.

        ``password=None`` stores an unusable password (the user must go
        through the password-reset flow, e.g. after a social signup).
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> AbstractKarniUser:
        """Create a superuser: ``is_staff`` and ``is_superuser`` forced to True."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("Superusers must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("Superusers must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)
