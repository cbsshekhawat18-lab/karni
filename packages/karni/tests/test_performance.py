"""Query accounting: the recorder, per-action budgets, the dev query log, the pytest plugin."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.test.utils import override_settings
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from karni.api import Access, Authenticated, BaseViewSet, Budget, Public
from karni.middleware import QueryLogMiddleware
from karni.performance import (
    DEFAULT_QUERY_BUDGET,
    QueryBudgetExceeded,
    budget_mode,
    record_queries,
    resolve_budget,
)
from tests.perfapp.models import Chapter, Novel, Publisher, Writer

pytestmark = pytest.mark.django_db

OPEN = Access(read=Public(), write=Authenticated())


class LeakyNovelSerializer(serializers.ModelSerializer):
    """``chapter_titles`` reads a relation per row behind the optimiser's back."""

    chapter_titles = serializers.SerializerMethodField()

    class Meta:
        model = Novel
        fields = ["id", "title", "chapter_titles"]

    def get_chapter_titles(self, novel: Novel) -> list[str]:
        return [chapter.title for chapter in Chapter.objects.filter(novel=novel)]


class LeakyNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = LeakyNovelSerializer
    auto_register = False


def _novels(count: int) -> None:
    writer = Writer.objects.create(name="W", publisher=Publisher.objects.create(name="P"))
    for index in range(count):
        novel = Novel.objects.create(title=f"N{index}", writer=writer, status="out")
        Chapter.objects.create(novel=novel, number=1, title="one")


def _list(viewset: type[Any]) -> Any:
    return viewset.as_view({"get": "list"})(APIRequestFactory().get("/"))


# recorder & report


def test_recorder_groups_duplicates_and_names_the_origin() -> None:
    _novels(4)
    with override_settings(KARNI_QUERY_BUDGET_MODE="off"), record_queries() as recorder:
        response = _list(LeakyNovelViewSet)
    assert response.status_code == 200
    report = recorder.report()
    assert report.count == 2 + 4  # COUNT, novels, one chapter query per novel
    (group,) = report.duplicates()
    assert group.count == 4
    assert group.table == "perfapp_chapter"
    # The serializer field that rendered it, and the project code inside it.
    assert group.origin.startswith("LeakyNovelSerializer.chapter_titles")
    assert "get_chapter_titles" in group.origin
    rendered = report.render()
    assert "4× SELECT … FROM" in rendered
    assert "6 queries, 4 duplicated" in rendered


def test_savepoints_are_not_counted() -> None:
    """atomic() nesting adds SAVEPOINT/RELEASE statements; they read no data."""
    from django.db import transaction

    with record_queries() as recorder:
        with transaction.atomic():  # inside the test's transaction: a savepoint
            list(Publisher.objects.all())
    assert recorder.report().count == 1


def test_report_without_duplicates_is_one_line() -> None:
    with record_queries() as recorder:
        list(Publisher.objects.all())
    assert recorder.report().render().startswith("1 queries, 0 duplicated")
    assert recorder.report().duplicates() == []


# Budget declarations


def test_budget_requires_a_reason_and_valid_limits() -> None:
    with pytest.raises(ImproperlyConfigured, match="reason"):
        Budget(list=20, reason="")
    with pytest.raises(ImproperlyConfigured, match="names no action"):
        Budget(reason="why")
    with pytest.raises(ImproperlyConfigured, match="positive integer"):
        Budget(list=0, reason="why")
    with pytest.raises(ImproperlyConfigured, match="positive integer"):
        Budget(list=True, reason="why")
    budget = Budget(list=20, default=None, reason="export")
    assert budget.limit_for("list") == 20
    assert budget.limit_for("retrieve") is None
    assert budget.describe() == "list=20, *=None"


def test_budget_resolution_falls_back_to_settings() -> None:
    assert resolve_budget(None, "list") == DEFAULT_QUERY_BUDGET["list"] == 8
    assert resolve_budget(None, "export") == DEFAULT_QUERY_BUDGET["*"] == 15
    assert resolve_budget(Budget(list=30, reason="r"), "retrieve") == 8
    with override_settings(KARNI_QUERY_BUDGET={"list": 3}):
        assert resolve_budget(None, "list") == 3
        assert resolve_budget(None, "destroy") == 10  # partial dicts merge


def test_viewset_budget_declarations_are_validated() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"Budget\(list=20"):

        class Plain(BaseViewSet):
            model = Novel
            access = OPEN
            query_budget = 20  # type: ignore[assignment]
            auto_register = False

    with pytest.raises(ImproperlyConfigured, match="unknown action"):

        class Typo(BaseViewSet):
            model = Novel
            access = OPEN
            query_budget = Budget(lsit=20, reason="typo")
            auto_register = False


# enforcement in BaseViewSet.dispatch


def test_the_plugin_makes_budgets_raise_in_tests() -> None:
    assert settings.KARNI_QUERY_BUDGET_MODE == "raise"
    assert budget_mode() == "raise"


def test_over_budget_request_raises_with_the_report() -> None:
    _novels(9)  # 2 + 9 queries > list budget 8
    with pytest.raises(QueryBudgetExceeded) as excinfo:
        _list(LeakyNovelViewSet)
    message = str(excinfo.value)
    assert "LeakyNovelViewSet.list ran 11 queries; budget is 8." in message
    assert "9× SELECT" in message
    assert "LeakyNovelSerializer.chapter_titles" in message
    assert "query_budget = Budget(list=N, reason=...)" in message


def test_within_budget_sets_headers() -> None:
    _novels(2)
    response = _list(LeakyNovelViewSet)
    assert response["X-Karni-Queries"] == "4"
    assert response["X-Karni-Query-Budget"] == "8"


def test_a_declared_budget_raises_the_limit() -> None:
    class Measured(LeakyNovelViewSet):
        query_budget = Budget(list=20, reason="per-row chapter titles, measured")

    _novels(9)
    response = _list(Measured)
    assert response["X-Karni-Query-Budget"] == "20"


def test_none_stops_checking_an_action() -> None:
    class Export(LeakyNovelViewSet):
        query_budget = Budget(list=None, reason="nightly export, unbounded by design")

    _novels(9)
    response = _list(Export)
    assert response["X-Karni-Queries"] == "11"
    assert "X-Karni-Query-Budget" not in response


def test_warn_mode_logs_instead_of_raising(caplog: pytest.LogCaptureFixture) -> None:
    _novels(9)
    with override_settings(KARNI_QUERY_BUDGET_MODE="warn"), caplog.at_level(logging.WARNING):
        response = _list(LeakyNovelViewSet)
    assert response.status_code == 200
    assert response["X-Karni-Queries"] == "11"
    assert any("ran 11 queries; budget is 8" in record.getMessage() for record in caplog.records)


def test_off_mode_does_not_count() -> None:
    _novels(9)
    with override_settings(KARNI_QUERY_BUDGET_MODE="off"):
        response = _list(LeakyNovelViewSet)
    assert "X-Karni-Queries" not in response


def test_invalid_mode_is_a_configuration_error() -> None:
    with override_settings(KARNI_QUERY_BUDGET_MODE="loud"):
        with pytest.raises(ImproperlyConfigured, match="KARNI_QUERY_BUDGET_MODE"):
            budget_mode()


# the query_budget fixture


def test_query_budget_fixture_passes_within_the_limit(query_budget: Any) -> None:
    with query_budget(1) as recorder:
        list(Publisher.objects.all())
    assert recorder.count == 1


def test_query_budget_fixture_fails_over_the_limit(query_budget: Any) -> None:
    Publisher.objects.create(name="a")
    Publisher.objects.create(name="b")
    with pytest.raises(QueryBudgetExceeded, match=r"report ran 3 queries; budget is 1"):
        with query_budget(1, label="report"):
            for publisher in Publisher.objects.all():
                list(publisher.writers.all())


def test_query_budget_is_reexported_from_karni_testing() -> None:
    import karni.testing
    from karni.testing.performance import query_budget

    assert karni.testing.query_budget is query_budget


# QueryLogMiddleware


def test_query_log_is_dropped_when_disabled() -> None:
    with override_settings(KARNI_QUERY_LOG=False):
        with pytest.raises(MiddlewareNotUsed):
            QueryLogMiddleware(lambda request: HttpResponse())


def test_query_log_prints_count_duplicates_and_time(caplog: pytest.LogCaptureFixture) -> None:
    Publisher.objects.create(name="a")
    Publisher.objects.create(name="b")

    def view(request: HttpRequest) -> HttpResponse:
        for publisher in Publisher.objects.all():
            list(publisher.writers.all())
        return HttpResponse("ok")

    with override_settings(KARNI_QUERY_LOG=True):
        middleware = QueryLogMiddleware(view)
    with caplog.at_level(logging.INFO, logger="karni.queries"):
        middleware(RequestFactory().get("/publishers/?page=1"))
    (record,) = caplog.records
    assert record.levelno == logging.WARNING  # duplicates present
    message = record.getMessage()
    assert message.startswith("GET /publishers/?page=1 200 — 3 queries, 2 duplicated")
    assert "ms in SQL" in message and "ms total" in message
    assert "2× SELECT … FROM" in message


def test_query_log_is_silent_without_queries(caplog: pytest.LogCaptureFixture) -> None:
    with override_settings(KARNI_QUERY_LOG=True):
        middleware = QueryLogMiddleware(lambda request: HttpResponse())
    with caplog.at_level(logging.INFO, logger="karni.queries"):
        middleware(RequestFactory().get("/"))
    assert caplog.records == []


def test_dev_profile_warns_and_logs_prod_is_off(make_settings: Any) -> None:
    dev, prod = make_settings("dev"), make_settings("prod")
    assert dev["KARNI_QUERY_BUDGET_MODE"] == "warn" and dev["KARNI_QUERY_LOG"] is True
    assert prod["KARNI_QUERY_BUDGET_MODE"] == "off" and prod["KARNI_QUERY_LOG"] is False
    # Outermost but for RequestIdMiddleware (no SQL; it gives the log line its id).
    assert dev["MIDDLEWARE"][:2] == [
        "karni.tracing.RequestIdMiddleware",
        "karni.middleware.QueryLogMiddleware",
    ]
