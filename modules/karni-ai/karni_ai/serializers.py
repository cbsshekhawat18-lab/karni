"""The request body of ``POST /api/ai/extract/``."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

__all__ = ["ExtractSerializer"]


class ExtractSerializer(serializers.Serializer[Any]):
    """Experimental. ``resource`` (a router prefix) and exactly one of ``text``, ``url``, ``file``.

    ``file`` is a PDF upload (multipart). Which one is given, and its limits,
    are checked by :func:`karni_ai.sources.read_source` (AI010).
    """

    resource = serializers.CharField(max_length=100)
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    file = serializers.FileField(required=False, allow_empty_file=False)
