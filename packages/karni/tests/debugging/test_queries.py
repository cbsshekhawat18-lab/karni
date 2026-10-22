"""``karni queries``: the request, the attribution of each repeated query, the fix.

Each viewset in :mod:`tests.debugging.queries_urls` has one N+1 the
optimiser cannot fix by itself (or, for ``source-novels``, none at all). The
report must name the field and relation behind it, say why the optimiser did
not fetch it (from its own blind spots) and print the specific hint.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test.utils import override_settings

from karni.api import diagnose
from karni.api.optimizer import blind_spots, planned_lookups
from karni.exceptions import KarniCommandError, KarniLookupError, KarniValueError
from tests.debugging.queries_urls import (
    LoudWriterSerializer,
    MethodNovelSerializer,
    NestedNovelSerializer,
    SourceNovelSerializer,
)
from tests.perfapp.models import Chapter, Genre, Novel, Publisher, Writer

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("_routes"),
]


@pytest.fixture
def _routes() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.debugging.queries_urls",
        KARNI_API_ROUTER="tests.debugging.queries_urls.get_router",
    ):
        yield


@pytest.fixture
def novels() -> list[Novel]:
    """Four novels, each by its own writer at its own publisher, with three chapters."""
    created = []
    for index in range(4):
        publisher = Publisher.objects.create(name=f"P{index}")
        writer = Writer.objects.create(name=f"W{index}", publisher=publisher)
        novel = Novel.objects.create(title=f"N{index}", writer=writer, status="out")
        novel.genres.add(Genre.objects.get_or_create(name=f"G{index}")[0])
        for number in (1, 2, 3):
            Chapter.objects.create(novel=novel, number=number, title=f"C{number}")
        created.append(novel)
    return created


@pytest.fixture
def reader() -> object:
    return get_user_model().objects.create_user(email="reader@example.com", password="x")


def _cause(report: diagnose.Report, field: str) -> diagnose.Cause:
    found = [cause for cause in report.causes if cause.field == field]
    assert found, report.render()
    return found[0]


def test_method_fields_are_attributed_to_the_relation_they_read(novels: list[Novel]) -> None:
    report = diagnose.run("/api/method-novels/")
    assert report.status == 200
    assert report.view == "MethodNovelViewSet.list"
    publisher = _cause(report, "MethodNovelSerializer.publisher_name")
    assert publisher.count == 4
    assert publisher.relation == "Novel.writer__publisher"
    assert publisher.kind == "method"
    assert "SerializerMethodField (get_publisher_name" in publisher.why
    assert "karni/api/optimizer.py" in publisher.why
    assert 'select_related = ["writer__publisher"] on MethodNovelViewSet' in publisher.fix
    assert publisher.where.startswith("tests/debugging/queries_urls.py:")
    assert publisher.where.endswith("in get_publisher_name")

    count = _cause(report, "MethodNovelSerializer.chapter_count")
    assert count.summary == "Novel.chapters (an aggregate per row)"
    assert 'annotate(count_rows=Count("chapters"))' in count.fix
    assert report.headline().startswith(f"{report.total} queries — 4 from ")


def test_a_filtered_related_manager_is_named(novels: list[Novel]) -> None:
    cause = _cause(diagnose.run("filtered-novels"), "FilteredNovelSerializer.later_chapters")
    assert cause.summary == "Novel.chapters (a filtered query per row)"
    assert ".filter()/.exclude()/.order_by()" in cause.fix
    assert 'Prefetch("chapters", queryset=Chapter.objects.filter(...)' in cause.fix


def test_what_the_optimiser_derives_repeats_nothing(novels: list[Novel]) -> None:
    report = diagnose.run("source-novels")
    assert report.causes == []
    assert report.headline().endswith("no statement repeats")
    assert report.total == len(report.counted) <= 4


def test_a_nested_to_representation_is_a_blind_spot(novels: list[Novel]) -> None:
    cause = _cause(diagnose.run("/api/nested-novels/"), "NestedNovelSerializer.writer")
    assert cause.relation == "Writer.publisher"
    assert cause.kind == "representation"
    assert "rendered by LoudWriterSerializer.to_representation" in cause.why
    assert 'select_related = ["writer__publisher"] on NestedNovelViewSet' in cause.fix


def test_optimize_false_is_named(novels: list[Novel]) -> None:
    report = diagnose.run("UnoptimizedNovelViewSet.list")
    cause = _cause(report, "ChaptersNovelSerializer.chapters")
    assert cause.kind == "unoptimised"
    assert "sets optimize = False" in cause.why
    assert 'prefetch_related = ["chapters"]' in cause.fix


def test_a_custom_action_is_not_optimised(novels: list[Novel]) -> None:
    report = diagnose.run("ActionNovelViewSet.everything")
    assert report.path == "/api/action-novels/everything/"
    cause = _cause(report, "ChaptersNovelSerializer.chapters")
    assert "custom actions are not optimised automatically" in cause.why
    assert "self.paginated_response(queryset)" in cause.fix


def test_a_loop_outside_serialisation_names_its_line(novels: list[Novel]) -> None:
    report = diagnose.run("/api/action-novels/publishers/")
    cause = next(c for c in report.causes if c.kind == "code")
    assert cause.where.startswith("tests/debugging/queries_urls.py:")
    assert cause.where.endswith("in publishers")
    assert "outside serializer rendering" in cause.why


def test_the_report_text_and_json(novels: list[Novel], reader: object) -> None:
    report = diagnose.run("method-novels", user="reader@example.com", explain=True)
    text = report.render()
    assert text.splitlines()[0] == (
        "GET /api/method-novels/ as reader@example.com → 200 · MethodNovelViewSet.list"
    )
    assert "4× Novel.writer__publisher not prefetched" in text
    assert "  field  MethodNovelSerializer.publisher_name" in text
    assert "EXPLAIN SELECT" in text
    assert "force-authenticated" in text
    data = report.as_dict(every=True)
    assert data["request"] == {
        "method": "GET",
        "path": "/api/method-novels/",
        "as": "reader@example.com",
    }
    assert data["budget"] == 8 and data["queries"] == report.total
    assert data["causes"][0]["fix"] and data["explain"]
    assert len(data["statements"]) == report.total
    json.dumps(data)


def test_writes_are_rolled_back(reader: object) -> None:
    writer = Writer.objects.create(name="W", publisher=Publisher.objects.create(name="P"))
    body = json.dumps({"title": "Fresh", "writer": str(writer.pk), "status": "out"})
    report = diagnose.run("source-novels", user="reader@example.com", method="POST", data=body)
    assert report.status == 201, report.render()
    assert not Novel.objects.filter(title="Fresh").exists()
    assert "rolled back" in report.render()


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        ("/api/source-novels/?page=1", "/api/source-novels/?page=1"),
        ("source-novels", "/api/source-novels/"),
        ("source-novels?page=1", "/api/source-novels/?page=1"),
        ("SourceNovelViewSet", "/api/source-novels/"),
        ("http://localhost:8000/api/source-novels/", "/api/source-novels/"),
    ],
)
def test_endpoint_forms(endpoint: str, path: str) -> None:
    assert diagnose.resolve_endpoint(endpoint).path == path


def test_detail_forms(novels: list[Novel]) -> None:
    novel = novels[0]
    target = diagnose.resolve_endpoint(f"source-novels/{novel.pk}")
    assert target.path == f"/api/source-novels/{novel.pk}/"
    assert target.action == "retrieve"
    retrieve = diagnose.resolve_endpoint("SourceNovelViewSet.retrieve")
    assert retrieve.action == "retrieve" and retrieve.path.startswith("/api/source-novels/")


def test_unknown_endpoint_user_method_and_data(reader: object) -> None:
    with pytest.raises(KarniLookupError) as endpoint:
        diagnose.run("nowhere")
    assert endpoint.value.code == "E940" and "method-novels" in endpoint.value.message
    with pytest.raises(KarniLookupError) as user:
        diagnose.run("source-novels", user="nobody@example.com")
    assert user.value.code == "E941" and "reader@example.com" in user.value.message
    with pytest.raises(KarniValueError) as method:
        diagnose.run("source-novels", method="FETCH")
    assert method.value.code == "E942"
    with pytest.raises(KarniValueError) as data:
        diagnose.run("source-novels", method="POST", data="{nope")
    assert data.value.code == "E942"
    with pytest.raises(KarniValueError) as verb:
        diagnose.run("/api/action-novels/everything/", method="DELETE")
    assert verb.value.code == "E942" and "GET" in verb.value.message


def test_a_view_that_raises_is_explained() -> None:
    with pytest.raises(KarniCommandError) as info:
        call_command("karni_queries", "/api/action-novels/broken/")
    assert info.value.code == "E943"
    assert "ZeroDivisionError: division by zero" in info.value.message
    assert "Not a failure Karni recognises" in info.value.message


def test_the_management_command(novels: list[Novel]) -> None:
    out = StringIO()
    call_command("karni_queries", "method-novels", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert data["causes"][0]["count"] == 4
    text = StringIO()
    call_command("karni_queries", "method-novels", "--all", stdout=text)
    assert "MethodNovelViewSet.list" in text.getvalue()
    with pytest.raises(KarniCommandError) as info:
        call_command("karni_queries", "nowhere")
    assert info.value.code == "E940"


def test_the_optimiser_records_its_blind_spots() -> None:
    spots = {
        (prefix, spot.label, spot.kind)
        for prefix, spot in blind_spots(MethodNovelSerializer, Novel)
    }
    assert spots == {
        ("", "MethodNovelSerializer.publisher_name", "method"),
        ("", "MethodNovelSerializer.chapter_count", "method"),
    }
    nested = {(p, s.label, s.kind) for p, s in blind_spots(NestedNovelSerializer, Novel)}
    assert ("writer__", "LoudWriterSerializer", "representation") in nested
    assert blind_spots(SourceNovelSerializer, Novel) == []
    assert planned_lookups(SourceNovelSerializer, Novel) == {
        "writer",
        "writer__publisher",
        "chapters",
    }
    assert blind_spots(LoudWriterSerializer, Writer)[0][1].kind == "representation"
