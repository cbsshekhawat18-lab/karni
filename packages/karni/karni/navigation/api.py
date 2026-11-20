"""Experimental. ``GET /api/navigation/``: the menu the requesting user sees.

``{"items": [{"label", "icon", "route", "children"}, ...]}``, siblings in
order, built by :func:`karni.navigation.payload` from the active source
(``KARNI_NAVIGATION``): the settings list or the ``NavItem`` rows.
``?menu=public`` names one of the named menus (default ``app``), and a
menu the project does not name answers no entries. Entries
the user's grants do not open are left out, and so is a group whose
entries are all hidden. Anyone may call it: a visitor who is not signed in
gets the ``public`` entries. A group has ``route: null``, an item
``children: []``.

The route exists while ``KARNI_NAVIGATION`` is set (:func:`build_urlpatterns`,
mounted by :mod:`karni.api.urls`). A URLconf built while it was set answers
404 ``E535`` once it is unset.

Override / escape hatch: subclass :class:`NavigationView` and override
:meth:`~NavigationView.get_menu`, then declare
``path("api/navigation/", YourView.as_view())`` before the API include.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.urls import URLPattern, path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni import navigation
from karni.exceptions import KarniValueError

__all__ = [
    "NavigationItemSerializer",
    "NavigationSerializer",
    "NavigationView",
    "build_urlpatterns",
]

_ITEM_REF = {"$ref": "#/components/schemas/NavigationItem"}


@extend_schema_field({"type": "array", "items": _ITEM_REF})
class _Children(serializers.ListField):  # type: ignore[type-arg]
    """A group's entries: more ``NavigationItem`` objects (the schema refers to itself)."""


class NavigationItemSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One menu entry. A group has ``route: null``, an item ``children: []``."""

    label = serializers.CharField()
    icon = serializers.CharField(allow_null=True, help_text="An icon name, or null.")
    route = serializers.CharField(allow_null=True, help_text="An app path. null for a group.")
    children = _Children(child=serializers.DictField())


class NavigationSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. The body of ``GET /api/navigation/``."""

    items = NavigationItemSerializer(many=True)


def turned_off() -> Response:
    """The 404 ``E535`` the route answers while ``KARNI_NAVIGATION`` is unset."""
    error = KarniValueError(
        f"Navigation is turned off: {navigation.SETTING} is not set.", code="E535"
    )
    return Response({"code": "E535", "detail": str(error)}, status=status.HTTP_404_NOT_FOUND)


class NavigationView(APIView):
    """Experimental. ``GET navigation/``: the menu for the requesting user, signed in or not.

    Override / escape hatch: override :meth:`get_menu`.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]

    # On the method: drf-spectacular refuses an operation_id on a view class.
    @extend_schema(
        operation_id="navigation",
        parameters=[
            OpenApiParameter(
                "menu",
                OpenApiTypes.STR,
                description="The named menu: app (the default), public, account, or any name "
                "KARNI_NAVIGATION declares. A name it does not declare answers no entries.",
            )
        ],
        responses={200: NavigationSerializer, 404: OpenApiTypes.OBJECT},
        tags=["navigation"],
    )
    def get(self, request: Request, **kwargs: Any) -> Response:
        if navigation.source() is None:
            return turned_off()
        return Response(self.get_menu(request))

    def get_menu_name(self, request: Request) -> str:
        """The menu ``?menu=`` names (default ``app``)."""
        value = str(request.query_params.get("menu", "") or "").strip()
        return value or navigation.DEFAULT_MENU

    def get_menu(self, request: Request) -> dict[str, Any]:
        """The body: :func:`karni.navigation.payload` for ``request.user`` and the menu asked."""
        return navigation.payload(request.user, menu=self.get_menu_name(request))


def build_urlpatterns() -> list[URLPattern]:
    """Experimental. The ``navigation/`` route while ``KARNI_NAVIGATION`` is set, else ``[]``."""
    if navigation.source() is None:
        return []
    return [path("navigation/", NavigationView.as_view(), name="karni-navigation")]
