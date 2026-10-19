"""The history entry as the API renders it."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from karni.audit.models import ChangeLog

__all__ = ["ChangeLogSerializer"]


class ActorSerializer(serializers.Serializer[Any]):
    id = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True, required=False)


class ChangeLogSerializer(serializers.ModelSerializer[ChangeLog]):
    """One change: when, by whom, what kind, and the fields that changed.

    ``diff`` is ``{field: [old, new]}`` minus the fields ``Karni.field_roles``
    hides from the requesting user (P3), so history never shows a value the
    row itself would not.
    """

    actor = ActorSerializer(read_only=True, allow_null=True)
    diff = serializers.SerializerMethodField()
    fields_changed = serializers.SerializerMethodField()

    class Meta:
        model = ChangeLog
        fields = ["id", "timestamp", "actor", "action", "diff", "fields_changed"]
        read_only_fields = fields

    def _user(self) -> Any:
        request = self.context.get("request") if isinstance(self.context, dict) else None
        return getattr(request, "user", None)

    def get_diff(self, entry: ChangeLog) -> dict[str, Any]:
        return entry.visible_diff(self._user())

    def get_fields_changed(self, entry: ChangeLog) -> list[str]:
        return sorted(self.get_diff(entry))
