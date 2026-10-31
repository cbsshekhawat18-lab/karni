"""crm API. Each viewset extends the one karni build writes in crm/karni/api.py from
karni.yaml: add your actions here.
"""

from typing import Any

from django.db.models import Count, Sum
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from crm.karni import api as karni


class CompanyViewSet(karni.CompanyViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ContactViewSet(karni.ContactViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class DealViewSet(karni.DealViewSet):
    """Deals, and the pipeline: what each stage holds."""

    @action(detail=False)
    def pipeline(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The number and value of the deals this user may see, per stage."""
        deals = self.filter_queryset(self.get_queryset()).order_by("stage")
        rows = deals.values("stage").annotate(deals=Count("id"), value=Sum("value"))
        return Response(
            [{"stage": r["stage"], "deals": r["deals"], "value": f"{r['value']:.2f}"} for r in rows]
        )


class ActivityViewSet(karni.ActivityViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
