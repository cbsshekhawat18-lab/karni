"""Experimental. The API behind the Settings page: ``/api/preferences/``.

* ``GET preferences/``: everything the page shows, for a caller who may change
  at least one part of it (403 otherwise): ``details`` (values, fields,
  locked fields), ``sections`` (one per registered section: its JSON schema,
  values, defaults, locked fields), ``connections`` (each declared one: what
  it needs, whether that is installed, its switch, whether it is active) and
  ``emails`` (the sender, and each email kind with its switch). Every part
  says ``can_change`` for this caller.
* ``PATCH preferences/details/``: some details (JSON, or multipart with a
  ``logo`` file, and ``"logo": null`` removes it).
* ``PATCH preferences/sections/<key>/``: some fields of a section. ``null``
  puts a field back to its default.
* ``PATCH preferences/connections/<name>/`` and ``PATCH preferences/emails/<kind>/``:
  ``{"on": true | false | null}`` (``null``: back to the default).
* ``GET preferences/history/``: the latest changes, who made them and what moved.
* ``GET preferences/public/``: the details any visitor may see (name, address,
  phone, contact email, logo, time zone, language, currency and its display),
  for the site's header, footer and money formatting. Open to everyone.

A refused change answers 400 ``E323`` (with ``errors`` per field), 409
``E324`` (the deployment fixes it) or 404 ``E325`` (no such name).

Override / escape hatch: ``KARNI_PREFERENCES_API = False`` mounts nothing, and
:func:`build_urlpatterns` lets a project mount the views under its own prefix
or subclass them.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.urls import path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.errorcodes import KarniError
from karni.preferences import registry, services
from karni.preferences.services import PreferenceRefused

__all__ = [
    "ConnectionView",
    "DetailsView",
    "EmailView",
    "HistoryView",
    "PublicDetailsView",
    "SectionView",
    "SettingsView",
    "build_urlpatterns",
    "settings_page",
]

#: The details anyone may read (``GET preferences/public/``).
PUBLIC_DETAILS = (
    "name",
    "legal_name",
    "address",
    "phone",
    "email",
    "tax_number",
    "logo",
    "time_zone",
    "language",
    "currency",
    "currency_display",
)
_STATUS = {"E323": 400, "E324": 409, "E325": 404}


def _refused(exc: KarniError) -> Response:
    body: dict[str, Any] = {"code": exc.code, "detail": exc.message}
    if isinstance(exc, PreferenceRefused) and exc.errors:
        body["errors"] = exc.errors
    return Response(body, status=_STATUS.get(exc.code or "", 400))


def _forbidden(what: str) -> Response:
    return Response(
        {"detail": f"You may not change {what}."},
        status=403,
    )


def _detail_fields() -> list[dict[str, Any]]:
    from karni.preferences.models import DETAIL_FIELDS, Details

    found = []
    for name in DETAIL_FIELDS:
        field = Details._meta.get_field(name)
        kind = "text"
        if name == "logo":
            kind = "file"
        elif name == "address":
            kind = "textarea"
        elif name in ("email", "sender_email", "reply_to"):
            kind = "email"
        elif getattr(field, "choices", None):
            kind = "choice"
        entry: dict[str, Any] = {
            "name": name,
            "label": str(field.verbose_name).capitalize(),
            "type": kind,
            "help": str(field.help_text or ""),
        }
        if kind == "choice":
            entry["choices"] = [{"value": v, "label": str(label)} for v, label in field.choices]
        found.append(entry)
    return found


def settings_page(user: Any) -> dict[str, Any]:
    """Experimental. What ``GET preferences/`` answers for ``user``."""
    from karni.preferences import CONTRACT

    shown = services.details()
    sections = []
    for spec in registry.sections():
        sections.append(
            {
                "key": spec.key,
                "title": spec.title,
                "describe": spec.describe,
                "version": spec.version,
                "schema": spec.schema(),
                "values": services.get(spec.key).model_dump(mode="json"),
                "defaults": spec.defaults(),
                "locked": sorted(services.locked_names(spec.key)),
                "can_change": services.can_change(user, spec.key),
            }
        )
    connections = []
    for found in registry.connections():
        on = services.switch_position("connection", found.name, found.default)
        installed = found.installed()
        connections.append(
            {
                "name": found.name,
                "title": found.title,
                "describe": found.describe,
                "part": found.prefix,
                "needs": list(found.needs),
                "installed": installed,
                "default": found.default,
                "on": on,
                "active": installed and on,
                "locked": services.locked("connections", found.name),
            }
        )
    kinds = []
    for kind in registry.emails():
        kinds.append(
            {
                "name": kind.name,
                "title": kind.title,
                "describe": kind.describe,
                "transactional": kind.transactional,
                "source": kind.source,
                "audience": kind.audience,
                "switchable": kind.switchable,
                "editable": kind.editable,
                "default": kind.default,
                "on": services.email_on(kind.name, kind.default),
                "locked": services.locked("emails", kind.name) or not kind.switchable,
            }
        )
    return {
        "contract": CONTRACT,
        "details": {
            "values": shown.as_dict(),
            "fields": _detail_fields(),
            "locked": sorted(services.locked_names("details")),
            "can_change": services.can_change(user, "details"),
        },
        "sections": sections,
        "connections": {
            "items": connections,
            "can_change": services.can_change(user, "connections"),
        },
        "emails": {
            "sender": {
                "sender_name": shown.sender_name,
                "sender_email": shown.sender_email,
                "reply_to": shown.reply_to,
                "from": services.sender() or "",
            },
            "items": kinds,
            "can_change": services.can_change(user, "emails"),
        },
    }


def _may_open(user: Any) -> bool:
    targets = ["details", "connections", "emails", *(s.key for s in registry.sections())]
    return any(services.can_change(user, target) for target in targets)


class SettingsView(APIView):
    """Experimental. ``GET preferences/``: the Settings page (see the module docstring)."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="preferences_page",
        tags=["preferences"],
        description="Experimental. The Settings page: details, sections, connections, emails.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, **kwargs: Any) -> Response:
        if not _may_open(request.user):
            return _forbidden("any setting")
        return Response(settings_page(request.user))


class PublicDetailsView(APIView):
    """Experimental. ``GET preferences/public/``: the details any visitor may see."""

    permission_classes: ClassVar[list[type]] = [AllowAny]
    authentication_classes: ClassVar[list[type]] = []

    @extend_schema(
        operation_id="preferences_public",
        tags=["preferences"],
        description="Experimental. The business's public details, for the header and footer.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, **kwargs: Any) -> Response:
        shown = services.details().as_dict()
        return Response({name: shown[name] for name in PUBLIC_DETAILS})


class DetailsView(APIView):
    """Experimental. ``PATCH preferences/details/``: change some details."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="preferences_details_update",
        tags=["preferences"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(self, request: Request, **kwargs: Any) -> Response:
        if not services.can_change(request.user, "details"):
            return _forbidden("the details")
        values = {name: request.data[name] for name in request.data if name != "logo"}
        logo = request.FILES.get("logo")
        clear = "logo" in request.data and not logo and request.data.get("logo") in (None, "")
        try:
            services.save_details(values, user=request.user, logo=logo, clear_logo=clear)
        except KarniError as exc:
            return _refused(exc)
        return Response(settings_page(request.user)["details"])


class SectionView(APIView):
    """Experimental. ``PATCH preferences/sections/<key>/``: change some fields of a section."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="preferences_section_update",
        tags=["preferences"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(self, request: Request, key: str, **kwargs: Any) -> Response:
        if registry.find_section(key) is None:
            return Response({"code": "E325", "detail": f"No section {key!r}."}, status=404)
        if not services.can_change(request.user, key):
            return _forbidden(f"the {key} settings")
        if not isinstance(request.data, dict):
            return Response(
                {"code": "E323", "detail": "Send an object of field names to values."},
                status=400,
            )
        try:
            found = services.save_section(key, dict(request.data), user=request.user)
        except KarniError as exc:
            return _refused(exc)
        return Response({"key": key, "values": found.model_dump(mode="json")})


class _SwitchView(APIView):
    kind: ClassVar[str] = "connection"
    target: ClassVar[str] = "connections"
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def patch(self, request: Request, name: str, **kwargs: Any) -> Response:
        if not services.can_change(request.user, self.target):
            return _forbidden(f"the {self.target}")
        on = request.data.get("on") if isinstance(request.data, dict) else None
        if "on" not in request.data or (on is not None and not isinstance(on, bool)):
            return Response(
                {"code": "E323", "detail": 'Send {"on": true}, {"on": false} or {"on": null}.'},
                status=400,
            )
        try:
            position = services.switch(self.kind, name, on, user=request.user)
        except KarniError as exc:
            return _refused(exc)
        return Response({"name": name, "on": position})


class ConnectionView(_SwitchView):
    """Experimental. ``PATCH preferences/connections/<name>/``: switch a connection."""

    kind = "connection"
    target = "connections"

    @extend_schema(
        operation_id="preferences_connection_update",
        tags=["preferences"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(self, request: Request, name: str, **kwargs: Any) -> Response:
        return super().patch(request, name, **kwargs)


class EmailView(_SwitchView):
    """Experimental. ``PATCH preferences/emails/<kind>/``: switch an email kind."""

    kind = "email"
    target = "emails"

    @extend_schema(
        operation_id="preferences_email_update",
        tags=["preferences"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(self, request: Request, name: str, **kwargs: Any) -> Response:
        return super().patch(request, name, **kwargs)


class HistoryView(APIView):
    """Experimental. ``GET preferences/history/``: the latest 100 changes, newest first."""

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    @extend_schema(
        operation_id="preferences_history",
        tags=["preferences"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, **kwargs: Any) -> Response:
        from django.contrib.contenttypes.models import ContentType

        from karni.audit.models import ChangeLog
        from karni.preferences.models import Details, SectionValue, Switch

        if not _may_open(request.user):
            return _forbidden("any setting")
        types = ContentType.objects.get_for_models(Details, SectionValue, Switch)
        names = {ct.pk: model.__name__ for model, ct in types.items()}
        rows = (
            ChangeLog.objects.filter(content_type__in=list(types.values()))
            .select_related("actor")
            .order_by("-timestamp")[:100]
        )
        objects = _labels(rows, types)
        return Response(
            [
                {
                    "at": row.timestamp.isoformat(),
                    "table": names.get(row.content_type_id, ""),
                    "record": objects.get((row.content_type_id, row.object_id), "details"),
                    "action": row.action,
                    "changes": row.diff,
                    "actor": str(row.actor) if row.actor is not None else None,
                }
                for row in rows
            ]
        )


def _labels(rows: Any, types: dict[Any, Any]) -> dict[tuple[int, str], str]:
    """Each changed row's name: a section key, a switch's name, "details"."""
    from karni.preferences.models import SectionValue, Switch

    found: dict[tuple[int, str], str] = {}
    ids: dict[int, set[str]] = {}
    for row in rows:
        ids.setdefault(row.content_type_id, set()).add(row.object_id)
    for model, field in ((SectionValue, "section"), (Switch, "name")):
        ct = types[model]
        wanted = [pk for pk in ids.get(ct.pk, ()) if str(pk).isdigit()]
        for pk, label in model.objects.filter(pk__in=wanted).values_list("pk", field):
            found[(ct.pk, str(pk))] = str(label)
    return found


def build_urlpatterns(*, force: bool = False) -> list[Any]:
    """Experimental. The ``preferences/`` routes, unless ``KARNI_PREFERENCES_API`` is False.

    ``force=True`` returns them whatever the setting says (a project's own URLconf).
    """
    from django.conf import settings

    if not force and not getattr(settings, "KARNI_PREFERENCES_API", True):
        return []
    return [
        path("preferences/", SettingsView.as_view(), name="karni-preferences"),
        path("preferences/public/", PublicDetailsView.as_view(), name="karni-preferences-public"),
        path("preferences/details/", DetailsView.as_view(), name="karni-preferences-details"),
        path("preferences/history/", HistoryView.as_view(), name="karni-preferences-history"),
        path(
            "preferences/sections/<str:key>/",
            SectionView.as_view(),
            name="karni-preferences-section",
        ),
        path(
            "preferences/connections/<str:name>/",
            ConnectionView.as_view(),
            name="karni-preferences-connection",
        ),
        path(
            "preferences/emails/<str:name>/",
            EmailView.as_view(),
            name="karni-preferences-email",
        ),
    ]
