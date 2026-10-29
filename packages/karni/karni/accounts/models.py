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
from django.db.models import Manager
from django.utils import timezone

from karni.accounts.managers import KarniUserManager
from karni.accounts.terms import PermanentRecordError
from karni.fields.constraints import LiveUniqueConstraint
from karni.managers import BaseQuerySet, ScopedManagerMixin
from karni.models import BaseModel

if TYPE_CHECKING:
    from django.db.models import QuerySet

__all__ = [
    "AbstractKarniUser",
    "LoginCode",
    "OneTimeToken",
    "Permission",
    "Role",
    "RolePermission",
    "SocialIdentity",
    "TermsAcceptance",
    "TermsAcceptanceQuerySet",
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


class SocialIdentity(BaseModel):
    """Experimental. One provider identity (Google, Microsoft, Apple, ...) linked to a user.

    Written by sign-in with an ID token (:mod:`karni.accounts.social_token`):
    ``subject`` is the provider's stable id for the person (the token's
    ``sub``, or ``<tid>:<oid>`` for Microsoft), unique per provider among live
    rows. Once linked, the identity signs in by subject alone, so the link
    survives a change of the user's email. ``email_at_link`` records the
    address the token carried when the link was made, and ``last_used_at``
    the latest sign-in through it.

    django-allauth's session redirect flow (``KARNI_SOCIAL_AUTH``) keeps its
    own ``SocialAccount`` table. The two are separate and never read each
    other.

    Override / escape hatch: rows are written only by
    :func:`karni.accounts.social_token.sign_in`, and the admin shows them
    read-only. Delete a row (``hard_delete()``) to unlink an identity.
    """

    provider = models.CharField(max_length=32)
    subject = models.CharField(max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_identities",
    )
    email_at_link = models.EmailField(blank=True, default="")
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "social identity"
        verbose_name_plural = "social identities"
        ordering: ClassVar[list[str]] = ["provider", "created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            LiveUniqueConstraint(
                fields=["provider", "subject"], name="karni_socialidentity_provider_subject"
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider} identity of user {self.user_id}"


class LoginCode(BaseModel):
    """Experimental. One sign-in code sent by email, stored as a keyed hash.

    Written by sign-in with a code (:mod:`karni.accounts.otp`). ``email`` is
    the address the code was sent to, lower-cased, and ``user`` the account
    that had it at that moment (``None`` for an address without an account).
    ``code_hash`` is an HMAC-SHA256 keyed by ``SECRET_KEY`` over the address
    and the code: the code itself is never stored. A code is looked up by its
    address, never by its hash, and dies when ``used_at`` is set, when
    ``expires_at`` passes, or when ``attempts`` reaches
    ``KARNI_EMAIL_OTP_MAX_ATTEMPTS``.

    :class:`OneTimeToken` does not fit: it finds a token by the hash of the
    secret alone, which needs a secret unique across every user, and it has
    no attempt counter. A six-digit code is neither.

    Override / escape hatch: rows are written only by
    :func:`karni.accounts.otp.send_code` and :func:`karni.accounts.otp.verify_code`,
    and the admin shows them read-only. ``karni.accounts.tasks.flush_login_codes``
    removes the dead ones.
    """

    email = models.EmailField(db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="login_codes",
    )
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "login code"
        verbose_name_plural = "login codes"
        ordering: ClassVar[list[str]] = ["-created_at"]

    def __str__(self) -> str:
        return f"login code {self.pk}"


_PERMANENT_HINT = (
    "Record a new acceptance with karni.accounts.terms.accept(). To make everyone accept "
    'again, change KARNI_TERMS["version"].'
)


def _permanent(operation: str) -> PermanentRecordError:
    return PermanentRecordError(
        f"TermsAcceptance rows are permanent: {operation} would rewrite the record of who "
        f"accepted which terms. {_PERMANENT_HINT}"
    )


class TermsAcceptanceQuerySet(BaseQuerySet):
    """Experimental. The queryset of :class:`TermsAcceptance`: it reads, it never rewrites.

    ``update()``, ``delete()``, ``hard_delete()`` and ``restore()`` raise
    :class:`~karni.accounts.terms.PermanentRecordError` (``E247``), so a bulk
    change cannot rewrite the record either. ``create()`` and
    ``get_or_create()`` insert as usual.
    """

    def update(self, **kwargs: Any) -> int:
        raise _permanent("update()")

    update.alters_data = True  # type: ignore[attr-defined]

    def delete(self) -> tuple[int, dict[str, int]]:
        raise _permanent("delete()")

    delete.queryset_only = True  # type: ignore[attr-defined]
    delete.alters_data = True  # type: ignore[attr-defined]

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        raise _permanent("hard_delete()")

    hard_delete.queryset_only = True  # type: ignore[attr-defined]
    hard_delete.alters_data = True  # type: ignore[attr-defined]

    def restore(self) -> int:
        raise _permanent("restore()")

    restore.queryset_only = True  # type: ignore[attr-defined]
    restore.alters_data = True  # type: ignore[attr-defined]


class TermsAcceptanceManager(ScopedManagerMixin, Manager.from_queryset(TermsAcceptanceQuerySet)):  # type: ignore[misc]
    """Experimental. The default manager of :class:`TermsAcceptance`: scoped, no rewrites."""


class TermsAcceptance(BaseModel):
    """Experimental. One user's acceptance of one version of the terms (``KARNI_TERMS``).

    Written by :func:`karni.accounts.terms.accept` (``POST <auth
    mount>/terms/accept/``): ``version`` is the ``KARNI_TERMS["version"]``
    the user accepted, ``accepted_at`` when, ``ip`` the client's address as
    Karni's throttles read it (honouring ``NUM_PROXIES``), ``user_agent`` its
    ``User-Agent`` header, and ``client`` what the app sent about itself (a
    mobile app's device and app version, for example). One row per user and
    version among live rows.

    The table is append-only. Saving an existing row, ``delete()``,
    ``hard_delete()``, ``restore()``, and ``update()`` or ``delete()`` on a
    queryset raise :class:`~karni.accounts.terms.PermanentRecordError`
    (``E247``), also through ``objects.without(...)``. Only the alias every
    model inherits from 0.2, deprecated and removed in 1.0, builds a plain
    queryset. A new row clears the gate's cached answer for its user and
    version, so the next request sees it.

    Override / escape hatch: write rows with :func:`karni.accounts.terms.accept`
    from a view of your own. A user's rows go only with the user:
    ``user.hard_delete()`` deletes them with it. The admin lists them
    read-only, with filters by version and an export.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="terms_acceptances",
    )
    version = models.CharField(max_length=100)
    accepted_at = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=1024, blank=True, default="")
    client = models.JSONField(null=True, blank=True)

    objects: ClassVar[TermsAcceptanceManager] = TermsAcceptanceManager()

    class Meta(BaseModel.Meta):
        verbose_name = "terms acceptance"
        verbose_name_plural = "terms acceptances"
        ordering: ClassVar[list[str]] = ["-accepted_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            LiveUniqueConstraint(
                fields=["user", "version"], name="karni_termsacceptance_user_version"
            )
        ]

    def __str__(self) -> str:
        return f"terms {self.version} accepted by user {self.user_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert only: saving a row that exists raises ``E247``."""
        if not self._state.adding:
            raise _permanent("save() of an existing row")
        super().save(*args, **kwargs)
        from karni.accounts.terms import remember_acceptance

        remember_acceptance(self.user_id, self.version, using=self._state.db)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Raises ``E247``: an acceptance is never deleted on its own."""
        raise _permanent("delete()")

    delete.alters_data = True  # type: ignore[attr-defined]

    def hard_delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Raises ``E247``: an acceptance is never deleted on its own."""
        raise _permanent("hard_delete()")

    hard_delete.alters_data = True  # type: ignore[attr-defined]

    def restore(self, using: str | None = None) -> None:
        """Raises ``E247``: an acceptance is never deleted, so it is never restored."""
        raise _permanent("restore()")

    restore.alters_data = True  # type: ignore[attr-defined]


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

    class Karni:
        """Every change to a role is history (``karni.audit``, ADR 0002 P5)."""

        audit = True
        cascade: ClassVar[dict[str, str]] = {
            "group": "a role is the Karni face of its auth Group and cannot outlive it",
        }

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
    ``user.<scope_path>``), ``custom`` (``scope_path`` names a scope
    registered with :func:`karni.accounts.roles.register_scope`) or ``none``
    — a declared grant the permission matrix revoked, kept as a row so the
    next ``karni sync-roles`` does not quietly restore it.

    ``origin`` says who owns the row: ``declared`` rows are written by the
    sync from ``KARNI_ROLES`` and follow the declaration; ``matrix`` rows
    were set in the permission matrix (or its API) and the sync leaves them
    alone. Every change is recorded by ``karni.audit``.
    """

    class Scope(models.TextChoices):
        ALL = "all", "All rows"
        OWN = "own", "Own rows"
        RELATED = "related", "Rows related through a scope path"
        CUSTOM = "custom", "Rows a registered scope returns"
        NONE = "none", "No rows (revoked in the permission matrix)"

    class Origin(models.TextChoices):
        DECLARED = "declared", "Declared in KARNI_ROLES"
        MATRIX = "matrix", "Set in the permission matrix"

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="grants")
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.ALL)
    scope_path = models.CharField(max_length=100, blank=True, default="")
    origin = models.CharField(max_length=16, choices=Origin.choices, default=Origin.DECLARED)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["role__slug", "permission__action"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="karni_rolepermission_role_permission"
            )
        ]

    class Karni:
        """The permission system's own audit trail: who changed which grant, from what."""

        audit = True
        cascade: ClassVar[dict[str, str]] = {
            "role": "a grant is part of its role, so deleting the role revokes it",
            "permission": "a grant of a permission that no longer exists grants nothing",
        }

    def __str__(self) -> str:
        suffix = f":{self.scope_path}" if self.scope_path else ""
        return f"{self.role_id} may {self.permission_id} ({self.scope}{suffix})"
