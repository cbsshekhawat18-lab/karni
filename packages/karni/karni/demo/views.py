"""Experimental. What a demo exposes: ``GET /api/demo/`` and the built React app at ``/``.

``GET /api/demo/`` answers, while ``KARNI_DEMO_MODE`` is on (and 404 ``E954`` otherwise)::

    {"enabled": true,
     "accounts": [{"login", "password", "label", "can", "roles"}, ...],
     "reset_hours": 24,
     "next_reset": "2026-11-14T09:00:00Z" | null,
     "admin_url": "/admin/" | null}

Anyone may call it: it is what ``DemoNotice`` in ``@karni/ui`` shows on the sign-in
page, and the demo passwords are public on purpose.

The React app is served by Django, so one service answers everything with no
reverse proxy in front: WhiteNoise (project settings) serves the build's files,
and every path that is not Django's answers the app's ``index.html`` (:func:`app`),
so a reload or a shared link of a deeper page works.

Override / escape hatch: subclass :class:`DemoInfoView` and override :meth:`DemoInfoView.payload`,
then declare your ``path("api/demo/", ...)`` before the include.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.http import HttpRequest, HttpResponse
from django.urls import NoReverseMatch, reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.demo import accounts as demo_accounts
from karni.demo import conf, reset
from karni.exceptions import KarniValueError

__all__ = ["NOT_BUILT", "DemoInfoView", "app", "info", "turned_off"]

NOT_BUILT = (
    "<!doctype html><title>Demo</title><h1>The React app is not built</h1>"
    "<p>Run <code>npm run build</code> in <code>frontend/</code>, or use its dev server.</p>"
)


def info() -> dict[str, Any]:
    """The body of ``GET /api/demo/``: the accounts, the reset period, the next reset."""
    try:
        admin_url: str | None = reverse("admin:index")
    except NoReverseMatch:
        admin_url = None
    following = reset.next_reset()
    return {
        "enabled": True,
        "accounts": [
            {
                "login": account.login,
                "password": account.secret,
                "label": account.label,
                "can": account.can,
                "roles": demo_accounts.wanted_roles(account),
            }
            for account in conf.accounts()
        ],
        "reset_hours": conf.reset_hours(),
        "next_reset": None if following is None else following.isoformat(),
        "admin_url": admin_url,
    }


def turned_off() -> Response:
    """The 404 ``E954`` the route answers while ``KARNI_DEMO_MODE`` is off."""
    error = KarniValueError(
        "Demo mode is turned off: KARNI_DEMO_MODE is not set to True.", code="E954"
    )
    return Response({"code": "E954", "detail": str(error)}, status=status.HTTP_404_NOT_FOUND)


class DemoInfoView(APIView):
    """Experimental. ``GET demo/``: the demo accounts and the reset period, for anyone.

    Override / escape hatch: override :meth:`payload`.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    authentication_classes: ClassVar[list[type]] = []

    def get(self, request: Request, **kwargs: Any) -> Response:
        if not conf.demo_mode():
            return turned_off()
        return Response(self.payload(request))

    def payload(self, request: Request) -> dict[str, Any]:
        """The body: :func:`info`."""
        return info()


def app(request: HttpRequest, path: str = "") -> HttpResponse:
    """The app's page (``KARNI_DEMO_APP_INDEX``), for ``/`` and every deeper path of the app."""
    try:
        html = conf.app_index().read_text(encoding="utf-8")
    except OSError:
        return HttpResponse(NOT_BUILT, status=503)
    response = HttpResponse(html)
    response["Cache-Control"] = "no-cache"  # a new build's scripts on the next visit
    return response
