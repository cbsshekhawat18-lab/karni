"""crm API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`.

Leads get the pipeline actions of the original module on top of the CRUD,
filtering, search, export and import every BaseViewSet carries:
`assign`, `status`, `activity`, `convert`, `timeline`, `bulk-assign` and
`score`. `?tag=` narrows by one tag (a JSON list has no derived filter).
"""

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import get_user_model
from django.db import connection
from karni.api import BaseViewSet, Budget, Can, Granted
from rest_framework.decorators import action
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from crm import services
from crm.models import Contact, Lead, LeadActivity, Workspace

WRITE = Can("crm.lead:change")
READ = Can("crm.lead:view")


class WorkspaceViewSet(BaseViewSet):
    model = Workspace
    access = Granted()


class ContactViewSet(BaseViewSet):
    model = Contact
    access = Granted()
    search_fields = ("name", "phone", "email")


class LeadViewSet(BaseViewSet):
    model = Lead
    access = Granted()
    search_fields = ("name", "phone", "email", "interest", "notes")
    expandable_fields = {
        "workspace": "workspace",
        "contact": "contact",
        "assigned_to": "assigned_to",
        "activities": "activities",
    }
    query_budget = Budget(bulk_assign=None, reason="one activity row per assigned lead")

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        tag = self.request.query_params.get("tag")
        if not tag:
            return queryset
        if connection.vendor == "postgresql":  # JSON containment: exact membership
            return queryset.filter(tags__contains=[tag])
        return queryset.filter(tags__icontains=json.dumps(tag))  # sqlite: text search

    @action(detail=True, methods=["post"], access=WRITE)
    def assign(self, request: Request, pk: Any = None) -> Response:
        lead = self.get_object()
        user = _user_or_none(request.data.get("user_id"))
        return Response(self.get_serializer(services.assign(lead, request.user, user)).data)

    @action(detail=True, methods=["post", "put"], access=WRITE)
    def status(self, request: Request, pk: Any = None) -> Response:
        lead = self.get_object()
        new = request.data.get("status")
        if new not in Lead.Status.values:
            raise ValidationError({"status": f"one of {sorted(Lead.Status.values)}"})
        notes = str(request.data.get("notes") or "").strip()
        return Response(self.get_serializer(services.set_status(lead, request.user, new, notes)).data)

    @action(detail=True, methods=["post"], access=WRITE)
    def activity(self, request: Request, pk: Any = None) -> Response:
        lead = self.get_object()
        kind = request.data.get("activity_type") or "note"
        if kind not in LeadActivity.ActivityType.values:
            raise ValidationError({"activity_type": f"one of {sorted(LeadActivity.ActivityType.values)}"})
        row = services.record(
            lead, request.user, kind, str(request.data.get("content") or "").strip(),
            **(request.data.get("metadata") or {}),
        )
        return Response({"id": row.pk, "activity_type": row.activity_type, "content": row.content}, status=201)

    @action(detail=True, methods=["post"], access=WRITE)
    def convert(self, request: Request, pk: Any = None) -> Response:
        lead = self.get_object()
        try:
            value = Decimal(str(request.data.get("conversion_value") or 0))
        except InvalidOperation as exc:
            raise ValidationError({"conversion_value": "a number"}) from exc
        return Response(self.get_serializer(services.convert(lead, request.user, value)).data)

    @action(detail=True, methods=["get"], access=READ)
    def timeline(self, request: Request, pk: Any = None) -> Response:
        lead = self.get_object()
        activities = [
            {
                "id": row.pk, "activity_type": row.activity_type, "content": row.content,
                "metadata": row.metadata, "actor": row.actor_id,
                "actor_email": getattr(row.actor, "email", "") if row.actor_id else "",
                "created_at": row.created_at.isoformat(),
            }
            for row in lead.activities.select_related("actor")
        ]
        return Response({"activities": activities, "bot_steps": []})

    @action(detail=False, methods=["post"], url_path="bulk-assign", access=WRITE)
    def bulk_assign(self, request: Request) -> Response:
        ids = request.data.get("lead_ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"lead_ids": "a non-empty list"})
        user = _user_or_none(request.data.get("user_id"))
        updated = 0
        for lead in self.filter_queryset(self.get_queryset()).filter(pk__in=ids):
            services.assign(lead, request.user, user)
            updated += 1
        return Response({"updated": updated})

    @action(detail=True, methods=["post"], url_path="score-with-ai", access=WRITE)
    def score(self, request: Request, pk: Any = None) -> Response:
        lead = services.apply_score(self.get_object(), request.user)
        return Response({"quality_score": lead.quality_score, "quality_reason": lead.quality_reason})


class LeadActivityViewSet(BaseViewSet):
    model = LeadActivity
    access = Granted()


def _user_or_none(value: Any) -> Any | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return get_user_model().objects.get(pk=value)
    except (get_user_model().DoesNotExist, TypeError, ValueError, DjangoValidationError) as exc:
        raise ValidationError({"user_id": "an existing user"}) from exc
