"""Experimental. ``GET /api/timeline/``: a person's, an organisation's or a record's timeline.

::

    GET /api/timeline/?person=<id>
    GET /api/timeline/?organisation=<id>
    GET /api/timeline/?subject=helpdesk.ticket:<id>
    GET /api/timeline/?person=<id>&kind=helpdesk.ticket.closed,crm.call&limit=20&cursor=...

    {"results": [{"id": "...", "occurred_at": "...", "kind": "helpdesk.ticket.closed",
                  "title": "Ticket closed: Printer jam", "body": "", "source": "helpdesk",
                  "actor": 3, "actor_name": "Ines Duarte", "person": "...", "event": "...",
                  "links": [{"model": "helpdesk.ticket", "id": "...", "resource": "tickets"}],
                  "data": {...}}],
     "next": "<cursor>"}

* **Whose timeline.** ``?person=`` lists the entries about that person,
  ``?organisation=`` and ``?subject=<app_label.model>:<id>`` the entries
  linked to that record. Exactly one of them (400 ``E463`` otherwise). The
  record itself must be one the caller may read, else 404, so the endpoint
  never says whether a record exists.
* **Row scope.** An entry shows only when the caller may read every record
  it is about: its person and each linked record, each through its model's
  own list endpoint for this request (:mod:`karni.timeline.access`). One
  query per model on the page.
* **Paging.** Newest first. ``?limit=`` entries (``KARNI_TIMELINE_PAGE_SIZE``,
  at most ``KARNI_TIMELINE_MAX_PAGE_SIZE``), ``next`` is the cursor of the
  following page (``?cursor=``), or null on the last one. Entries the caller
  may not see are skipped, so a page may hold fewer than ``limit``.
* ``?kind=`` keeps the given kinds (comma-separated), ``?source=`` the given
  parts.

Override / escape hatch: ``KARNI_TIMELINE_API = False`` leaves the route out;
subclass :class:`TimelineView` (``base_queryset``, ``serialize``,
``visibility``) and mount it yourself. ``KARNI_TIMELINE_VISIBILITY`` changes
who reads what.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
from collections.abc import Sequence
from typing import Any, ClassVar, Final

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Prefetch, Q
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.exceptions import KarniValueError
from karni.timeline.access import Visibility, get_visibility
from karni.timeline.models import TimelineEntry, TimelineLink
from karni.timeline.services import clean_id

__all__ = [
    "TimelineEntrySerializer",
    "TimelinePageSerializer",
    "TimelineView",
    "decode_cursor",
    "encode_cursor",
]

#: How many batches one request reads at most to fill a page past hidden entries.
MAX_ROUNDS: Final = 4


class TimelineLinkSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. A record an entry shows on."""

    model = serializers.CharField(help_text="app_label.model")
    id = serializers.CharField()
    resource = serializers.CharField(
        allow_null=True, help_text="The API resource that serves it, for a link, or null."
    )


class TimelineEntrySerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One timeline entry."""

    id = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    kind = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    source = serializers.CharField(allow_blank=True)
    actor = serializers.JSONField(allow_null=True, help_text="The acting user's id, or null.")
    actor_name = serializers.CharField(allow_blank=True)
    person = serializers.CharField(allow_null=True)
    event = serializers.CharField(allow_null=True, help_text="The family event's id, or null.")
    links = TimelineLinkSerializer(many=True)
    data = serializers.DictField(child=serializers.JSONField())


class TimelinePageSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One page of a timeline, newest first."""

    results = TimelineEntrySerializer(many=True)
    next = serializers.CharField(allow_null=True, help_text="The cursor of the next page.")


def encode_cursor(entry: TimelineEntry) -> str:
    """Experimental. The cursor of the page that starts after ``entry``."""
    raw = f"{entry.occurred_at.isoformat()}|{entry.pk}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[dt.datetime, str]:
    """Experimental. ``(occurred_at, id)`` of a cursor (E463 when it is not one)."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, key = base64.urlsafe_b64decode(padded.encode()).decode().split("|", 1)
        moment = dt.datetime.fromisoformat(stamp)
        clean_id(TimelineEntry, key, "cursor")
    except (ValueError, binascii.Error, UnicodeDecodeError, KarniValueError) as exc:
        raise KarniValueError(
            f"karni.timeline: ?cursor={cursor!r} is not a cursor this endpoint gave.",
            code="E463",
        ) from exc
    return moment, key


def _refused(message: str) -> Response:
    return Response({"code": "E463", "detail": message}, status=400)


class TimelineView(APIView):
    """Experimental. ``GET /api/timeline/`` (see the module docstring).

    Open to signed-in callers. What each one sees is what the records'
    own list endpoints show them.
    """

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="timeline_list",
        tags=["timeline"],
        description=(
            "Experimental. The timeline of one person, organisation or record, newest first. "
            "An entry shows only when the caller may read its person and every linked record."
        ),
        parameters=[
            OpenApiParameter("person", OpenApiTypes.STR, description="A person's id."),
            OpenApiParameter("organisation", OpenApiTypes.STR, description="An organisation's id."),
            OpenApiParameter("subject", OpenApiTypes.STR, description="app_label.model:id"),
            OpenApiParameter("kind", OpenApiTypes.STR, description="Kinds, comma-separated."),
            OpenApiParameter("source", OpenApiTypes.STR, description="Parts, comma-separated."),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Entries per page."),
            OpenApiParameter("cursor", OpenApiTypes.STR, description="The previous page's next."),
        ],
        responses={200: TimelinePageSerializer},
    )
    def get(self, request: Request, **kwargs: Any) -> Response:
        try:
            model, key = self.get_subject(request)
            limit = self.get_limit(request)
            cursor = request.query_params.get("cursor")
            after = decode_cursor(cursor) if cursor else None
        except KarniValueError as exc:
            return _refused(exc.message)
        visibility = self.visibility(request)
        if key not in visibility.readable(model, [key]):
            raise Http404("No such record that you may read.")
        queryset = self.base_queryset(request, model, key)
        entries, last = self.page(queryset, visibility, (model, key), limit, after)
        return Response(
            {
                "results": [self.serialize(entry, visibility) for entry in entries],
                "next": encode_cursor(last) if last is not None else None,
            }
        )

    # what to list ---------------------------------------------------------------------

    def get_subject(self, request: Request) -> tuple[type[models.Model], str]:
        """The record whose timeline is asked: ``(model, key as text)``. E463 otherwise."""
        from karni.people.models import Organisation, Person

        given = {
            name: request.query_params.get(name)
            for name in ("person", "organisation", "subject")
            if request.query_params.get(name)
        }
        if len(given) != 1:
            raise KarniValueError(
                "karni.timeline: name exactly one of ?person=<id>, ?organisation=<id> or "
                "?subject=<app_label.model>:<id>.",
                code="E463",
            )
        (name, value), *_ = given.items()
        if name == "person":
            return Person, clean_id(Person, value, "?person=")
        if name == "organisation":
            return Organisation, clean_id(Organisation, value, "?organisation=")
        label, _, raw = str(value).partition(":")
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError) as exc:
            raise KarniValueError(
                f"karni.timeline: ?subject={value!r}. Write <app_label.model>:<id>, for "
                "example helpdesk.ticket:42.",
                code="E463",
            ) from exc
        return model, clean_id(model, raw, "?subject=")

    def get_limit(self, request: Request) -> int:
        """``?limit=`` within 1 and ``KARNI_TIMELINE_MAX_PAGE_SIZE``, else the page size."""
        default = int(getattr(settings, "KARNI_TIMELINE_PAGE_SIZE", 25))
        ceiling = int(getattr(settings, "KARNI_TIMELINE_MAX_PAGE_SIZE", 100))
        raw = request.query_params.get("limit")
        try:
            limit = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, ceiling))

    def base_queryset(
        self, request: Request, model: type[models.Model], key: str
    ) -> models.QuerySet[TimelineEntry]:
        """Every entry of the record's timeline, newest first, before the row scope."""
        from karni.people.models import Person

        queryset = TimelineEntry.objects.all()
        if model is Person:
            queryset = queryset.filter(person_id=key)
        else:
            content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
            queryset = queryset.filter(
                pk__in=TimelineLink.objects.filter(content_type=content_type, object_id=key).values(
                    "entry_id"
                )
            )
        for param, column in (("kind", "kind__in"), ("source", "source__in")):
            wanted = _listed(request.query_params.getlist(param))
            if wanted:
                queryset = queryset.filter(**{column: wanted})
        return queryset.select_related("actor").order_by("-occurred_at", "-id")

    def visibility(self, request: Request) -> Visibility:
        """Who may read what, for this request (``KARNI_TIMELINE_VISIBILITY``)."""
        return get_visibility(request)

    # paging -----------------------------------------------------------------------------

    def page(
        self,
        queryset: models.QuerySet[TimelineEntry],
        visibility: Visibility,
        known: tuple[type[models.Model], str],
        limit: int,
        after: tuple[dt.datetime, str] | None,
    ) -> tuple[list[TimelineEntry], TimelineEntry | None]:
        """The visible entries of one page, and the entry the next page starts after."""
        shown: list[TimelineEntry] = []
        position = after
        for _round in range(MAX_ROUNDS):
            batch = self._batch(queryset, position, limit + 1)
            if not batch:
                return shown, None
            allowed = self._allowed(batch, visibility, known)
            for index, entry in enumerate(batch):
                if entry.pk in allowed:
                    shown.append(entry)
                if len(shown) == limit:
                    more = index + 1 < len(batch) or len(batch) > limit
                    return shown, (entry if more else None)
            if len(batch) <= limit:
                return shown, None
            last = batch[-1]
            position = (last.occurred_at, str(last.pk))
        return shown, batch[-1]

    def _batch(
        self,
        queryset: models.QuerySet[TimelineEntry],
        after: tuple[dt.datetime, str] | None,
        size: int,
    ) -> list[TimelineEntry]:
        if after is not None:
            moment, key = after
            queryset = queryset.filter(
                Q(occurred_at__lt=moment) | Q(occurred_at=moment, id__lt=key)
            )
        links = Prefetch("links", queryset=TimelineLink.objects.order_by("id"))
        return list(queryset.prefetch_related(links)[:size])

    def _allowed(
        self,
        batch: Sequence[TimelineEntry],
        visibility: Visibility,
        known: tuple[type[models.Model], str],
    ) -> set[Any]:
        """The keys of the entries in ``batch`` the caller may read every record of."""
        from karni.people.models import Person

        wanted: dict[type[models.Model] | None, set[str]] = {}
        needs: dict[Any, list[tuple[type[models.Model] | None, str]]] = {}
        for entry in batch:
            records: list[tuple[type[models.Model] | None, str]] = []
            if entry.person_id is not None:
                records.append((Person, str(entry.person_id)))
            for link in entry.links.all():
                content_type = ContentType.objects.get_for_id(link.content_type_id)
                records.append((content_type.model_class(), link.object_id))
            records = [record for record in records if record != known]
            needs[entry.pk] = records
            for model, key in records:
                wanted.setdefault(model, set()).add(key)
        readable = {model: visibility.readable(model, keys) for model, keys in wanted.items()}
        return {
            pk
            for pk, records in needs.items()
            if all(key in readable[model] for model, key in records)
        }

    # output -----------------------------------------------------------------------------

    def serialize(self, entry: TimelineEntry, visibility: Visibility) -> dict[str, Any]:
        """One entry as the API gives it."""
        links = []
        for link in entry.links.all():
            content_type = ContentType.objects.get_for_id(link.content_type_id)
            model = content_type.model_class()
            links.append(
                {
                    "model": f"{content_type.app_label}.{content_type.model}",
                    "id": link.object_id,
                    "resource": visibility.resource(model) if model is not None else None,
                }
            )
        actor = entry.actor
        return {
            "id": str(entry.pk),
            "occurred_at": entry.occurred_at.isoformat(),
            "kind": entry.kind,
            "title": entry.title,
            "body": entry.body,
            "source": entry.source,
            "actor": entry.actor_id,
            "actor_name": _name(actor) if actor is not None else "",
            "person": str(entry.person_id) if entry.person_id is not None else None,
            "event": str(entry.event_id) if entry.event_id is not None else None,
            "links": links,
            "data": entry.data,
        }


def _listed(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        for part in str(value).split(","):
            name = part.strip()
            if name and name not in found:
                found.append(name)
    return found


def _name(user: Any) -> str:
    full = getattr(user, "get_full_name", None)
    text = full() if callable(full) else ""
    if text:
        return str(text)
    username = getattr(user, "get_username", None)
    return str(username() if callable(username) else user)


def build_urlpatterns() -> list[Any]:
    """Experimental. The ``timeline/`` route while ``KARNI_TIMELINE_API`` is on, else ``[]``."""
    from django.urls import path

    if not getattr(settings, "KARNI_TIMELINE_API", True):
        return []
    return [path("timeline/", TimelineView.as_view(), name="karni-timeline")]
