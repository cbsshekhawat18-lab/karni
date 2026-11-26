"""The admin list looks a table up once, and a duplicate query names the code that ran it."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from karni import performance
from karni.admin import listing
from karni.performance import record_queries
from tests.adminapp.models import Widget

pytestmark = pytest.mark.django_db

LOOKUP = "to_regclass"


def _client() -> Client:
    users = get_user_model()
    user = users.objects.create_superuser(email="root@example.com", password="pw-123456")
    client = Client()
    client.force_login(user)
    return client


def _list_widgets(**settings: Any) -> Any:
    Widget.objects.bulk_create([Widget(name=f"Widget {i}") for i in range(3)])
    url = reverse("admin:adminapp_widget_changelist")
    client = _client()
    with override_settings(**settings), record_queries() as recorder:
        assert client.get(url).status_code == 200
    return recorder


@pytest.mark.skipif(connection.vendor != "postgresql", reason="the estimate is PostgreSQL only")
def test_one_list_request_looks_the_table_up_once() -> None:
    recorder = _list_widgets()
    lookups = [query for query in recorder.queries if LOOKUP in query.sql]
    assert len(lookups) == 1, [query.sql for query in recorder.queries]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="the estimate is PostgreSQL only")
def test_the_size_is_remembered_for_one_screen_only() -> None:
    from django.db import connections

    default = connections["default"]
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE sfcore_estimate_probe (id integer)")
        cursor.execute("INSERT INTO sfcore_estimate_probe SELECT generate_series(1, 50)")
        cursor.execute("ANALYZE sfcore_estimate_probe")
    try:
        assert listing.table_rows(default, "sfcore_estimate_probe") == 50
        with listing.remembered_sizes(), listing.remembered_sizes():
            assert listing.table_rows(default, "sfcore_estimate_probe") == 50
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE sfcore_estimate_probe")
            assert listing.table_rows(default, "sfcore_estimate_probe") == 50  # the same screen
        assert listing.table_rows(default, "sfcore_estimate_probe") is None  # a new one asks again
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS sfcore_estimate_probe")


@pytest.mark.skipif(connection.vendor != "postgresql", reason="the estimate is PostgreSQL only")
def test_a_pass_through_middleware_is_not_blamed_for_a_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This file stands for the server that calls the project (its frames are not the project's),
    # so the middleware is the only project frame on the stack, as in a running site.
    monkeypatch.setattr(
        performance, "_ROOTS", (*performance._framework_roots(), str(Path(__file__)))
    )
    # without the memo the list asks twice, which is when an origin is recorded
    monkeypatch.setattr(listing, "remembered_sizes", contextlib.nullcontext)
    middleware = [*_middleware(), "tests.admin.passthrough_middleware.PassThrough"]
    recorder = _list_widgets(MIDDLEWARE=middleware)
    origins = {group.table: group.origin for group in recorder.report().duplicates()}
    assert origins["pg_class"].startswith("karni.admin.listing:"), origins
    assert origins["pg_class"].endswith("in table_rows"), origins


def test_a_project_frame_that_called_karni_is_still_named() -> None:
    from karni.performance import query_origin

    def project_code() -> str:
        return _from_karni()

    def _from_karni() -> str:
        namespace: dict[str, Any] = {"__name__": "karni.fake", "query_origin": query_origin}
        exec(compile("def issue():\n    return query_origin()\n", "<karni>", "exec"), namespace)
        issue: Any = namespace["issue"]
        return str(issue())

    assert "test_count_lookup.py" in project_code() and "in _from_karni" in project_code()


def _middleware() -> list[str]:
    from django.conf import settings

    return list(settings.MIDDLEWARE)
