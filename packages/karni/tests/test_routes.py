"""Tests for ``manage.py karni_routes`` against the suite's URLconf (tests/urls.py)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

from django.core.management import call_command
from django.urls import path, re_path
from django.views.generic import View
from rest_framework.decorators import api_view
from rest_framework.response import Response

from karni.management.commands.karni_routes import access_summary, collect_routes, format_table
from tests.testapp.viewsets import EventViewSet


def _rows() -> dict[str, dict[str, Any]]:
    out = StringIO()
    call_command("karni_routes", "--json", stdout=out)
    return {row["path"]: row for row in json.loads(out.getvalue())}


def test_viewset_list_route() -> None:
    row = _rows()["/api/events/"]
    assert row["methods"] == ["GET", "POST"]
    assert row["actions"] == {"GET": "list", "POST": "create"}
    assert row["name"] == "testapp-event-list"
    assert row["view"] == "tests.testapp.viewsets.EventViewSet"
    assert row["model"] == "testapp.Event"
    expected = getattr(EventViewSet, "access", None)
    assert row["access"] == (repr(expected) if expected is not None else None)


def test_viewset_detail_route_and_path_prettifying() -> None:
    row = _rows()["/api/events/<pk>/"]
    assert row["methods"] == ["GET", "PUT", "PATCH", "DELETE"]
    assert row["actions"]["DELETE"] == "destroy"


def test_api_view_and_function_view_and_namespaces() -> None:
    rows = _rows()
    assert rows["/api/auth/login/"]["methods"] == ["POST"]
    assert rows["/api/auth/login/"]["model"] is None
    assert rows["/model-layer/venues/sync/"]["methods"] == ["ANY"]
    assert rows["/model-layer/venues/sync/"]["view"] == "tests.model_layer_views.create_venue"
    assert rows["/admin/"]["name"] == "admin:index"


def test_format_suffix_duplicates_are_omitted() -> None:
    assert not [p for p in _rows() if "format" in p]


def test_table_output() -> None:
    out = StringIO()
    call_command("karni_routes", stdout=out)
    lines = out.getvalue().splitlines()
    # ACCESS appears only when some routed viewset declares `access`.
    from karni.management.commands.karni_routes import collect_routes

    has_access = any(row["access"] for row in collect_routes())
    expected = ["METHODS", "PATH", "NAME", "VIEW", "MODEL"] + (["ACCESS"] if has_access else [])
    assert lines[0].split() == expected
    events = next(line for line in lines if " /api/events/ " in line)
    assert events.startswith("GET|POST")
    assert "tests.testapp.viewsets.EventViewSet (list, create)" in events
    assert "testapp.Event" in events


class _Plain(View):
    def get(self, request: Any) -> None:
        return None

    def post(self, request: Any) -> None:
        return None


@api_view(["GET", "DELETE"])
def _drf_function(request: Any) -> Response:
    return Response()


urlpatterns = [
    path("plain/", _Plain.as_view(), name="plain"),
    re_path(r"^drf/(?P<slug>[-\w]+)/$", _drf_function, name="drf"),
]


def test_collect_routes_for_another_urlconf() -> None:
    rows = collect_routes(__name__)
    assert rows[0]["path"] == "/plain/"
    assert rows[0]["methods"] == ["GET", "POST"]
    assert rows[0]["view"].endswith("test_routes._Plain")
    assert rows[1]["path"] == "/drf/<slug>/"
    assert rows[1]["methods"] == ["GET", "DELETE"]
    table = format_table(rows)
    assert "MODEL" not in table and "ACCESS" not in table  # only shown when some row has one


def test_access_summary_is_defensive() -> None:
    class NoAccess:
        pass

    class Declared:
        access = "Access(read=Public())"

    assert access_summary(NoAccess) is None
    assert access_summary(Declared) == "Access(read=Public())"
