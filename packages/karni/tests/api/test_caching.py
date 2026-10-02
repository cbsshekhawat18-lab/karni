"""Response caching for BaseViewSet list/retrieve: off by default, one setting, auto-invalidated."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache as default_cache
from django.core.exceptions import ImproperlyConfigured
from django.test.utils import override_settings
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.api import Access, Authenticated, BaseViewSet, Cache, Owned, Public, Uncached
from karni.api.caching import invalidate
from karni.performance import record_queries
from tests.perfapp.models import Chapter, Genre, Novel, Publisher, Writer

pytestmark = pytest.mark.django_db

OPEN = Access(read=Public(), write=Authenticated())


class NovelSerializer(serializers.ModelSerializer):
    writer = serializers.SlugRelatedField(slug_field="name", read_only=True)
    genres = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    chapter_count = serializers.SerializerMethodField()

    class Meta:
        model = Novel
        fields = ["id", "title", "writer", "genres", "chapter_count"]

    def get_chapter_count(self, novel: Novel) -> int:
        return len(novel.chapters.all())


class NovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = NovelSerializer
    prefetch_related = ["chapters"]
    cache: ClassVar[Cache | Uncached | None] = Cache(depends_on=(Chapter,))
    auto_register = False


@pytest.fixture(autouse=True)
def _cache_on() -> Iterator[None]:
    default_cache.clear()
    with override_settings(KARNI_API_CACHE=True):
        yield
    default_cache.clear()


@pytest.fixture
def novel() -> Novel:
    writer = Writer.objects.create(name="Ann", publisher=Publisher.objects.create(name="P"))
    return Novel.objects.create(title="One", writer=writer, status="out")


def _get(viewset: type[Any], action: str = "list", user: Any = None, **kwargs: Any) -> Any:
    request = APIRequestFactory().get("/")
    if user is not None:
        force_authenticate(request, user=user)
    with record_queries() as recorder:
        response = viewset.as_view({"get": action})(request, **kwargs)
    response.queries = recorder.count
    return response


def test_caching_is_off_by_default(novel: Novel) -> None:
    with override_settings(KARNI_API_CACHE=False):
        assert "X-Karni-Cache" not in _get(NovelViewSet)


def test_list_is_served_from_the_cache(novel: Novel) -> None:
    first = _get(NovelViewSet)
    assert first["X-Karni-Cache"] == "miss" and first.queries > 0
    second = _get(NovelViewSet)
    assert second["X-Karni-Cache"] == "hit"
    assert second.queries == 0
    assert second.data == first.data


def test_save_and_delete_invalidate_lists(novel: Novel) -> None:
    _get(NovelViewSet)
    novel.title = "Renamed"
    novel.save()
    response = _get(NovelViewSet)
    assert response["X-Karni-Cache"] == "miss"
    assert response.data["results"][0]["title"] == "Renamed"
    novel.delete()  # soft delete: a save, so it invalidates too
    assert _get(NovelViewSet).data["count"] == 0


def test_writes_to_related_models_invalidate(novel: Novel) -> None:
    _get(NovelViewSet)
    writer = novel.writer
    writer.name = "Bea"
    writer.save()  # the serializer reads Writer (slug field)
    assert _get(NovelViewSet).data["results"][0]["writer"] == "Bea"
    novel.genres.add(Genre.objects.create(name="noir"))  # m2m_changed
    assert _get(NovelViewSet).data["results"][0]["genres"] == ["noir"]
    Chapter.objects.create(novel=novel, number=1, title="c1")  # declared depends_on
    assert _get(NovelViewSet).data["results"][0]["chapter_count"] == 1


def test_detail_keys_use_the_canonical_pk(novel: Novel) -> None:
    _get(NovelViewSet, "retrieve", pk=str(novel.pk).upper())
    novel.title = "Changed"
    novel.save()
    response = _get(NovelViewSet, "retrieve", pk=str(novel.pk).upper())
    assert response["X-Karni-Cache"] == "miss" and response.data["title"] == "Changed"


def test_detail_invalidation_is_per_row(novel: Novel) -> None:
    other = Novel.objects.create(title="Two", writer=novel.writer, status="out")
    _get(NovelViewSet, "retrieve", pk=str(novel.pk))
    other.title = "Two!"
    other.save()
    assert _get(NovelViewSet, "retrieve", pk=str(novel.pk))["X-Karni-Cache"] == "hit"
    novel.title = "One!"
    novel.save()
    response = _get(NovelViewSet, "retrieve", pk=str(novel.pk))
    assert response["X-Karni-Cache"] == "miss" and response.data["title"] == "One!"


def test_entries_never_cross_users(novel: Novel) -> None:
    class OwnNovels(BaseViewSet):
        model = Novel
        access = Access(read=Owned("created_by"), write=Authenticated())
        auto_register = False

    users = get_user_model()
    ann = users.objects.create_user(email="ann@example.com", password="pw-123456789")
    bob = users.objects.create_user(email="bob@example.com", password="pw-123456789")
    Novel.objects.filter(pk=novel.pk).update(created_by=ann)
    invalidate(Novel)  # QuerySet.update() sends no signal
    assert _get(OwnNovels, user=ann).data["count"] == 1
    response = _get(OwnNovels, user=bob)
    assert response["X-Karni-Cache"] == "miss" and response.data["count"] == 0
    assert _get(OwnNovels, user=ann)["X-Karni-Cache"] == "hit"


def test_uncached_opts_out_with_a_reason(novel: Novel) -> None:
    class Live(NovelViewSet):
        cache = Uncached(reason="stock levels change every second")

    assert "X-Karni-Cache" not in _get(Live)
    with pytest.raises(ImproperlyConfigured, match="reason"):
        Uncached(reason="")


def test_retrieve_with_extra_permissions_is_not_cached(novel: Novel) -> None:
    class Guarded(NovelViewSet):
        permission_classes = (IsAuthenticated,)

    user = get_user_model().objects.create_user(email="u@example.com", password="pw-123456789")
    assert "X-Karni-Cache" not in _get(Guarded, "retrieve", user=user, pk=str(novel.pk))
    assert _get(Guarded, user=user)["X-Karni-Cache"] == "miss"  # lists still are


def test_declaration_validation() -> None:
    with pytest.raises(ImproperlyConfigured, match="positive integer"):
        Cache(ttl=0)
    with pytest.raises(ImproperlyConfigured, match="Cache"):

        class Wrong(BaseViewSet):
            model = Novel
            access = OPEN
            cache = 60  # type: ignore[assignment]
            auto_register = False


def test_invalidate_is_a_noop_when_disabled() -> None:
    with override_settings(KARNI_API_CACHE=False):
        invalidate(Novel)
    assert default_cache.get("karni:api:v:perfapp.novel") is None
