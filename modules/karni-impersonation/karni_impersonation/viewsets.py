"""The impersonation API — auto-registered at ``/api/impersonation-sessions/``.

* ``GET /impersonation-sessions/`` lists the session records (``view`` grant:
  for auditors; makers of a session also see their own through an ``own``
  grant on ``actor``… the record's owner field is ``actor``).
* ``POST …/start/`` ``{"user": <id or email>, "reason": "..."}`` — gated on
  the explicit ``impersonate`` permission. In JWT mode the answer carries
  tokens for the target (bounded by the session's limit); in session mode
  the Django session now acts as the target.
* ``POST …/stop/`` — ends the current impersonated session; in JWT mode the
  answer carries fresh tokens for the impersonator.
* ``GET …/current/`` — the session this request belongs to, or ``null``
  (what the banner reads).
"""

from __future__ import annotations

from typing import Any, cast

from karni.api import Access, Authenticated, BaseViewSet, Budget, Can, Granted, Owned
from karni.exceptions import api_error
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from karni_impersonation import services
from karni_impersonation.api import SessionSerializer, StartSerializer, StopSerializer
from karni_impersonation.middleware import current_session
from karni_impersonation.models import ImpersonationSession

__all__ = ["ImpersonationSessionViewSet"]

_START = Can(services.PERMISSION)


def _jwt_mode() -> bool:
    from karni.accounts.api.views import auth_mode

    return auth_mode() == "jwt"


class ImpersonationSessionViewSet(BaseViewSet):
    model = ImpersonationSession
    access = Access(read=Granted() | Owned("actor"), write=Granted())
    serializer_class = SessionSerializer
    filterset_fields = ["actor", "target", "end_reason"]
    select_related = ["actor", "target"]
    query_budget = Budget(
        start=30, stop=20, reason="a start writes the record, its batch and history"
    )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("POST", detail="Start an impersonation with start/.")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT", detail="Session records are not edited.")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("DELETE", detail="Session records are kept for the audit trail.")

    @action(detail=False, methods=["post"], url_path="start", access=_START)
    def start(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Begin acting as another user (the explicit permission, no escalation, a reason)."""
        if current_session(request) is not None:
            raise PermissionDenied(detail="IMP004: stop the current impersonation first.")
        body = StartSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        target = services.find_user(body.validated_data["user"])
        if target is None:
            raise NotFound("No such user.")
        try:
            session = services.start(request.user, target, body.validated_data["reason"], request)
        except services.ImpersonationError as exc:
            if exc.code in ("IMP001", "IMP002"):
                raise PermissionDenied(detail=str(exc), code=exc.code) from exc
            raise api_error(exc.code or "IMP004", str(exc)) from exc
        payload: dict[str, Any] = {
            "session": SessionSerializer(session, context=self.get_serializer_context()).data
        }
        if _jwt_mode():
            from karni_impersonation.tokens import issue_for_session

            payload.update(issue_for_session(session))
        else:
            services.attach(request, session)
        return Response(payload, status=201)

    @action(detail=False, methods=["post"], url_path="stop", access=Authenticated())
    def stop(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """End the impersonated session this request belongs to."""
        session = current_session(request)
        if session is None:
            raise api_error("IMP005", "This request is not part of an impersonated session.")
        body = StopSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.stop(session, services.STOPPED)
        services.detach(request)
        payload: dict[str, Any] = {
            "session": SessionSerializer(session, context=self.get_serializer_context()).data
        }
        if _jwt_mode():
            from rest_framework_simplejwt.exceptions import TokenError
            from rest_framework_simplejwt.tokens import RefreshToken

            from karni_impersonation.tokens import issue_for_actor

            raw = body.validated_data.get("refresh") or ""
            if raw:
                try:
                    RefreshToken(cast(Any, raw)).blacklist()
                except TokenError:
                    pass
            payload.update(issue_for_actor(session.actor))
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="current", access=Authenticated())
    def current(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The impersonated session this request belongs to, or ``{"session": null}``."""
        session = current_session(request)
        if session is None:
            return Response({"session": None})
        return Response(
            {"session": SessionSerializer(session, context=self.get_serializer_context()).data}
        )
