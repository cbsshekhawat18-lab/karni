"""The pending-changes API — auto-registered at ``/api/pending-changes/``.

A read-only resource (``create``/``update``/``destroy`` answer 405) gated by
the roles' grants on ``karni_approvals.pendingchange`` (``Granted()``):
``view`` to list, ``approve`` / ``reject`` for the two detail actions —
"a checker holding the approve permission". The list is narrowed to the
pending changes whose row the requester may view (``services.visible_to``)
on top of the grant's own row scope, so a branch checker sees their branch
and a maker (``own``) their own proposals. ``count/`` is the badge.

Override / escape hatch: subclass and redeclare ``access``, override the
actions, or set ``auto_register = False`` and register your own.
"""

from __future__ import annotations

from typing import Any

from karni.api import BaseViewSet, Budget, Granted
from karni.exceptions import api_error
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from karni_approvals import services
from karni_approvals.api import DecideSerializer, PendingChangeSerializer
from karni_approvals.models import PendingChange

__all__ = ["PendingChangeViewSet"]

_FORBIDDEN = {"APR002", "APR003"}


class PendingChangeViewSet(BaseViewSet):
    model = PendingChange
    access = Granted()
    serializer_class = PendingChangeSerializer
    filterset_fields = ["status", "action", "content_type", "maker"]
    select_related = ["content_type", "maker", "resolved_by"]
    prefetch_related = ["decisions", "decisions__checker"]
    # A decision writes the decision, the pending change, the row it applies and
    # their audit entries, then renders the result: more than a read ever needs.
    query_budget = Budget(
        approve=40, reject=25, reason="a decision writes several rows and their history"
    )

    def get_queryset(self) -> Any:
        return services.visible_to(self.request.user, PendingChange.objects.all())

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(
            "POST", detail="Pending changes are proposed by changing a guarded row."
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT", detail="Decide with approve/ or reject/.")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("DELETE", detail="Reject a pending change instead of deleting it.")

    def _decide(self, request: Request, verdict: str) -> Response:
        pending = self.get_object()
        body = DecideSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            decided = services.decide(pending, request.user, verdict, body.validated_data["reason"])
        except services.ApprovalError as exc:
            if exc.code in _FORBIDDEN:
                raise PermissionDenied(detail=str(exc), code=exc.code) from exc
            raise api_error(exc.code or "APR005", str(exc)) from exc
        fresh = self.get_queryset().get(pk=decided.pk)  # with the viewset's select/prefetch
        return Response(PendingChangeSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """``POST /pending-changes/<id>/approve/`` with ``{"reason": ...}``."""
        return self._decide(request, "approve")

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """``POST /pending-changes/<id>/reject/`` with ``{"reason": ...}``."""
        return self._decide(request, "reject")

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """``GET /pending-changes/count/``: how many the requester may decide (the badge)."""
        return Response({"pending": services.pending_count(request.user)})
