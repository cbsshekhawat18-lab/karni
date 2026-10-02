"""Plain Django views for the audit-population tests in ``tests/test_model_layer.py``.

Deliberately *not* DRF: these prove ``CurrentUserMiddleware`` stamps
``created_by`` / ``updated_by`` from the user ``AuthenticationMiddleware``
attached to the request, through the full middleware stack, under both the
WSGI (sync view) and ASGI (async view) handlers. The DRF/JWT path is covered
through the real auto-routed ``/api/events/`` endpoint instead.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from tests.testapp.models import Venue


def create_venue(request: HttpRequest) -> JsonResponse:
    """Sync view: ``POST name=…`` creates a ``Venue`` (any ``AuditedModel``)."""
    venue = Venue.objects.create(name=request.POST["name"], city="sync")
    return JsonResponse({"id": str(venue.pk)}, status=201)


async def acreate_venue(request: HttpRequest) -> JsonResponse:
    """Async view: the same, through the ORM's async API (``acreate``)."""
    venue = await Venue.objects.acreate(name=request.POST["name"], city="async")
    return JsonResponse({"id": str(venue.pk)}, status=201)
