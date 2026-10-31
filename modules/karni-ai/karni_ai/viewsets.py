"""The AI API, auto-registered at ``/api/ai/``.

* ``POST /api/ai/extract/`` with ``resource`` (a router prefix such as
  ``products``) and one of ``text``, ``url`` or ``file`` (a PDF) answers the
  import preview of the rows a language model read from the source: the
  proposed rows, a problem per field, the counts and the import job's id. It
  writes nothing to the resource. ``POST /api/<resource>/import/<id>/commit/``
  saves the rows once the user confirms. Only a signed-in user the resource's
  ``access`` lets create may call it, at most ``30/hour`` each (the
  ``ai.extract`` throttle scope).
* ``GET /api/ai/`` lists the caller's own provider calls (tokens, cost),
  read-only. The admin shows everyone's.

Override / escape hatch: ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["ai.extract"]``
sets the rate (``None`` turns it off), ``KARNI_AI_EXTRACTOR`` swaps the class
that runs an extraction.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from karni.api import Access, Authenticated, BaseViewSet, Owned, Throttle
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from karni_ai.exceptions import ExtractionRefused, ProviderError
from karni_ai.extraction import get_extractor
from karni_ai.models import AICall
from karni_ai.serializers import ExtractSerializer

__all__ = ["AICallViewSet"]


def _refused(code: str, detail: str, status: int) -> Response:
    return Response({"code": code, "detail": detail}, status=status)


class AICallViewSet(BaseViewSet):
    """Experimental. The usage log, each user reading their own calls, and the extract action."""

    model = AICall
    route = "ai"
    access = Access(read=Owned("user"), write=Owned("user"))
    throttle = Throttle(extract="30/hour")
    #: The extraction previews every proposed row, so its queries grow with the rows,
    #: like the import's own actions: unbudgeted.
    unbudgeted_actions = BaseViewSet.unbudgeted_actions | {"extract"}

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("POST", detail="Calls are logged by extract/, never posted.")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT", detail="The usage log is read-only.")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("DELETE", detail="The usage log is read-only.")

    @extend_schema(
        request={
            "multipart/form-data": ExtractSerializer,
            "application/json": ExtractSerializer,
        },
        responses={201: OpenApiTypes.OBJECT},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="extract",
        access=Authenticated(),
        parser_classes=[JSONParser, MultiPartParser, FormParser],
    )
    def extract(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Experimental. Rows of a resource read from a source, as the import's preview."""
        body = ExtractSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            extraction = get_extractor(request).run(
                data["resource"],
                text=data.get("text") or None,
                url=data.get("url") or None,
                file=data.get("file"),
            )
        except ExtractionRefused as exc:
            return _refused(exc.code, exc.message, exc.status)
        except ProviderError as exc:
            return _refused(exc.code, exc.message, exc.status)
        return Response(extraction.to_dict(request), status=201)
