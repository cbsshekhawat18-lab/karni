"""redundant-serializer (K106) also covers Karni's own serializer base.

A Meta-only subclass of ``KarniModelSerializer`` duplicates the generated
serializer exactly like one of DRF's ``ModelSerializer``; both the static
single-file check and the runtime architecture check must flag it.
"""

from __future__ import annotations

from rest_framework import serializers

from karni.agent.check import check_source
from karni.api.serializers import KarniModelSerializer
from karni.testing.architecture import _is_meta_only
from tests.testapp.models import Venue

META_ONLY = """
from karni.api.serializers import KarniModelSerializer

class VenueSerializer(KarniModelSerializer):
    class Meta:
        model = Venue
        fields = "__all__"
"""


def test_static_check_flags_meta_only_karni_serializer() -> None:
    codes = [f.code for f in check_source("events/serializers.py", META_ONLY)]
    assert "K106" in codes


def test_static_check_ignores_karni_serializer_with_behaviour() -> None:
    with_method = META_ONLY + "\n    def validate_name(self, value):\n        return value\n"
    codes = [f.code for f in check_source("events/serializers.py", with_method)]
    assert "K106" not in codes


def test_runtime_meta_only_walk_stops_at_karni_bases() -> None:
    class VenueSerializer(KarniModelSerializer):
        class Meta:
            model = Venue
            fields = "__all__"

    class VenueWithField(KarniModelSerializer):
        extra = serializers.CharField()

        class Meta:
            model = Venue
            fields = "__all__"

    assert _is_meta_only(VenueSerializer, serializers.ModelSerializer) is True
    assert _is_meta_only(VenueWithField, serializers.ModelSerializer) is False
