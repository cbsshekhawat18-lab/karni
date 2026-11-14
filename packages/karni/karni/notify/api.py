"""Experimental. The inbox, a person's own switches and the unsubscribe link, over HTTP.

Every route answers the signed-in person about their own notifications only::

    GET  /api/inbox/?unread=true&kind=commerce.order_paid&limit=20&page=2
         {"count": 42, "unread": 3, "next": 3, "results": [{"id": 7, "kind": "...",
          "title": "Order 1001 is confirmed", "body": "...", "link": "/orders/1001",
          "read": false, "read_at": null, "created_at": "..."}]}
    GET  /api/inbox/unread/                   {"count": 3}
    POST /api/inbox/<id>/read/                the notification, read
    POST /api/inbox/<id>/unread/              the notification, unread again
    POST /api/inbox/read-all/                 {"updated": 3}
    GET  /api/inbox/choices/                  each kind the person may switch, per channel
    PATCH /api/inbox/choices/<kind>/          {"email": false} or {"inbox": false}

and one route needs no sign-in, because the token is the proof::

    GET  /api/notify/unsubscribe/?token=...   what the link unsubscribes (a page in a
                                              browser, JSON otherwise)
    POST /api/notify/unsubscribe/?token=...   unsubscribe (a mail program's one-click
                                              too: List-Unsubscribe-Post)

Override / escape hatch: ``KARNI_NOTIFY_API = False`` leaves the routes out;
subclass the views and mount them yourself with :func:`build_urlpatterns`
(``force=True``).
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.exceptions import KarniValueError
from karni.notify import services
from karni.notify.models import Notification

__all__ = [
    "ChoiceView",
    "ChoicesView",
    "InboxView",
    "MarkAllReadView",
    "MarkView",
    "NotificationSerializer",
    "UnreadView",
    "UnsubscribeView",
    "build_urlpatterns",
]


class NotificationSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One notification in the inbox."""

    id = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    link = serializers.CharField(allow_blank=True)
    read = serializers.BooleanField()
    read_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class InboxPageSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One page of the inbox, newest first."""

    count = serializers.IntegerField(help_text="Notifications that match the filters.")
    unread = serializers.IntegerField(help_text="Unread notifications in the whole inbox.")
    next = serializers.IntegerField(allow_null=True, help_text="The next page, or null.")
    results = NotificationSerializer(many=True)


class ChoiceSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. A kind a person may switch, and where it goes for them now."""

    kind = serializers.CharField()
    title = serializers.CharField()
    describe = serializers.CharField(allow_blank=True)
    audience = serializers.CharField(allow_blank=True)
    marketing = serializers.BooleanField()
    channels = serializers.ListField(child=serializers.CharField())
    email = serializers.BooleanField()
    inbox = serializers.BooleanField()


class ChoiceInputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. A person's switch for one kind: either channel, or both."""

    email = serializers.BooleanField(required=False)
    inbox = serializers.BooleanField(required=False)


def serialize(row: Notification) -> dict[str, Any]:
    """Experimental. One notification as the API gives it."""
    return {
        "id": row.pk,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "link": row.link,
        "read": row.read_at is not None,
        "read_at": row.read_at.isoformat() if row.read_at is not None else None,
        "created_at": row.created_at.isoformat(),
    }


def _truthy(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).lower() in {"1", "true", "yes", "on"}


def _refused(code: str, message: str, status: int = 400) -> Response:
    return Response({"code": code, "detail": message}, status=status)


class InboxView(APIView):
    """Experimental. ``GET /api/inbox/``: the signed-in person's notifications, newest first."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="inbox_list",
        tags=["inbox"],
        description="Experimental. The signed-in person's notifications, newest first.",
        parameters=[
            OpenApiParameter("unread", OpenApiTypes.BOOL, description="Only unread ones."),
            OpenApiParameter("kind", OpenApiTypes.STR, description="Kinds, comma-separated."),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Notifications per page."),
            OpenApiParameter("page", OpenApiTypes.INT, description="The page, from 1."),
        ],
        responses={200: InboxPageSerializer},
    )
    def get(self, request: Request) -> Response:
        rows = self.get_queryset(request)
        unread = _truthy(request.query_params.get("unread"))
        if unread is not None:
            rows = rows.filter(read_at__isnull=unread)
        wanted = [
            name.strip()
            for value in request.query_params.getlist("kind")
            for name in value.split(",")
            if name.strip()
        ]
        if wanted:
            rows = rows.filter(kind__in=wanted)
        pages = Paginator(rows, self.get_limit(request))
        try:
            number = max(int(request.query_params.get("page") or 1), 1)
            page = pages.page(number)
        except (EmptyPage, ValueError):
            return _refused("E444", "karni.notify: ?page= is not a page of this inbox.")
        return Response(
            {
                "count": pages.count,
                "unread": services.unread_count(request.user),
                "next": page.next_page_number() if page.has_next() else None,
                "results": [serialize(row) for row in page.object_list],
            }
        )

    def get_queryset(self, request: Request) -> Any:
        """The caller's own notifications, newest first."""
        return Notification.objects.filter(recipient=request.user).order_by("-created_at", "-id")

    def get_limit(self, request: Request) -> int:
        """``?limit=`` within 1 and ``KARNI_NOTIFY_MAX_PAGE_SIZE``, else the page size."""
        default = int(getattr(settings, "KARNI_NOTIFY_PAGE_SIZE", 25))
        ceiling = int(getattr(settings, "KARNI_NOTIFY_MAX_PAGE_SIZE", 100))
        try:
            limit = int(request.query_params.get("limit") or default)
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, ceiling))


class UnreadView(APIView):
    """Experimental. ``GET /api/inbox/unread/``: how many are unread (the bell's number)."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="inbox_unread",
        tags=["inbox"],
        responses={200: OpenApiTypes.OBJECT},
        description="Experimental. How many of the signed-in person's notifications are unread.",
    )
    def get(self, request: Request) -> Response:
        return Response({"count": services.unread_count(request.user)})


class MarkView(APIView):
    """Experimental. ``POST /api/inbox/<id>/read/`` and ``.../unread/``: one notification."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    read: ClassVar[bool] = True

    @extend_schema(
        operation_id="inbox_mark",
        tags=["inbox"],
        request=None,
        responses={200: NotificationSerializer},
        description="Experimental. Mark one of the caller's notifications read or unread.",
    )
    def post(self, request: Request, pk: int) -> Response:
        row = Notification.objects.filter(recipient=request.user, pk=pk).first()
        if row is None:
            raise Http404("No such notification in your inbox.")
        if self.read:
            services.mark_read(request.user, [row.pk])
        else:
            services.mark_unread(request.user, [row.pk])
        row.refresh_from_db()
        return Response(serialize(row))


class MarkAllReadView(APIView):
    """Experimental. ``POST /api/inbox/read-all/``: every unread notification, read."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="inbox_read_all",
        tags=["inbox"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        description="Experimental. Mark every one of the caller's notifications read.",
    )
    def post(self, request: Request) -> Response:
        return Response({"updated": services.mark_read(request.user)})


class ChoicesView(APIView):
    """Experimental. ``GET /api/inbox/choices/``: the kinds the caller may switch."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="inbox_choices",
        tags=["inbox"],
        responses={200: ChoiceSerializer(many=True)},
        description="Experimental. Each message kind the caller may turn off, per channel.",
    )
    def get(self, request: Request) -> Response:
        # karni: allow(unpaginated-action): the declared kinds, a few dozen at most
        return Response(services.choices(request.user))


class ChoiceView(APIView):
    """Experimental. ``PATCH /api/inbox/choices/<kind>/``: the caller switches one kind."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="inbox_choice_update",
        tags=["inbox"],
        request=ChoiceInputSerializer,
        responses={200: ChoiceSerializer},
        description="Experimental. Turn one kind on or off for the caller, by channel.",
    )
    def patch(self, request: Request, kind: str) -> Response:
        body = ChoiceInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            found = services.choose(
                request.user,
                kind,
                email=body.validated_data.get("email"),
                inbox=body.validated_data.get("inbox"),
            )
        except KarniValueError as exc:
            return _refused(exc.code or "E441", exc.message)
        return Response(found)


@method_decorator(csrf_exempt, name="dispatch")
class UnsubscribeView(View):
    """Experimental. ``/api/notify/unsubscribe/?token=``: leave a marketing kind, no sign-in.

    ``GET`` describes what the link unsubscribes: a small page with a button in
    a browser (``karni/notify/unsubscribe.html``, which a project overrides in
    its templates), JSON otherwise. ``POST`` unsubscribes, from the page's
    button or from a mail program's one-click (``List-Unsubscribe-Post``), and
    ``POST ...&undo=1`` takes it back. A token this project did not sign is
    400 ``E442``.
    """

    template_name: ClassVar[str] = "karni/notify/unsubscribe.html"

    def _token(self, request: HttpRequest) -> str:
        return str(request.GET.get("token") or request.POST.get("token") or "")

    def _wants_page(self, request: HttpRequest) -> bool:
        return "text/html" in str(request.headers.get("Accept", ""))

    def _answer(self, request: HttpRequest, values: dict[str, Any], status: int = 200) -> Any:
        if self._wants_page(request):
            return render(request, self.template_name, values, status=status)
        return JsonResponse(values, status=status)

    def _read(self, request: HttpRequest) -> tuple[str, str, Any] | HttpResponse:
        from karni.mail import find_kind

        try:
            address, kind = services.read_token(self._token(request))
        except KarniValueError as exc:
            return self._answer(request, {"code": exc.code, "detail": exc.message}, status=400)
        return address, kind, find_kind(kind)

    def get(self, request: HttpRequest) -> Any:
        found = self._read(request)
        if isinstance(found, HttpResponse):
            return found
        address, kind, declared = found
        return self._answer(request, self._values(request, address, kind, declared))

    def post(self, request: HttpRequest) -> Any:
        found = self._read(request)
        if isinstance(found, HttpResponse):
            return found
        address, kind, declared = found
        if _truthy(request.GET.get("undo") or request.POST.get("undo")):
            services.resubscribe(address, kind)
        else:
            try:
                services.unsubscribe(address, kind)
            except KarniValueError as exc:
                return self._answer(request, {"code": exc.code, "detail": exc.message}, 400)
        return self._answer(request, self._values(request, address, kind, declared))

    def _values(
        self, request: HttpRequest, address: str, kind: str, declared: Any
    ) -> dict[str, Any]:
        return {
            "address": address,
            "kind": kind,
            "title": declared.title if declared is not None else kind,
            "unsubscribed": services.unsubscribed(address, kind),
            "token": self._token(request),
        }


def build_urlpatterns(*, force: bool = False) -> list[Any]:
    """Experimental. The ``inbox/`` and ``notify/`` routes while ``KARNI_NOTIFY_API`` is on."""
    from django.urls import path

    if not force and not getattr(settings, "KARNI_NOTIFY_API", True):
        return []
    return [
        path("inbox/", InboxView.as_view(), name="karni-inbox"),
        path("inbox/unread/", UnreadView.as_view(), name="karni-inbox-unread"),
        path("inbox/read-all/", MarkAllReadView.as_view(), name="karni-inbox-read-all"),
        path("inbox/choices/", ChoicesView.as_view(), name="karni-inbox-choices"),
        path("inbox/choices/<str:kind>/", ChoiceView.as_view(), name="karni-inbox-choice"),
        path("inbox/<int:pk>/read/", MarkView.as_view(read=True), name="karni-inbox-read"),
        path("inbox/<int:pk>/unread/", MarkView.as_view(read=False), name="karni-inbox-unread-one"),
        path("notify/unsubscribe/", UnsubscribeView.as_view(), name="karni-notify-unsubscribe"),
    ]
