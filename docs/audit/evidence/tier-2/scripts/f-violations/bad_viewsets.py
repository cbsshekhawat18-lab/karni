import requests  # K105
from django.contrib import admin
from django.db import connection, models
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from karni.api import Access, Authenticated, BaseViewSet
from shop.models import Event, Venue


class Plain(models.Model):  # K101
    name = models.CharField(max_length=10)


class VenueViewSet(BaseViewSet):  # K109: no access
    model = Venue


class LegacyViewSet(ModelViewSet):  # K102
    queryset = Event.objects.all()


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Authenticated(), write=Authenticated())

    def filter_queryset_for_user(self, queryset):  # K110: no opt-out reason
        return queryset

    @action(detail=False)
    def recent(self, request):  # K111: unpaginated many=True
        return Response(self.get_serializer(Event.objects.all(), many=True).data)

    def stats(self):
        with connection.cursor() as cur:  # K104
            cur.execute("SELECT 1")


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):  # K103
    list_display = ["name"]
