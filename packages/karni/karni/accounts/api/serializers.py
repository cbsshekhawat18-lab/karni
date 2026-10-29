"""Serializers for the :mod:`karni.accounts` auth endpoints.

These do transport-level validation only; every account mutation lives in
:mod:`karni.accounts.services` and the views stay thin. Auth-mode specifics
(JWT pair vs. Django session) are deliberately absent here — the views branch
on ``settings.KARNI_AUTH_MODE`` per request (amendment A3), so one serializer
set serves both modes.

Override / escape hatch: subclass any serializer and wire it into a subclassed
view, then declare that view's URL *before* ``include("karni.accounts.urls")``
in your project URLconf — first match wins (amendment A11).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainSerializer

from karni.accounts.permissions import user_roles

__all__ = [
    "CLIENT_MAX_BYTES",
    "CurrentPasswordMixin",
    "EmailChangeSerializer",
    "LoginSerializer",
    "LogoutSerializer",
    "MeSerializer",
    "MeTermsSerializer",
    "OneTimeTokenSerializer",
    "OtpSendSerializer",
    "OtpVerifySerializer",
    "PasswordChangeSerializer",
    "PasswordResetConfirmSerializer",
    "PasswordResetSerializer",
    "RegisterSerializer",
    "SocialNameSerializer",
    "SocialTokenLoginSerializer",
    "TermsAcceptSerializer",
    "TermsStatusSerializer",
]

_PASSWORD_STYLE: dict[str, str] = {"input_type": "password"}

#: Experimental. The largest ``client`` object ``terms/accept/`` stores, in bytes of JSON.
CLIENT_MAX_BYTES = 4096


class MeTermsSerializer(serializers.Serializer):
    """Experimental. The ``terms`` of ``me/`` while ``KARNI_TERMS`` is set.

    ``required`` and ``accepted`` together say whether the API will refuse the
    user (``E245``) until they accept ``version``, which is at ``url``.
    """

    required = serializers.BooleanField(read_only=True)
    version = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    accepted = serializers.BooleanField(read_only=True)


class MeSerializer(serializers.ModelSerializer):
    """The authenticated user's profile — the payload of ``me/`` and login.

    Only the safe fields ``first_name`` / ``last_name`` are writable (the
    ``me/`` PATCH surface); ``email`` changes exclusively through the
    email-change flow and everything else is audit data. ``roles`` (amendment
    A15) lists the user's Django group names via
    :func:`karni.accounts.permissions.user_roles` — the ``@karni/ui``
    ``usePermission`` hook consumes it.

    Override / escape hatch: subclass and redeclare ``Meta.fields`` to expose
    extra fields of a swapped user model, then point a subclassed view (or
    ``KARNI_ACCOUNTS_AUTO_LOGIN`` consumers) at your serializer.
    """

    roles = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields: ClassVar[list[str]] = [
            "id",
            "email",
            "first_name",
            "last_name",
            "email_verified",
            "date_joined",
            "roles",
            "created_at",
            "updated_at",
        ]
        read_only_fields: ClassVar[list[str]] = [
            "id",
            "email",
            "email_verified",
            "date_joined",
            "created_at",
            "updated_at",
        ]

    def get_fields(self) -> dict[str, serializers.Field]:
        """The declared fields, plus ``terms`` while ``KARNI_TERMS`` is set (experimental).

        ``terms`` is ``{"required", "version", "url", "accepted"}``
        (:func:`karni.accounts.terms.me_status`). Unset, the field is absent
        from the payload and from the OpenAPI schema, whose description of
        this serializer stays the class docstring.
        """
        from karni.accounts import terms

        fields: dict[str, serializers.Field] = super().get_fields()
        if terms.configured():
            fields["terms"] = serializers.SerializerMethodField()
        return fields

    def get_roles(self, user: AbstractBaseUser) -> list[str]:
        """The user's role (Django group) names, read-only (amendment A15)."""
        return user_roles(user)

    @extend_schema_field(MeTermsSerializer)
    def get_terms(self, user: AbstractBaseUser) -> dict[str, Any] | None:
        """Experimental. The terms the user must accept, and whether they have."""
        from karni.accounts import terms

        return terms.me_status(user)


class RegisterSerializer(serializers.Serializer):
    """Input for ``register/``: email, password and the optional name fields.

    Uniqueness is checked here — a duplicate email is a 400, the documented
    and accepted enumeration surface of registration (amendment A9). The
    password runs through ``AUTH_PASSWORD_VALIDATORS`` against a transient
    user instance so similarity validators see the posted attributes.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, style=_PASSWORD_STYLE)
    first_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)

    def validate_email(self, value: str) -> str:
        """Reject addresses that already have an account (A9: accepted 400)."""
        user_model = get_user_model()
        if user_model._default_manager.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email address already exists.", code="unique"
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Run Django's password validators with the would-be user for context."""
        user_model = get_user_model()
        transient = user_model(
            email=attrs["email"],
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            password_validation.validate_password(attrs["password"], transient)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


class LoginSerializer(TokenObtainSerializer):
    """Credential check shared by both auth modes (amendment A3).

    Inherits SimpleJWT's ``TokenObtainSerializer``: the fields are the user
    model's ``USERNAME_FIELD`` (``email``) plus ``password``, credentials run
    through ``django.contrib.auth.authenticate`` and a failure — wrong
    password, unknown address or inactive account, indistinguishably — raises
    ``AuthenticationFailed`` (HTTP 401). ``validate`` issues no tokens; it
    leaves the authenticated user on ``self.user`` and
    :class:`karni.accounts.api.views.LoginView` decides per request whether to
    mint a JWT pair or open a Django session.
    """


class LogoutSerializer(serializers.Serializer):
    """Input for ``logout/``: the refresh token to blacklist (JWT mode only).

    The field is optional at this level because session mode posts an empty
    body; the view enforces presence when ``KARNI_AUTH_MODE`` is ``"jwt"``.
    """

    refresh = serializers.CharField(
        required=False, allow_blank=True, default="", write_only=True, trim_whitespace=False
    )


class CurrentPasswordMixin(serializers.Serializer):
    """Adds a ``current_password`` field checked against the request user.

    Used by every sensitive self-service mutation (password change, email
    change) so a hijacked session or leaked access token alone cannot rotate
    the account's credentials.
    """

    current_password = serializers.CharField(
        write_only=True, trim_whitespace=False, style=_PASSWORD_STYLE
    )

    def validate_current_password(self, value: str) -> str:
        """400 unless ``value`` matches the authenticated user's password."""
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.", code="invalid")
        return value


class PasswordChangeSerializer(CurrentPasswordMixin):
    """Input for ``password/change/``: the current and the new password."""

    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, style=_PASSWORD_STYLE
    )

    def validate_new_password(self, value: str) -> str:
        """Run ``AUTH_PASSWORD_VALIDATORS`` against the authenticated user."""
        try:
            password_validation.validate_password(value, self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class PasswordResetSerializer(serializers.Serializer):
    """Input for ``password/reset/``: just the address to (maybe) mail."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Input for ``password/reset/confirm/``: emailed token plus new password.

    The password validators run in
    :func:`karni.accounts.services.confirm_password_reset` — inside the same
    transaction as the token consumption (amendment A7), against the token's
    owner — so they are deliberately not duplicated here.
    """

    token = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, style=_PASSWORD_STYLE
    )


class OneTimeTokenSerializer(serializers.Serializer):
    """Input for the token-consuming endpoints: ``{"token": "<secret>"}``."""

    token = serializers.CharField(write_only=True)


class EmailChangeSerializer(CurrentPasswordMixin):
    """Input for ``email/change/``: the new address plus the current password.

    Uniqueness of ``new_email`` is validated (and re-validated at confirm
    time) by :mod:`karni.accounts.services`, which raises the DRF 400
    directly — the accepted enumeration surface of the flow (amendment A9).
    """

    new_email = serializers.EmailField()


class SocialNameSerializer(serializers.Serializer):
    """Experimental. The optional ``name`` of ``social/<provider>/``: Apple's first sign-in."""

    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)


class SocialTokenLoginSerializer(serializers.Serializer):
    """Experimental. Request body of ``social/<provider>/``: the ID token, a nonce and a name.

    ``nonce`` is the raw value the app generated for this sign-in (the token
    carries it, or its SHA-256 hex digest). ``name`` is used only when the
    token creates an account and carries no name itself, which is what Apple
    does: it sends the name to the app once, on the first sign-in.
    """

    id_token = serializers.CharField(max_length=16384, trim_whitespace=True)
    nonce = serializers.CharField(
        max_length=512, required=False, allow_blank=True, trim_whitespace=True
    )
    name = SocialNameSerializer(required=False, allow_null=True)


class OtpSendSerializer(serializers.Serializer):
    """Experimental. Request body of ``otp/send/``: the address to send a sign-in code to."""

    email = serializers.EmailField()


class OtpVerifySerializer(serializers.Serializer):
    """Experimental. Request body of ``otp/verify/``: the address and the code it received.

    Whitespace inside the code is ignored, so ``"123 456"`` is ``"123456"``.
    """

    email = serializers.EmailField()
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class TermsStatusSerializer(serializers.Serializer):
    """Experimental. The answer of ``terms/`` and ``terms/accept/``.

    ``accepted_at`` is when the user accepted ``version``, ``null`` when they
    have not. While ``required`` is true and ``accepted`` false, the API
    refuses the user with ``E245``.
    """

    version = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    required = serializers.BooleanField(read_only=True)
    accepted = serializers.BooleanField(read_only=True)
    accepted_at = serializers.DateTimeField(read_only=True, allow_null=True)


class TermsAcceptSerializer(serializers.Serializer):
    """Experimental. Request body of ``terms/accept/``: the version shown, and the client.

    ``version`` is the version the user read and accepted. ``client`` is an
    optional JSON object the app sends about itself (a mobile app's device,
    platform and app version, for example), stored with the acceptance. It
    may be at most ``CLIENT_MAX_BYTES`` bytes of JSON.
    """

    version = serializers.CharField(max_length=100)
    client = serializers.JSONField(required=False, allow_null=True)

    def validate_client(self, value: Any) -> Any:
        """A JSON object (or null) of at most ``CLIENT_MAX_BYTES`` bytes."""
        if value is None:
            return None
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'Send a JSON object, e.g. {"platform": "ios", "app_version": "2.4.0"}.',
                code="invalid",
            )
        size = len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
        if size > CLIENT_MAX_BYTES:
            raise serializers.ValidationError(
                f"The client object is {size} bytes of JSON. Send at most {CLIENT_MAX_BYTES}.",
                code="max_length",
            )
        return value
