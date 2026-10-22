"""URLconf for ``tests/test_debug.py``: the API plus views that write, mail, enqueue and crash.

``debug/prices/`` creates an audited ``Price`` (``note`` is ``Karni.sensitive``,
``api_token`` matches the redaction pattern), optionally enqueues
``flaky_mail`` (a task that retries before sending an email) and, with
``explode``, raises with secrets in its locals and its message — what the
secret-scan test needs. ``debug/staff/`` is staff-only (the replay test),
``debug/crash/`` a plain Django view that raises.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tests.testapp.models import Price
from tests.testapp.tasks import flaky_mail


class PriceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        data = request.data
        price = Price.objects.create(
            amount=data.get("amount", "1.00"),
            note=data.get("note", ""),
            api_token=data.get("api_token", ""),
        )
        if data.get("mail_to"):
            flaky_mail.delay(data["mail_to"], int(data.get("fail_times", 1)))
        if data.get("explode"):
            password = data.get("password")
            signing = settings.SECRET_KEY  # a local holding SECRET_KEY under an innocent name
            remembered = price.note  # a sensitive field's value under an innocent name
            context: dict[str, Any] = {"note": price.note, "password": password, "n": 1}
            if context["n"]:
                raise RuntimeError(f"pricing failed for {password} with {signing} {remembered}")
        return Response({"id": str(price.pk)}, status=201)


class StaffView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


def crash(request: HttpRequest) -> HttpResponse:
    total = 0
    return HttpResponse(str(1 / total))


urlpatterns = [
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include("karni.api.urls")),
    path("debug/prices/", PriceView.as_view()),
    path("debug/staff/", StaffView.as_view()),
    path("debug/crash/", crash),
]
