"""Request bodies of the import endpoints, and the job state as the schema documents it."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

__all__ = [
    "ImportColumnSerializer",
    "ImportDescribeSerializer",
    "ImportJobSerializer",
    "ImportMappingSerializer",
    "ImportUploadSerializer",
]


class ImportUploadSerializer(serializers.Serializer[Any]):
    """``POST /<resource>/import/``: the file, optionally with a mapping."""

    file = serializers.FileField()
    mapping = serializers.JSONField(required=False)


class ImportMappingSerializer(serializers.Serializer[Any]):
    """``POST …/import/<job>/preview/``: header → field (``""`` ignores a column)."""

    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)


class ImportColumnSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.CharField()
    required = serializers.BooleanField()
    readable = serializers.BooleanField()
    writable = serializers.BooleanField()
    choices = serializers.ListField(child=serializers.DictField())
    target = serializers.CharField(allow_null=True)
    lookup = serializers.CharField(allow_null=True)
    help = serializers.CharField(allow_blank=True)


class ImportDescribeSerializer(serializers.Serializer[Any]):
    """``GET /<resource>/import/``: the importable fields and the remembered mapping."""

    fields = ImportColumnSerializer(many=True)
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True))
    inline_rows = serializers.IntegerField()
    max_rows = serializers.IntegerField()
    key = serializers.CharField(allow_null=True)


class ImportJobSerializer(serializers.Serializer[Any]):
    """The state of one import job (``services.job_state``)."""

    id = serializers.CharField()
    model = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    file_name = serializers.CharField()
    format = serializers.CharField()
    columns = serializers.ListField(child=serializers.CharField())
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True))
    rows_total = serializers.IntegerField()
    rows_done = serializers.IntegerField()
    async_ = serializers.BooleanField(source="async")
    result = serializers.DictField(allow_null=True)
    problems = serializers.ListField(child=serializers.DictField())
    error = serializers.CharField(allow_null=True)
    batch = serializers.IntegerField(allow_null=True)
    created_at = serializers.CharField(allow_null=True)
    fields = ImportColumnSerializer(many=True, required=False)
