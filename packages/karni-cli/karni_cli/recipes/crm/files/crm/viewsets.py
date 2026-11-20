"""crm API. Each viewset extends the one karni build writes in crm/karni/api.py from
karni.yaml: add your actions here.
"""

import datetime as dt
from typing import Any

from crm.karni import api as karni
from django.db.models import Count, Sum
from django.utils import timezone
from karni import preferences
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response


#: The stages a deal is still being worked in.
OPEN_STAGES = ("lead", "qualified", "proposal")


class CompanyViewSet(karni.CompanyViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ContactViewSet(karni.ContactViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class DealViewSet(karni.DealViewSet):
    """Deals, the pipeline (what each stage holds) and the stale deals."""

    @action(detail=False)
    def pipeline(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The number and value of the deals this user may see, per stage."""
        deals = self.filter_queryset(self.get_queryset()).order_by("stage")
        rows = deals.values("stage").annotate(deals=Count("id"), value=Sum("value"))
        return Response(
            [
                {"stage": r["stage"], "deals": r["deals"], "value": f"{r['value']:.2f}"}
                for r in rows
            ]
        )

    @action(detail=False)
    def stale(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Open deals nobody changed for Settings, CRM, stale_after_days days."""
        days = preferences.value("crm.stale_after_days", 30)
        since = timezone.now() - dt.timedelta(days=days)
        deals = self.filter_queryset(self.get_queryset()).filter(
            stage__in=OPEN_STAGES, updated_at__lt=since
        )
        page = self.paginate_queryset(deals.order_by("updated_at"))
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )
        return Response(self.get_serializer(deals, many=True).data)


class ActivityViewSet(karni.ActivityViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
