"""What the storefront reads besides karni.yaml's fields: a product's price today, what
is left and every picture."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


def image_url(context: dict[str, Any], image: Any) -> str | None:
    if not image:
        return None
    request = context.get("request")
    url = str(image.url)
    return request.build_absolute_uri(url) if request is not None else url


class ProductImageSerializer(serializers.Serializer[Any]):
    image = serializers.CharField()
    alt = serializers.CharField()


class ShipInputSerializer(serializers.Serializer[Any]):
    """What sending a parcel takes: its tracking number and the carrier."""

    tracking_number = serializers.CharField(max_length=80)
    carrier = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )
