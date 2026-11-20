"""Experimental. ``/api/email-templates/``: the emails a business edits (Settings, Emails).

``GET`` lists every declared message kind (``karni.mail`` kinds) with its merge
fields, its switch, its channels and its text now (edited, else the files).
``GET``, ``PUT`` and ``DELETE`` ``email-templates/<kind>/`` read, change and put back
one. ``POST email-templates/<kind>/preview/`` renders a draft with sample values.
Reading needs ``notify.emailtemplate:view``, changing ``notify.emailtemplate:change``.

Override / escape hatch: ``KARNI_NOTIFY_API = False`` keeps it off the router;
subclass :class:`EmailTemplateViewSet` and route your own.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import Access, BaseViewSet, Can, Granted
from karni.notify import editor
from karni.notify.models import EmailTemplate

__all__ = ["EmailTemplateInputSerializer", "EmailTemplateSerializer", "EmailTemplateViewSet"]

#: Routed by autodiscovery unless ``KARNI_NOTIFY_API`` is False (read at import).
_ROUTED = bool(getattr(settings, "KARNI_NOTIFY_API", True))


class EmailFieldSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    meaning = serializers.CharField()


class EmailTemplateSerializer(serializers.Serializer[Any]):
    """Experimental. An email as its editor shows it: its text now, its merge fields, its switch."""

    kind = serializers.CharField()
    title = serializers.CharField()
    describe = serializers.CharField(allow_blank=True)
    audience = serializers.CharField(allow_blank=True)
    switchable = serializers.BooleanField()
    on = serializers.BooleanField()
    channels = serializers.ListField(child=serializers.CharField())
    marketing = serializers.BooleanField()
    fields = EmailFieldSerializer(many=True)
    edited = serializers.BooleanField()
    subject = serializers.CharField(allow_blank=True)
    text = serializers.CharField(allow_blank=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class EmailTemplateInputSerializer(serializers.Serializer[Any]):
    """Experimental. An edited email: its subject and its text."""

    subject = serializers.CharField(max_length=300, allow_blank=True)
    text = serializers.CharField(max_length=20000, allow_blank=True)


class EmailTemplateViewSet(BaseViewSet):
    """Experimental. The emails a business edits: ``/api/email-templates/`` (see the module)."""

    model = EmailTemplate
    route = "email-templates"
    auto_register = _ROUTED
    access = Access(read=Granted(), write=Granted())
    serializer_class = EmailTemplateSerializer
    lookup_field = "kind"
    lookup_value_regex = r"[a-z0-9_.-]+"
    unbudgeted_actions = BaseViewSet.unbudgeted_actions | {"list", "retrieve", "preview"}

    def _kind(self, name: str) -> Any:
        from karni.mail import find_kind

        found = find_kind(name)
        if found is None:
            raise NotFound("No such email.")
        return found

    @extend_schema(responses=EmailTemplateSerializer(many=True))
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from karni.mail import kinds as mail_kinds

        edited = {row.kind: row for row in EmailTemplate.objects.all()}
        # karni: allow(unpaginated-action): the declared emails, a few dozen at most
        return Response([editor.describe(kind, edited.get(kind.name)) for kind in mail_kinds()])

    @extend_schema(responses=EmailTemplateSerializer)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kind = self._kind(str(kwargs.get("kind", "")))
        row = EmailTemplate.objects.filter(kind=kind.name).first()
        return Response(editor.describe(kind, row))

    @extend_schema(request=EmailTemplateInputSerializer, responses=EmailTemplateSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kind = self._kind(str(kwargs.get("kind", "")))
        body = EmailTemplateInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        row = editor.save(kind, body.validated_data["subject"], body.validated_data["text"])
        return Response(editor.describe(kind, row))

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("POST", detail="PUT email-templates/<kind>/ changes one.")

    @extend_schema(responses=EmailTemplateSerializer)
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Put the email back to its files."""
        kind = self._kind(str(kwargs.get("kind", "")))
        EmailTemplate.objects.filter(kind=kind.name).delete()
        return Response(editor.describe(kind, None))

    @extend_schema(request=EmailTemplateInputSerializer, responses=OpenApiTypes.OBJECT)
    @action(
        detail=True,
        methods=["post"],
        url_path="preview",
        access=Can("notify.emailtemplate:change"),
    )
    def preview(self, request: Request, kind: str = "") -> Response:
        """A draft rendered with sample values: its subject, text and HTML."""
        found = self._kind(kind)
        body = EmailTemplateInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            editor.preview(found, body.validated_data["subject"], body.validated_data["text"])
        )
