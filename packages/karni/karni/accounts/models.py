"""Karni's email-based user model and one-time token storage.

The concrete :class:`User` is swappable (``Meta.swappable = "AUTH_USER_MODEL"``).
Projects that need extra fields subclass :class:`AbstractKarniUser` in their
own app and set ``AUTH_USER_MODEL = "myapp.User"`` **before the first
migrate**; everything in Karni resolves the user model through
``settings.AUTH_USER_MODEL`` / ``get_user_model()`` so the swap is invisible
to the rest of the framework. See ``docs/accounts.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, PermissionsMixin
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from karni.accounts.managers import KarniUserManager
from karni.models import BaseModel

if TYPE_CHECKING:
    from django.db.models import QuerySet

__all__ = [
    "AbstractKarniUser",
    "OneTimeToken",
    "Permission",
    "Role",
    "RolePermission",
    "User",
]


class AbstractKarniUser(BaseModel, AbstractBaseUser, PermissionsMixin):
    """Abstract email-keyed user: no username field, email is the login.

    Combines :class:`karni.models.BaseModel` (UUID primary key, audit
    timestamps) with Django's ``AbstractBaseUser`` + ``PermissionsMixin``.
    ``email_verified`` is Karni's single source of truth for address
    ownership — it is only ever set by the verified email flows in
    ``karni.accounts.services`` (and mirrored from social-auth signals).

    Override / escape hatch: subclass in your own app to add fields, then
    point ``AUTH_USER_MODEL`` at your model. Redeclare ``objects`` to swap
    the manager and ``APIMeta`` to change the API field surface.
    """

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    email_verified = models.BooleanField(default=False)

    objects: ClassVar[KarniUserManager] = KarniUserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta(BaseModel.Meta):
        abstract = True

    class APIMeta:
        """API field surface consumed by ``karni.api``'s serializer generation.

        Permission flags and the password hash are deliberately absent from
        ``fields``; ``email`` changes only through the email-change flow.
        Subclasses inherit this and may redeclare it to expose more.
        """

        fields: ClassVar[list[str]] = [
            "id",
            "email",
            "first_name",
            "last_name",
            "email_verified",
            "date_joined",
            "created_at",
            "updated_at",
        ]
        read_only: ClassVar[list[str]] = ["email", "email_verified", "date_joined"]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        """Normalize the email's domain part, mirroring Django's ``AbstractUser``."""
        super().clean()
        self.email = type(self).objects.normalize_email(self.email)

    def get_full_name(self) -> str:
        """``"First Last"`` when names are set, otherwise the email address."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def get_short_name(self) -> str:
        """The first name when set, otherwise the email address."""
        return self.first_name or self.email

    # roles as data (karni.accounts.roles)

    @property
    def roles(self) -> QuerySet[Role]:
        """The :class:`Role` rows behind this user's groups (``user.roles.filter(...)``)."""
        return Role.objects.filter(group__in=self.groups.all()).order_by("slug")

    def has_role(self, slug: str) -> bool:
        """Does the user hold the role with this slug? One query, no string compared in Karni."""
        return self.groups.filter(name=slug).exists()

    def can(self, action: str, obj: Any = None, *, model: type[models.Model] | None = None) -> bool:
        """May the user perform ``action`` (``"shop.order:approve"``; or ``"approve"`` + ``obj=``)?

        The gate alone without ``obj``; with ``obj``, also whether that row is
        inside the scope the role grants. Grants are resolved once per user
        instance, so repeated calls in one request cost no further queries.
        """
        from karni.accounts.roles import user_can

        return user_can(self, action, obj, model=model)


class User(AbstractKarniUser):
    """Karni's default concrete user model.

    Swappable: set ``AUTH_USER_MODEL = "myapp.User"`` (subclassing
    :class:`AbstractKarniUser`) in your settings **before the first migrate**
    to replace it. Once migrations have run against the default model,
    swapping requires a manual data migration — Django does not support
    changing ``AUTH_USER_MODEL`` on a live database.
    """

    class Meta(AbstractKarniUser.Meta):
        swappable = "AUTH_USER_MODEL"
        verbose_name = "user"
        verbose_name_plural = "users"


class OneTimeToken(BaseModel):
    """Hashed single-use token backing the verify/reset/change-email flows.

    Only the SHA-256 hex digest of the secret is stored — the plaintext
    secret exists solely in the link emailed to the user. All issue/consume
    logic lives in :mod:`karni.accounts.tokens`; nothing should touch these
    rows directly.

    Override / escape hatch: token lifetimes come from the
    ``KARNI_ACCOUNTS_TOKEN_TTL`` setting (per-purpose seconds); the flows
    using these tokens are overridable at the service and view layers.
    """

    class Purpose(models.TextChoices):
        """What a token proves; one active token per ``(user, purpose)``."""

        VERIFY_EMAIL = "verify_email", "Verify email"
        RESET_PASSWORD = "reset_password", "Reset password"
        CHANGE_EMAIL = "change_email", "Change email"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="one_time_tokens",
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    new_email = models.EmailField(null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.purpose} token for user {self.user_id}"


# roles as data


class Role(BaseModel):
    """A role: one-to-one with the Django ``Group`` that carries membership.

    Membership stays ``user.groups`` (``assign_role`` / ``remove_role``, the
    admin's group widget, every existing ``HasRole`` check); the role adds
    what a group cannot hold — a stable ``slug``, a display name, a
    description, whether the project's declaration owns it (``is_system``)
    and, through :class:`RolePermission`, what its members may do and on
    which rows. Rows are reconciled from ``KARNI_ROLES`` by
    ``karni sync-roles``, which never deletes.
    """

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="karni_role")
    slug = models.SlugField(max_length=150, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    is_system = models.BooleanField(
        default=False, help_text="Declared by the project; its grants are managed by sync."
    )

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["slug"]

    def __str__(self) -> str:
        return self.name


class Permission(BaseModel):
    """One ``(model, action)`` a role can be granted — Karni's, not ``auth.Permission``.

    ``action`` is ``view`` / ``add`` / ``change`` / ``delete`` or one of the
    model's own (``class Karni: actions``). ``key`` is the ``app_label.model:action``
    form grants are written in.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    action = models.CharField(max_length=50)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["content_type__app_label", "content_type__model", "action"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["content_type", "action"], name="karni_permission_model_action"
            )
        ]

    @property
    def key(self) -> str:
        return f"{self.content_type.app_label}.{self.content_type.model}:{self.action}"

    def __str__(self) -> str:
        return self.key


class RolePermission(BaseModel):
    """A grant: ``role`` may perform ``permission`` on the rows ``scope`` reaches.

    ``scope`` is ``all``, ``own`` (rows whose ``Karni.owner_field`` is the
    user), ``related`` (rows whose ``Karni.scope_paths[scope_path]`` equals
    ``user.<scope_path>``) or ``custom`` (``scope_path`` names a scope
    registered with :func:`karni.accounts.roles.register_scope`).
    """

    class Scope(models.TextChoices):
        ALL = "all", "All rows"
        OWN = "own", "Own rows"
        RELATED = "related", "Rows related through a scope path"
        CUSTOM = "custom", "Rows a registered scope returns"

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="grants")
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.ALL)
    scope_path = models.CharField(max_length=100, blank=True, default="")

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["role__slug", "permission__action"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="karni_rolepermission_role_permission"
            )
        ]

    def __str__(self) -> str:
        suffix = f":{self.scope_path}" if self.scope_path else ""
        return f"{self.role_id} may {self.permission_id} ({self.scope}{suffix})"
