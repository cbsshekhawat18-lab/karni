"""The request side: who is acting, the time limit, the blocked paths, the banner.

Goes after ``AuthenticationMiddleware`` in ``MIDDLEWARE``::

    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "karni_impersonation.middleware.ImpersonationMiddleware",

Per request it resolves the impersonated session — from the Django session
(session auth mode) or from the ``imp`` claim of the bearer token (JWT
mode) — ends it if its time is up, swaps ``request.user`` to the target
(session mode; in JWT mode the token already is the target), refuses the
blocked paths outright, runs the view inside the session's audit batch,
and injects the banner into every HTML page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from karni_impersonation import conf, services
from karni_impersonation.models import ImpersonationSession

__all__ = ["ImpersonationMiddleware"]

_BANNER_TEMPLATE = "karni_impersonation/banner.html"
ENDED_CODE = "IMP005"
BLOCKED_CODE = "IMP006"


class ImpersonationMiddleware:
    """See the module docstring."""

    sync_capable = True
    async_capable = False

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        session, via_django_session, dead_token = self._resolve(request)
        request.impersonation = session
        if dead_token:
            return JsonResponse(
                {"detail": f"{ENDED_CODE}: this impersonation session has ended; sign in again."},
                status=401,
            )
        if session is None:
            return self.get_response(request)
        blocked = services.is_blocked_path(request.path)
        if blocked is not None:
            return JsonResponse(
                {
                    "detail": f"{BLOCKED_CODE}: {request.path} is blocked while impersonating "
                    f"(pattern {blocked!r})."
                },
                status=403,
            )
        if via_django_session:
            request.user = session.target
        with services.impersonating(session):
            response = self.get_response(request)
        if conf.get("KARNI_IMPERSONATION_BANNER"):
            self._inject_banner(request, response, session)
        return response

    # resolution

    def _resolve(self, request: HttpRequest) -> tuple[ImpersonationSession | None, bool, bool]:
        """``(session, carried by the Django session, token of an ended session)``."""
        django_session = getattr(request, "session", None)
        if django_session is not None:
            session_id = django_session.get(services.SESSION_KEY)
            if session_id:
                session = services.active_session(session_id)
                if session is None:
                    django_session.pop(services.SESSION_KEY, None)
                return session, session is not None, False
        header = str(request.META.get("HTTP_AUTHORIZATION", ""))
        if header.startswith("Bearer "):
            from karni_impersonation.tokens import session_id_from_token

            session_id = session_id_from_token(header[len("Bearer ") :].strip())
            if session_id:
                session = services.active_session(session_id)
                return session, False, session is None
        return None, False, False

    # the banner

    def _inject_banner(
        self, request: HttpRequest, response: HttpResponse, session: ImpersonationSession
    ) -> None:
        if getattr(response, "streaming", False) or response.status_code >= 300:
            return
        content_type = str(response.get("Content-Type", ""))
        if not content_type.startswith("text/html"):
            return
        body = response.content
        marker = body.rfind(b"</body>")
        if marker < 0:
            return
        try:
            stop_url: str | None = reverse("karni-impersonation-stop")
        except NoReverseMatch:
            stop_url = None
        remaining = max(int((session.expires_at - timezone.now()).total_seconds() // 60), 0)
        html = render_to_string(
            _BANNER_TEMPLATE,
            {
                "session": session,
                "actor": session.actor,
                "target": session.target,
                "stop_url": stop_url,
                "csrf_token": get_token(request),
                "remaining_minutes": remaining,
                "next": request.get_full_path(),
            },
            request=request,
        )
        response.content = body[:marker] + html.encode("utf-8") + body[marker:]
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))


def current_session(request: Any) -> ImpersonationSession | None:
    """The session the middleware attached to ``request`` (``None`` outside one)."""
    found = getattr(request, "impersonation", None)
    if found is None:
        inner = getattr(request, "_request", None)
        found = getattr(inner, "impersonation", None) if inner is not None else None
    return found
