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


class VariationViewSerializer(serializers.Serializer[Any]):
    """A variation as the product page reads it: its values, price and what is left."""

    id = serializers.CharField()
    sku = serializers.CharField()
    label = serializers.CharField()
    values = serializers.DictField(child=serializers.CharField())
    price = serializers.CharField()
    current_price = serializers.CharField()
    on_sale = serializers.BooleanField()
    available = serializers.IntegerField(allow_null=True)
    image = serializers.CharField(allow_null=True)


class OptionSerializer(serializers.Serializer[Any]):
    """An option of a product (Size) with the values its variations use."""

    name = serializers.CharField()
    values = serializers.ListField(child=serializers.CharField())


class EligibilitySerializer(serializers.Serializer[Any]):
    """Whether the reader may review a product, and where their review stands."""

    can_review = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)
    status = serializers.CharField(allow_null=True)
