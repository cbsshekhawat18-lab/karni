"""Payments viewsets — auto-registered on Karni's API router.

``PaymentViewSet`` rides the auto-router at ``/api/payments/`` and
``RefundViewSet`` at ``/api/refunds/`` (this module is named ``viewsets.py``
because that is where :meth:`karni.api.routers.KarniRouter.autodiscover`
looks). Per amendment G1:

* both are **read-only**: ``create``/``update``/``partial_update``/
  ``destroy`` raise ``MethodNotAllowed`` (no ``http_method_names`` games);
* access is one declaration per viewset (ADR 0001 Decision 2): payments are
  never anonymously readable, lists/details are owner-scoped, and holders of
  the ``payments-admin`` role bypass the owner scope
  (``read=Owned("user") | HasRole("payments-admin")``);
* ``checkout`` is a ``detail=False`` action (it inherits ``write``: any
  authenticated user, for their own payment), ``refund`` a ``detail=True``
  action gated on the ``payments-admin`` role with ``@action(access=...)``;
  both have explicit input/output serializers and ``@extend_schema`` (the
  schema drives @karni/ui's typed hooks).

Override / escape hatches: all the standard Karni/DRF ones — subclass and
redeclare ``access`` (e.g. to use another role name), override the actions;
set ``auto_register = False`` on a subclass and register your own.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from karni.api import Access, BaseViewSet, HasRole, Owned
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
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

_PAYMENTS_ADMIN = HasRole(PAYMENTS_ADMIN_ROLE)


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
    # Role-gated detail actions × owner scoping: the admin role must be in
    # `read`, because the refund action's get_object() looks the payment up
    # through the read scope. `user` (the owner) is read-only in the
    # generated serializer; checkout stamps it server-side.
    access = Access(read=Owned("user") | _PAYMENTS_ADMIN, write=Owned("user"))

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
    @action(detail=True, methods=["post"], access=_PAYMENTS_ADMIN)
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

    ``HasRole`` is both the request gate (non-admins get 403) and the row
    policy (non-admins would see no rows even if the gate were swapped).

    Override / escape hatch: to let customers list their own refunds,
    subclass with ``access = Access(read=Owned("payment__user") |
    HasRole("payments-admin"), write=HasRole("payments-admin"))``.
    """

    model = Refund
    access = Access(read=_PAYMENTS_ADMIN, write=_PAYMENTS_ADMIN)
