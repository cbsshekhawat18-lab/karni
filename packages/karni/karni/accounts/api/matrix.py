"""The permission matrix and effective permissions as an API (ADR 0002, P5).

The same four functions the admin page uses (:mod:`karni.accounts.matrix`),
so a project can build its own screen, seed the matrix in fixtures and assert
it in tests:

* ``GET permissions/matrix/`` — roles, models (with the scopes each may
  take) and every cell;
* ``POST permissions/matrix/`` — ``{"changes": [{"role", "permission",
  "scope"}], "dry_run": false}``; ``scope`` is a scope value, ``null`` to
  revoke or ``"declared"`` to hand the cell back to ``KARNI_ROLES``. The
  answer is the plan (changes and refusals); a refused request is a 400
  with code ``E213`` and nothing written; ``dry_run`` returns the plan
  without writing — the confirmation diff for a custom UI;
* ``GET permissions/effective/`` — the requester's own effective
  permissions; ``permissions/effective/<user id>/`` anyone else's.

Gated on the grants: ``karni_accounts.rolepermission:view`` to read the
matrix or someone else's effective permissions, ``:change`` to post.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.accounts.matrix import (
    MATRIX_PERMISSION,
    MatrixRefused,
    apply_changes,
    build_matrix,
    effective_permissions,
    plan_changes,
)
from karni.accounts.roles import user_can

__all__ = [
    "EffectivePermissionsView",
    "MatrixChangeSerializer",
    "MatrixChangesSerializer",
    "MatrixPermission",
    "PermissionMatrixView",
]


class MatrixChangeSerializer(serializers.Serializer):
    """One requested cell: ``scope`` is a value, ``null`` (revoke) or ``"declared"``."""

    role = serializers.CharField()
    permission = serializers.CharField()
    scope = serializers.CharField(allow_null=True)


class MatrixChangesSerializer(serializers.Serializer):
    """The ``POST`` body: the cells to change and whether to only plan."""

    changes = MatrixChangeSerializer(many=True)
    dry_run = serializers.BooleanField(default=False)


class MatrixPermission(BasePermission):
    """``rolepermission:view`` for safe methods, ``rolepermission:change`` otherwise."""

    message = "This endpoint requires the permission to view or change role permissions."

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        action = "view" if request.method in SAFE_METHODS else "change"
        return user_can(user, f"{MATRIX_PERMISSION}:{action}")


class PermissionMatrixView(APIView):
    """``GET``/``POST permissions/matrix/`` — the matrix, and changes to it."""

    permission_classes: ClassVar[list[type]] = [MatrixPermission]
    serializer_class = MatrixChangesSerializer

    def get(self, request: Request) -> Response:
        return Response(build_matrix().to_dict())

    def post(self, request: Request) -> Response:
        serializer = MatrixChangesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = [
            (change["role"], change["permission"], change["scope"])
            for change in serializer.validated_data["changes"]
        ]
        if serializer.validated_data["dry_run"]:
            return Response(plan_changes(request.user, requested).to_dict())
        try:
            plan = apply_changes(request.user, requested)
        except MatrixRefused as exc:
            return Response(
                {"code": "E213", "detail": str(exc), **exc.plan.to_dict()},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(plan.to_dict())


@extend_schema(responses={200: OpenApiTypes.OBJECT})
class EffectivePermissionsView(APIView):
    """``GET permissions/effective/[<user id>/]`` — what a user may do, and why."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request: Request, user_id: str | None = None) -> Response:
        target = request.user
        if user_id is not None and str(user_id) != str(target.pk):
            if not user_can(request.user, f"{MATRIX_PERMISSION}:view"):
                raise PermissionDenied(
                    detail="Viewing another user's effective permissions requires "
                    f"{MATRIX_PERMISSION}:view."
                )
            try:
                target = get_user_model()._default_manager.filter(pk=user_id).first()
            except (ValueError, DjangoValidationError):
                target = None
            if target is None:
                raise NotFound
        return Response(effective_permissions(target).to_dict())
