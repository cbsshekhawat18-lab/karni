"""crm API. Each viewset extends the one karni build writes in crm/karni/api.py from
karni.yaml: add your actions here.
"""

from decimal import Decimal
from typing import Any

from crm.karni import api as karni
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from karni.accounts.permissions import has_role
from karni.api import Can
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

STAGES = ["lead", "qualified", "proposal", "won", "lost"]


class CompanyViewSet(karni.CompanyViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class ContactViewSet(karni.ContactViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class DealViewSet(karni.DealViewSet):
    """Deals: the owner can be changed by managers and admins, the stage moves, the pipeline."""

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        new_owner = request.data.get("owner")
        response = super().update(request, *args, **kwargs)
        if new_owner and has_role(request.user, "manager", "admin"):
            deal = self.get_object()
            owner = get_user_model().objects.filter(pk=new_owner).first()
            if owner is None:
                raise ValidationError({"owner": ["Unknown user."]})
            deal.owner = owner
            deal.save(update_fields=["owner", "updated_at"])
            response = Response(self.get_serializer(deal).data)
        return response

    @action(detail=True, methods=["post"], access=Can("crm.deal:change"))
    def move(self, request: Request, pk: str | None = None) -> Response:
        """Move the deal to another stage; only the pipeline's steps and lost are allowed."""
        deal = self.get_object()
        stage = request.data.get("stage")
        if stage not in deal.allowed_transitions("stage"):
            raise ValidationError({"stage": [f"A deal cannot move from {deal.stage} to {stage}."]})
        deal.transition("stage", stage)
        return Response(self.get_serializer(deal).data)

    @action(detail=False)
    def pipeline(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The number and value of the deals this user may see, per stage."""
        found = {
            row["stage"]: row
            for row in self.get_queryset()
            .order_by()
            .values("stage")
            .annotate(count=Count("id"), value=Sum("value"))
        }
        return Response(
            [
                {
                    "stage": stage,
                    "count": found.get(stage, {}).get("count", 0),
                    "value": f"{found.get(stage, {}).get('value') or Decimal(0):.2f}",
                }
                for stage in STAGES
            ]
        )
