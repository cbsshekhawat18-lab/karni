"""A hand-written serializer duplicating the generated one (K106)."""
from rest_framework import serializers

from shop.models import Venue


class VenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "city", "capacity"]
