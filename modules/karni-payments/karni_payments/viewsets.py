"""Payments viewsets — auto-registered on Karni's API router.

``PaymentViewSet`` rides the auto-router at ``/api/payments/`` and
``RefundViewSet`` at ``/api/refunds/`` (this module is named ``viewsets.py``
because that is where :meth:`karni.api.routers.KarniRouter.autodiscover`
looks). Per amendment G1:

* both are **read-only**: ``create``/``update``/``partial_update``/
  ``destroy`` raise ``MethodNotAllowed`` (no ``http_method_names`` games);
* payments are never anonymously readable (``IsAuthenticated``);
* lists/details are owner-scoped via ``filter_queryset_for_user`` — holders
  of the ``payments-admin`` role bypass the scoping;
* ``checkout`` is a ``detail=False`` action, ``refund`` a ``detail=True``
  action gated on the ``payments-admin`` role, both with explicit
  input/output serializers and ``@extend_schema`` (the schema drives
  @karni/ui's typed hooks).

Override / escape hatches: all the standard Karni/DRF ones — subclass and
override ``permission_classes`` / ``filter_queryset_for_user`` / the
actions; swap the role name by overriding ``admin_role``; set
``auto_register = False`` on a subclass and register your own.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from karni.accounts.permissions import RolePermission, has_role
from karni.api import BaseViewSet
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from karni_payments import services
from karni_payments.api import (
    CheckoutInputSerializer,
    CheckoutOutputSerializer,
    RefundInputSerializer,
    RefundSerializer,
)
from karni_payments.models import Payment, Refund

__all__ = ["PAYMENTS_ADMIN_ROLE", "PaymentViewSet", "RefundViewSet"]

PAYMENTS_ADMIN_ROLE = "payments-admin"
"""Role (Django auth group) granting refund rights and unscoped reads."""


class _ReadOnlyModelMixin:
    """Raise ``MethodNotAllowed`` for every write verb (amendment G1).

    Explicit overrides — not ``http_method_names`` — so extra ``@action``
    POST routes (checkout, refund) keep working while the stock write
    routes answer 405.
    """

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "POST")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT")

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PATCH")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "DELETE")


class PaymentViewSet(_ReadOnlyModelMixin, BaseViewSet):
    """Owner-scoped, read-only payments plus the checkout/refund actions."""

    model = Payment
    permission_classes = [IsAuthenticated]
    admin_role: ClassVar[str] = PAYMENTS_ADMIN_ROLE

    def filter_queryset_for_user(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Owner scoping with a ``payments-admin`` bypass (amendment G1).

        The pattern for role-gated detail actions × owner scoping: admins
        must reach *any* payment (the refund action calls ``get_object()``,
        which runs through this filter), everyone else only their own.
        """
        user = self.request.user
        if not user.is_authenticated:
            return queryset.none()
        if has_role(user, self.admin_role):
            return queryset
        return queryset.filter(user=user)

    @extend_schema(
        request=CheckoutInputSerializer,
        responses={201: CheckoutOutputSerializer},
        description=(
            "Create a pending payment and a provider checkout session; "
            "redirect the customer to `url`. Amounts are validated "
            "server-side by KARNI_PAYMENTS_CHECKOUT_VALIDATOR."
        ),
    )
    @action(detail=False, methods=["post"])
    def checkout(self, request: Request) -> Response:
        """``POST /api/payments/checkout/`` → ``services.create_checkout``."""
        serializer = CheckoutInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment, session = services.create_checkout(request.user, **serializer.validated_data)
        output = CheckoutOutputSerializer(
            {"payment_id": payment.pk, "session_id": session.id, "url": session.url}
        )
        return Response(output.data, status=201)

    @extend_schema(
        request=RefundInputSerializer,
        responses={201: RefundSerializer},
        description=(
            "Refund this payment (omit `amount` for the full unrefunded "
            "remainder). Requires the payments-admin role."
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[RolePermission.for_roles(PAYMENTS_ADMIN_ROLE)],
    )
    def refund(self, request: Request, pk: str | None = None) -> Response:
        """``POST /api/payments/{id}/refund/`` → ``services.create_refund``."""
        payment = self.get_object()
        serializer = RefundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = services.create_refund(
            payment,
            serializer.validated_data.get("amount"),
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(RefundSerializer(refund).data, status=201)


class RefundViewSet(_ReadOnlyModelMixin, BaseViewSet):
    """Read-only refunds, gated on the ``payments-admin`` role.

    Override / escape hatch: to let customers list their own refunds,
    subclass with ``permission_classes = [IsAuthenticated]`` and an
    owner-scoping ``filter_queryset_for_user`` over ``payment__user``.
    """

    model = Refund
    permission_classes = [RolePermission.for_roles(PAYMENTS_ADMIN_ROLE)]
    admin_role: ClassVar[str] = PAYMENTS_ADMIN_ROLE

    def filter_queryset_for_user(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Defence in depth: even with permissions swapped, non-admins see nothing."""
        user = self.request.user
        if user.is_authenticated and has_role(user, self.admin_role):
            return queryset
        return queryset.none()
