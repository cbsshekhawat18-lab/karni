"""The N+1 scaling check (karni.testing.performance) — 2 rows vs 12, queries must not grow."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db.models import Q
from rest_framework import serializers

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Owned, Public, Where
from karni.testing import _source, architecture, performance
from karni.testing.performance import ScalingCase, check_scaling, scaling_cases
from tests.perfapp.models import Chapter, Novel, Writer
from tests.testapp.models import Event

OPEN = Access(read=Public(), write=Authenticated())


class ChapterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chapter
        fields = ["id", "number"]


class NovelSerializer(serializers.ModelSerializer):
    chapters = ChapterSerializer(many=True, read_only=True)
    genres = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Novel
        fields = ["id", "title", "chapters", "genres"]


class WriterSerializer(serializers.ModelSerializer):
    novels = NovelSerializer(many=True, read_only=True)

    class Meta:
        model = Writer
        fields = ["id", "name", "novels"]


class NovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = NovelSerializer
    auto_register = False


class LeakyNovelViewSet(NovelViewSet):
    optimize = False


class WriterViewSet(BaseViewSet):
    model = Writer
    access = OPEN
    serializer_class = WriterSerializer
    auto_register = False


class LeakyWriterViewSet(WriterViewSet):
    optimize = False


# --- measuring -------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["list", "retrieve"])
def test_an_optimised_viewset_is_flat(action: str) -> None:
    result = check_scaling(ScalingCase(WriterViewSet, action))
    assert not result.skipped, result.skipped
    assert not result.grows and result.small == result.large


@pytest.mark.django_db
def test_an_n_plus_one_list_is_caught() -> None:
    result = check_scaling(ScalingCase(LeakyNovelViewSet, "list"))
    assert result.grows
    assert result.large - result.small == 2 * (12 - 2)  # chapters + genres per extra row
    message = result.message()
    assert "LeakyNovelViewSet.list: " in message and "(N+1)" in message
    assert "10× SELECT" in message or "12× SELECT" in message
    assert "# karni: allow(query-scaling): <reason>" in message


@pytest.mark.django_db
def test_an_n_plus_one_retrieve_is_caught_through_nested_rows() -> None:
    # retrieve renders 2 vs 12 novels, each with its own chapters and genres.
    result = check_scaling(ScalingCase(LeakyWriterViewSet, "retrieve"))
    assert result.grows and not result.skipped


@pytest.mark.django_db
def test_the_requester_owns_owned_rows() -> None:
    class MyEvents(BaseViewSet):
        model = Event
        access = Access(read=Owned("organizer"), write=Authenticated())
        auto_register = False

    result = check_scaling(ScalingCase(MyEvents, "list"))
    assert not result.skipped and not result.grows


@pytest.mark.django_db
def test_the_requester_holds_the_named_roles() -> None:
    class StaffNovels(NovelViewSet):
        access = Access(read=HasRole("editors"), write=HasRole("editors"))

    result = check_scaling(ScalingCase(StaffNovels, "list"))
    assert not result.skipped and not result.grows


@pytest.mark.django_db
def test_invisible_rows_skip_with_the_reason() -> None:
    class Nothing(NovelViewSet):
        access = Access(read=Where(lambda request: Q(title="never")), write=Authenticated())

    result = check_scaling(ScalingCase(Nothing, "list"))
    assert "of 12 seeded rows are visible" in result.skipped
    detail = check_scaling(ScalingCase(Nothing, "retrieve"))
    assert "answered 404" in detail.skipped


# --- the default wiring --------------------------------------------------------------------


@pytest.mark.django_db
def test_every_routed_testapp_viewset_is_n_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real router + generated serializers: Event's M2M list no longer grows (F7)."""
    real = [django_apps.get_app_config("testapp")]
    monkeypatch.setattr(_source, "project_app_configs", lambda: real)
    cases = scaling_cases()
    assert {case.id for case in cases} >= {
        "EventViewSet.list",
        "EventViewSet.retrieve",
        "VenueViewSet.list",
        "OrganizerViewSet.list",
    }
    for case in cases:
        result = check_scaling(case)
        assert not result.skipped, result.skipped
        assert not result.grows, result.message()


def test_no_project_apps_means_no_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_source, "project_app_configs", lambda: [])
    assert scaling_cases() == []


SOURCE = """
from karni.api import Access, Authenticated, BaseViewSet, Public
from tests.perfapp.models import Novel


# karni: allow(query-scaling): renders a live stock price per row from a service
class Priced(BaseViewSet):
    model = Novel
    access = Access(read=Public(), write=Authenticated())
    auto_register = False


# karni: allow(query-scaling):
class Unexplained(BaseViewSet):
    model = Novel
    access = Access(read=Public(), write=Authenticated())
    auto_register = False
"""


def test_optout_marker_needs_a_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scaling_viewsets.py"
    path.write_text(SOURCE)
    spec = importlib.util.spec_from_file_location("scaling_viewsets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "scaling_viewsets", module)
    spec.loader.exec_module(module)
    _source._file_lines.cache_clear()
    assert performance._optout(module.Priced) == (True, "")
    opted, error = performance._optout(module.Unexplained)
    assert not opted and "requires a non-empty reason" in error
    with pytest.raises(AssertionError, match="opt-out-reason"):
        performance.test_list_and_retrieve_queries_do_not_grow_with_rows(
            None, ScalingCase(module.Unexplained, "list", error)
        )


@pytest.mark.django_db
def test_the_suite_test_fails_on_an_n_plus_one() -> None:
    with pytest.raises(AssertionError, match=r"\(N\+1\)"):
        performance.test_list_and_retrieve_queries_do_not_grow_with_rows(
            None, ScalingCase(LeakyNovelViewSet, "list")
        )


def test_generate_tests_parametrises_the_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    case = ScalingCase(NovelViewSet, "list")
    monkeypatch.setattr(performance, "scaling_cases", lambda: [case])
    calls: list[tuple[Any, ...]] = []
    metafunc = SimpleNamespace(
        fixturenames=["db", "karni_scaling_case"],
        parametrize=lambda *args, **kwargs: calls.append((*args, kwargs)),
    )
    performance.pytest_generate_tests(metafunc)
    assert calls == [("karni_scaling_case", [case], {"ids": ["NovelViewSet.list"]})]


def test_the_architecture_suite_carries_the_scaling_check() -> None:
    name = "test_list_and_retrieve_queries_do_not_grow_with_rows"
    assert getattr(architecture, name) is getattr(performance, name)
    assert architecture.pytest_generate_tests is performance.pytest_generate_tests
