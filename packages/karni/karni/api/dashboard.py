"""Experimental. ``GET /api/dashboard/``: the home tiles the requesting person sees.

``{"tiles": [{"key", "title", "kind", "size", "order", "description", "link",
"resource", "filters", "columns", "limit", "data"}, ...]}`` in order
(:func:`karni.tiles.tiles_for`). A tile with ``resource`` is counted or listed
by the browser through that resource's list endpoint, with ``filters``. A tile
with ``data`` carries the figures its code worked out. A visitor who is not
signed in gets the tiles open to everyone (usually none).

Override / escape hatch: subclass :class:`DashboardView` and override
:meth:`~DashboardView.get_tiles`, then declare ``path("api/dashboard/",
YourView.as_view())`` before the API include.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.tiles import tiles_for

__all__ = ["DashboardSerializer", "DashboardView", "TileSerializer"]


class TileSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One home tile."""

    key = serializers.CharField()
    title = serializers.CharField()
    kind = serializers.ChoiceField(choices=["stat", "list", "chart", "custom"])
    size = serializers.ChoiceField(choices=["third", "half", "full"])
    order = serializers.IntegerField()
    description = serializers.CharField(allow_blank=True)
    link = serializers.CharField(allow_null=True)
    resource = serializers.CharField(allow_null=True)
    filters = serializers.DictField()
    columns = serializers.ListField(child=serializers.CharField())
    limit = serializers.IntegerField()
    data = serializers.DictField(allow_null=True)


class DashboardSerializer(serializers.Serializer):  # type: ignore[type-arg]
    tiles = TileSerializer(many=True)


class DashboardView(APIView):
    """Experimental. The home tiles of the requesting person."""

    permission_classes = [AllowAny]

    def get_tiles(self, request: Request) -> list[dict[str, Any]]:
        return tiles_for(request)

    @extend_schema(responses=DashboardSerializer, operation_id="dashboard_tiles")
    def get(self, request: Request) -> Response:
        return Response({"tiles": self.get_tiles(request)})
