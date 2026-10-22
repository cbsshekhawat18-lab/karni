"""Viewsets with one N+1 each, for the ``karni queries`` suite.

Used with ``override_settings(ROOT_URLCONF=__name__, KARNI_API_ROUTER=
"tests.debugging.queries_urls.get_router")``; none of them sits in an
autodiscovered module, so the project-wide schema snapshot never sees them.
"""

from __future__ import annotations

from typing import Any

from django.urls import include, path
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import Access, Authenticated, BaseViewSet, Public
from karni.api.routers import KarniRouter
from tests.perfapp.models import Chapter, Novel, Writer

OPEN = Access(read=Public(), write=Authenticated())


class ChapterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chapter
        fields = ["id", "number", "title"]


class MethodNovelSerializer(serializers.ModelSerializer):
    """Two method fields: one walks two FKs, one counts a reverse FK."""

    publisher_name = serializers.SerializerMethodField()
    chapter_count = serializers.SerializerMethodField()

    class Meta:
        model = Novel
        fields = ["id", "title", "publisher_name", "chapter_count"]

    def get_publisher_name(self, obj: Novel) -> str:
        return obj.writer.publisher.name

    def get_chapter_count(self, obj: Novel) -> int:
        return obj.chapters.count()


class FilteredNovelSerializer(serializers.ModelSerializer):
    later_chapters = serializers.SerializerMethodField()

    class Meta:
        model = Novel
        fields = ["id", "title", "later_chapters"]

    def get_later_chapters(self, obj: Novel) -> list[str]:
        return [chapter.title for chapter in obj.chapters.filter(number__gt=1)]


class SourceNovelSerializer(serializers.ModelSerializer):
    """Everything through declared relations: the optimiser fetches it all."""

    publisher_name = serializers.CharField(source="writer.publisher.name", read_only=True)
    chapters = ChapterSerializer(many=True, read_only=True)

    class Meta:
        model = Novel
        fields = ["id", "title", "writer", "status", "publisher_name", "chapters"]


class LoudWriterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Writer
        fields = ["id", "name"]

    def to_representation(self, instance: Writer) -> dict[str, Any]:
        data = dict(super().to_representation(instance))
        data["publisher"] = instance.publisher.name
        return data


class NestedNovelSerializer(serializers.ModelSerializer):
    writer = LoudWriterSerializer(read_only=True)

    class Meta:
        model = Novel
        fields = ["id", "title", "writer"]


class ChaptersNovelSerializer(serializers.ModelSerializer):
    chapters = ChapterSerializer(many=True, read_only=True)

    class Meta:
        model = Novel
        fields = ["id", "title", "chapters"]


class MethodNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = MethodNovelSerializer


class FilteredNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = FilteredNovelSerializer


class SourceNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = SourceNovelSerializer


class NestedNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = NestedNovelSerializer


class UnoptimizedNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = ChaptersNovelSerializer
    optimize = False


class ActionNovelViewSet(BaseViewSet):
    model = Novel
    access = OPEN
    serializer_class = ChaptersNovelSerializer

    @action(detail=False)
    def everything(self, request: Request) -> Response:
        """A custom action that serialises without the optimiser."""
        queryset = self.get_queryset()[:50]
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False)
    def publishers(self, request: Request) -> Response:
        """A loop outside serialisation."""
        names = [novel.writer.publisher.name for novel in Novel.objects.all()]
        return Response({"names": names})

    @action(detail=False)
    def broken(self, request: Request) -> Response:
        raise ZeroDivisionError("division by zero")


ROUTES = {
    "method-novels": MethodNovelViewSet,
    "filtered-novels": FilteredNovelViewSet,
    "source-novels": SourceNovelViewSet,
    "nested-novels": NestedNovelViewSet,
    "unoptimized-novels": UnoptimizedNovelViewSet,
    "action-novels": ActionNovelViewSet,
}

router = KarniRouter()
for prefix, viewset in ROUTES.items():
    router.register(prefix, viewset, basename=f"diag-{prefix}")


def get_router() -> KarniRouter:
    return router


urlpatterns = [path("api/", include(router.urls))]
