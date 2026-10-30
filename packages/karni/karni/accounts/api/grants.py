"""Experimental. Per-user grants as an API: list, add, change, revoke and bulk-grant.

The functions of :mod:`karni.accounts.grants` over HTTP, for a project's own
screen, a support tool or a provisioning script. Mounted under the accounts
URLs while ``KARNI_USER_GRANTS`` is on:

* ``GET permissions/grants/``: the grants the requester may view, paginated,
  filtered by ``?user=<id>``, ``?active=true|false`` and ``?permission=``;
* ``POST permissions/grants/``: ``{user, permission, scope, targets,
  expires_at, reason}``, one grant;
* ``GET``, ``PATCH``, ``DELETE permissions/grants/<id>/``: one grant, a change
  (``permission``, ``scope``, ``targets``, ``expires_at``, ``reason``) and a
  revoke (a soft delete, recorded in the history);
* ``POST permissions/grants/bulk/``: ``{users: [...], permission, scope,
  targets, expires_at, reason}``, the same grant to every user, all or none.

Gated on the grants ``karni_accounts.usergrant:view`` (reads), ``:add``
(``POST``), ``:change`` (``PATCH``) and ``:delete`` (``DELETE``). Rows follow
the requester's scope on ``UserGrant``: ``all`` reaches every grant, ``own``
the grants the requester received. A grant with a bad pattern, scope or
targets is a 400 (``E360``, ``E361``, ``E362``), one the requester does not
hold a 403 (``E363``) with ``reasons``, and every route answers 404
(``E364``) while the switch is off.

Override / escape hatch: declare your own view at the same path before the
accounts include, or call :mod:`karni.accounts.grants` from your own.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.accounts import grants
from karni.accounts.models import UserGrant
from karni.accounts.roles import rows_for, user_can
from karni.exceptions import KarniValueError
from karni.rows import apply_rows

__all__ = [
    "BULK_LIMIT",
    "BulkGrantSerializer",
    "UserGrantBulkView",
    "UserGrantDetailView",
    "UserGrantListView",
    "UserGrantPermission",
    "UserGrantSerializer",
]

#: The most users one ``bulk/`` request grants to.
BULK_LIMIT = 1000

_ACTIONS: dict[str, str] = {"POST": "add", "PUT": "change", "PATCH": "change", "DELETE": "delete"}
_FIELDS: dict[str, str] = {"E360": "permission", "E361": "scope", "E362": "targets"}


def _turned_off() -> Response:
    error = KarniValueError(
        f"Per-user grants are turned off: {grants.SETTING} is False.", code="E364"
    )
    return Response({"code": "E364", "detail": str(error)}, status=status.HTTP_404_NOT_FOUND)


def _refused(exc: KarniValueError) -> Response:
    """A coded refusal as a response: 403 with ``reasons`` for ``E363``, else a 400."""
    body: dict[str, Any] = {"code": exc.code, "detail": str(exc)}
    if isinstance(exc, grants.GrantRefused):
        body["reasons"] = exc.reasons
        return Response(body, status=status.HTTP_403_FORBIDDEN)
    body["field"] = _FIELDS.get(str(exc.code), "permission")
    return Response(body, status=status.HTTP_400_BAD_REQUEST)


class UserGrantPermission(BasePermission):
    """``usergrant:view`` to read, ``:add`` to post, ``:change`` to patch, ``:delete`` to delete."""

    message = "This endpoint requires the permission to view or change user grants."

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        action = "view" if request.method in SAFE_METHODS else _ACTIONS.get(str(request.method))
        return action is not None and user_can(user, f"{grants.GRANT_PERMISSION}:{action}")


class UserGrantSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    """One grant. ``user`` is set once, ``granted_by`` and ``active`` are read-only."""

    targets = serializers.ListField(child=serializers.CharField(), required=False)
    active = serializers.BooleanField(source="is_live", read_only=True)

    class Meta:
        model = UserGrant
        fields: ClassVar[list[str]] = [
            "id",
            "user",
            "permission",
            "scope",
            "targets",
            "expires_at",
            "reason",
            "granted_by",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields: ClassVar[list[str]] = [
            "id",
            "granted_by",
            "active",
            "created_at",
            "updated_at",
        ]

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        if self.instance is not None and "user" in fields:
            fields["user"].read_only = True
        return fields


class BulkGrantSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The ``bulk/`` body: one pattern and scope for every user listed (at most 1000)."""

    users = serializers.PrimaryKeyRelatedField(
        many=True, queryset=get_user_model()._default_manager.all()
    )
    permission = serializers.CharField()
    scope = serializers.CharField(default="all")
    targets = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)

    def validate_users(self, value: list[Any]) -> list[Any]:
        if not value:
            raise serializers.ValidationError("List at least one user.")
        if len(value) > BULK_LIMIT:
            raise serializers.ValidationError(f"List at most {BULK_LIMIT} users per request.")
        return list({user.pk: user for user in value}.values())


def _visible(request: Request, action: str = "view") -> QuerySet[UserGrant]:
    """The grants the requester's ``usergrant:<action>`` scope reaches."""
    queryset = UserGrant.objects.select_related("user", "granted_by")
    return apply_rows(queryset, rows_for(request.user, UserGrant, action))


def _truthy(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes"):
        return True
    if lowered in ("0", "false", "no"):
        return False
    return None


class UserGrantListView(generics.ListCreateAPIView):  # type: ignore[type-arg]
    """``GET``/``POST permissions/grants/``: the grants the requester may view, and a new one."""

    permission_classes: ClassVar[list[type]] = [UserGrantPermission]
    serializer_class = UserGrantSerializer

    def get_queryset(self) -> QuerySet[UserGrant]:
        queryset = _visible(self.request)
        params = self.request.query_params
        if params.get("user"):
            queryset = queryset.filter(user__pk=params["user"])
        if params.get("permission"):
            queryset = queryset.filter(permission=params["permission"])
        active = _truthy(params.get("active", ""))
        if active is True:
            queryset = queryset.live()
        elif active is False:
            queryset = queryset.expired()
        return queryset.order_by("-created_at", "pk")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not grants.enabled():
            return _turned_off()
        try:
            return super().list(request, *args, **kwargs)
        except (ValueError, TypeError, DjangoValidationError):  # a malformed ?user= id
            return Response({"user": ["Not a valid id."]}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not grants.enabled():
            return _turned_off()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            row = grants.grant(
                request.user,
                data["user"],
                data["permission"],
                data.get("scope", "all"),
                targets=data.get("targets", []),
                expires_at=data.get("expires_at"),
                reason=data.get("reason", ""),
            )
        except KarniValueError as exc:
            return _refused(exc)
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)


class UserGrantDetailView(generics.RetrieveUpdateDestroyAPIView):  # type: ignore[type-arg]
    """``GET``/``PATCH``/``DELETE permissions/grants/<id>/``: one grant, a change, a revoke.

    A grant outside the requester's view scope is a 404, one they may read
    but not change or delete a 403.
    """

    permission_classes: ClassVar[list[type]] = [UserGrantPermission]
    serializer_class = UserGrantSerializer
    http_method_names: ClassVar[list[str]] = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[UserGrant]:
        return _visible(self.request)

    def get_object(self) -> UserGrant:
        row: UserGrant = super().get_object()
        action = _ACTIONS.get(str(self.request.method))
        if action is not None and not user_can(
            self.request.user, f"{grants.GRANT_PERMISSION}:{action}", row
        ):
            raise PermissionDenied(f"Your {action} scope on user grants does not reach this one.")
        return row

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        self._off = not grants.enabled()

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _turned_off() if self._off else super().retrieve(request, *args, **kwargs)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if self._off:
            return _turned_off()
        row = self.get_object()
        serializer = self.get_serializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = {
            name: value
            for name, value in serializer.validated_data.items()
            if name in grants.CHANGEABLE
        }
        try:
            grants.change(request.user, row, **fields)
        except KarniValueError as exc:
            return _refused(exc)
        return Response(self.get_serializer(row).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if self._off:
            return _turned_off()
        grants.revoke(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=BulkGrantSerializer, responses={201: UserGrantSerializer(many=True)})
class UserGrantBulkView(APIView):
    """``POST permissions/grants/bulk/``: one pattern and scope to many users, all or none."""

    permission_classes: ClassVar[list[type]] = [UserGrantPermission]
    serializer_class = BulkGrantSerializer

    def post(self, request: Request) -> Response:
        if not grants.enabled():
            return _turned_off()
        serializer = BulkGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            rows = grants.bulk_grant(
                request.user,
                data["users"],
                data["permission"],
                data["scope"],
                targets=data["targets"],
                expires_at=data["expires_at"],
                reason=data["reason"],
            )
        except KarniValueError as exc:
            return _refused(exc)
        return Response(UserGrantSerializer(rows, many=True).data, status=status.HTTP_201_CREATED)
