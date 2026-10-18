"""The serializer-walking optimiser (ADR 0001 Q3.1) — N+1 eliminated, three levels deep.

``PublisherSerializer`` nests writers → novels → chapters (+ an M2M PK list and
an M2M slug list at the third level), all hand-written serializers, none of
them known to Karni. The same viewset with ``optimize = False`` is the
baseline: its query count grows with every row; the optimised one does not.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import Prefetch
from django.test.utils import override_settings
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from karni.api import Access, Authenticated, BaseViewSet, Public
from karni.api.optimizer import Plan, optimize, plan_for
from karni.performance import record_queries
from tests.perfapp.models import Chapter, Genre, Novel, Publisher, Writer
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db

OPEN = Access(read=Public(), write=Authenticated())


class ChapterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chapter
        fields = ["id", "number", "title"]


class NovelSerializer(serializers.ModelSerializer):
    chapters = ChapterSerializer(many=True, read_only=True)
    genres = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    genre_names = serializers.SlugRelatedField(
        source="genres", slug_field="name", many=True, read_only=True
    )

    class Meta:
        model = Novel
        fields = ["id", "title", "chapters", "genres", "genre_names"]


class WriterSerializer(serializers.ModelSerializer):
    novels = NovelSerializer(many=True, read_only=True)

    class Meta:
        model = Writer
        fields = ["id", "name", "novels"]


class PublisherSerializer(serializers.ModelSerializer):
    writers = WriterSerializer(many=True, read_only=True)

    class Meta:
        model = Publisher
        fields = ["id", "name", "writers"]


class PublisherBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Publisher
        fields = ["id", "name"]


class WriterBriefSerializer(serializers.ModelSerializer):
    publisher = PublisherBriefSerializer(read_only=True)

    class Meta:
        model = Writer
        fields = ["id", "name", "publisher"]


class NovelBriefSerializer(serializers.ModelSerializer):
    writer = WriterBriefSerializer(read_only=True)

    class Meta:
        model = Novel
        fields = ["id", "title", "writer"]


class ChapterDetailSerializer(serializers.ModelSerializer):
    novel = NovelBriefSerializer(read_only=True)
    publisher_name = serializers.CharField(source="novel.writer.publisher.name", read_only=True)

    class Meta:
        model = Chapter
        fields = ["id", "title", "novel", "publisher_name"]


class PublisherViewSet(BaseViewSet):
    model = Publisher
    access = OPEN
    serializer_class = PublisherSerializer
    auto_register = False


class UnoptimizedPublisherViewSet(PublisherViewSet):
    optimize = False


class ChapterViewSet(BaseViewSet):
    model = Chapter
    access = OPEN
    serializer_class = ChapterDetailSerializer
    auto_register = False


class UnoptimizedChapterViewSet(ChapterViewSet):
    optimize = False


def _seed(publishers: int) -> None:
    """Each publisher: 2 writers × 2 novels × (2 chapters + 2 genres)."""
    for p in range(publishers):
        publisher = Publisher.objects.create(name=f"P{p}-{Publisher.objects.count()}")
        for w in range(2):
            writer = Writer.objects.create(name=f"W{w}", publisher=publisher)
            for n in range(2):
                novel = Novel.objects.create(title=f"N{n}", writer=writer, status="out")
                novel.genres.add(
                    *(Genre.objects.create(name=f"g-{novel.pk}-{g}") for g in range(2))
                )
                for c in range(2):
                    Chapter.objects.create(novel=novel, number=c + 1, title=f"C{c}")


def _count(viewset: type[Any], action: str = "list", **kwargs: Any) -> tuple[int, Any]:
    view = viewset.as_view({"get": action})
    with override_settings(KARNI_QUERY_BUDGET_MODE="off"), record_queries() as recorder:
        response = view(APIRequestFactory().get("/"), **kwargs)
    assert response.status_code == 200, response.data
    return recorder.count, response


def _counts_at(viewset: type[Any], small: int = 2, large: int = 12) -> tuple[int, int]:
    _seed(small)
    at_small, _ = _count(viewset)
    _seed(large - small)
    at_large, response = _count(viewset)
    assert response.data["count"] == large
    return at_small, at_large


# the proof


def test_three_level_nesting_is_n_plus_one_without_the_optimizer() -> None:
    small, large = _counts_at(UnoptimizedPublisherViewSet)

    def expected(publishers: int) -> int:
        # COUNT + publishers, then one query per publisher (its writers), per
        # writer (its novels) and three per novel (chapters, genre PKs, genre names).
        return 2 + publishers + 2 * publishers + 3 * (4 * publishers)

    assert small == expected(2) == 32
    assert large == expected(12) == 182


def test_three_level_nesting_is_flat_with_the_optimizer() -> None:
    small, large = _counts_at(PublisherViewSet)
    # COUNT, publishers, writers, novels, chapters, genres — one query per level,
    # whatever the row count (the two genres fields share one full-row prefetch).
    assert small == large == 6


def test_optimised_output_equals_unoptimised_output() -> None:
    _seed(3)
    _, optimised = _count(PublisherViewSet)
    _, baseline = _count(UnoptimizedPublisherViewSet)
    assert optimised.data == baseline.data
    first_novel = optimised.data["results"][0]["writers"][0]["novels"][0]
    assert [chapter["number"] for chapter in first_novel["chapters"]] == [1, 2]
    assert len(first_novel["genres"]) == len(first_novel["genre_names"]) == 2


def test_three_level_to_one_chain_is_joined() -> None:
    _seed(2)
    small, _ = _count(ChapterViewSet)
    _seed(10)
    large, response = _count(ChapterViewSet)
    # COUNT + one SELECT joining novel → writer → publisher.
    assert small == large == 2
    row = response.data["results"][0]
    assert row["publisher_name"] == row["novel"]["writer"]["publisher"]["name"]
    baseline, _ = _count(UnoptimizedChapterViewSet)
    assert baseline > 2 + Chapter.objects.count()  # one per row, per level


def test_retrieve_is_optimised_too() -> None:
    _seed(1)
    publisher = Publisher.objects.get()
    optimised, response = _count(PublisherViewSet, "retrieve", pk=str(publisher.pk))
    baseline, _ = _count(UnoptimizedPublisherViewSet, "retrieve", pk=str(publisher.pk))
    assert optimised == 5  # publisher, writers, novels, chapters, genres
    assert baseline > optimised
    assert len(response.data["writers"]) == 2


# the plan


def test_plan_follows_sources_and_merges_relations() -> None:
    plan = plan_for(PublisherSerializer, Publisher)
    novels = plan.to_many["writers"].plan
    assert isinstance(novels, Plan)
    novel_plan = novels.to_many["novels"].plan
    assert novel_plan is not None
    assert set(novel_plan.to_many) == {"chapters", "genres"}
    # The PK list alone would prefetch .only("pk"); the slug list needs full rows.
    assert novel_plan.to_many["genres"].only == ()
    assert plan.models == {Publisher, Writer, Novel, Chapter, Genre}


def test_pk_list_prefetch_loads_only_the_pk() -> None:
    class Ids(serializers.ModelSerializer):
        genres = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

        class Meta:
            model = Novel
            fields = ["id", "genres"]

    plan = plan_for(Ids, Novel)
    assert plan.to_many["genres"].only == ("pk",)
    queryset = optimize(Novel.objects.all(), Ids)
    (lookup,) = queryset._prefetch_related_lookups
    assert isinstance(lookup, Prefetch)
    assert lookup.queryset.query.deferred_loading == ({Genre._meta.pk.name}, False)


def test_reverse_fk_pk_list_also_loads_the_fk_column() -> None:
    class Ids(serializers.ModelSerializer):
        chapters = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

        class Meta:
            model = Novel
            fields = ["id", "chapters"]

    assert plan_for(Ids, Novel).to_many["chapters"].only == ("pk", "novel")


def test_forward_pk_fields_and_columns_need_nothing() -> None:
    class Flat(serializers.ModelSerializer):
        writer_id = serializers.CharField(read_only=True)

        class Meta:
            model = Novel
            fields = ["id", "title", "writer", "writer_id", "status"]

    plan = plan_for(Flat, Novel)
    assert plan.to_one == {} and plan.to_many == {}


def test_opaque_fields_use_hints() -> None:
    class Opaque(serializers.ModelSerializer):
        chapter_count = serializers.SerializerMethodField()

        class Meta:
            model = Novel
            fields = ["id", "chapter_count"]

        def get_chapter_count(self, novel: Novel) -> int:
            return len(novel.chapters.all())

    plan = plan_for(Opaque, Novel)
    assert plan.to_many == {}
    hinted = optimize(Novel.objects.all(), Opaque, prefetch=["chapters"])
    assert "chapters" in hinted._prefetch_related_lookups


def test_api_meta_select_hint_applies_at_every_level() -> None:
    # Novel.APIMeta.select = ["writer"] (for the writer_name property).
    root = optimize(Novel.objects.all(), None)
    assert root.query.select_related == {"writer": {}}
    nested = optimize(Writer.objects.all(), WriterSerializer)
    (novels,) = nested._prefetch_related_lookups
    assert novels.queryset.query.select_related == {"writer": {}}


def test_explicit_lookups_win_over_derived_ones() -> None:
    custom = Prefetch("writers", queryset=Writer.objects.filter(name="W0"))
    queryset = optimize(Publisher.objects.prefetch_related(custom), PublisherSerializer)
    assert list(queryset._prefetch_related_lookups) == [custom]
    # A hint string on the same level replaces the derived Prefetch there.
    hinted = optimize(Publisher.objects.all(), PublisherSerializer, prefetch=["writers__novels"])
    assert list(hinted._prefetch_related_lookups) == ["writers__novels"]


def test_optimize_is_idempotent() -> None:
    once = optimize(Publisher.objects.all(), PublisherSerializer)
    twice = optimize(once, PublisherSerializer)
    assert len(twice._prefetch_related_lookups) == len(once._prefetch_related_lookups)


# viewset declarations


def test_unexpanded_m2m_pk_list_on_a_generated_serializer_is_prefetched() -> None:
    """F7: every list of a model with an M2M was N+1 out of the box."""
    from django.utils import timezone

    from tests.testapp.models import Tag
    from tests.testapp.viewsets import EventViewSet

    tag = Tag.objects.create(name="t")
    for index in range(5):
        Event.objects.create(title=f"E{index}", starts_at=timezone.now()).tags.add(tag)
    count, response = _count(EventViewSet)
    assert count == 3  # COUNT, events, tags (pk only)
    assert all(row["tags"] == [tag.pk] for row in response.data["results"])


def test_viewset_hints_are_validated_at_class_definition() -> None:
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="list of lookups"):

        class Bad(BaseViewSet):
            model = Publisher
            access = OPEN
            prefetch_related = "writers"
            auto_register = False

    with pytest.raises(ImproperlyConfigured, match="optimize"):

        class AlsoBad(BaseViewSet):
            model = Publisher
            access = OPEN
            optimize = "yes"  # type: ignore[assignment]
            auto_register = False


# prefetches obey the target's read scope (ADR 0001 R3, Q2.5)


def test_nested_to_one_into_a_row_scoped_target_is_a_scoped_prefetch() -> None:
    """Users are readable by authenticated callers only (OrganizerViewSet)."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from rest_framework.test import force_authenticate

    class OrganizerBrief(serializers.ModelSerializer):
        class Meta:
            model = get_user_model()
            fields = ["id", "email"]

    class EventWithOrganizer(serializers.ModelSerializer):
        organizer = OrganizerBrief(read_only=True)

        class Meta:
            model = Event
            fields = ["id", "title", "organizer"]

    class Events(BaseViewSet):
        model = Event
        access = OPEN
        serializer_class = EventWithOrganizer
        auto_register = False

    user = get_user_model().objects.create_user(email="o@example.com", password="pw-123456789")
    Event.objects.create(title="E", starts_at=timezone.now(), organizer=user)
    anonymous = Events.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert anonymous.data["results"][0]["organizer"] is None
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    signed_in = Events.as_view({"get": "list"})(request)
    assert signed_in.data["results"][0]["organizer"]["email"] == "o@example.com"


# the expansion helpers it replaces


def test_expansion_lookup_helpers_are_deprecated() -> None:
    from karni.api.expansion import related_lookups, scoped_related_lookups
    from karni.deprecation import KarniDeprecationWarning

    with pytest.warns(KarniDeprecationWarning, match="optimizer.optimize"):
        assert related_lookups(Event, {"venue"}) == (["venue"], [])
    with pytest.warns(KarniDeprecationWarning, match="scoped_related_lookups"):
        select, prefetch = scoped_related_lookups(
            Event, {"tags"}, lambda model: (model._default_manager.all(), False)
        )
    assert select == [] and [p.prefetch_to for p in prefetch] == ["tags"]
