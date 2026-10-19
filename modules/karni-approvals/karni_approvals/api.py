"""Serializers of the approvals API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from karni_approvals.models import Decision, PendingChange

__all__ = ["DecideSerializer", "DecisionSerializer", "PendingChangeSerializer", "PersonSerializer"]


class PersonSerializer(serializers.Serializer[Any]):
    id = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True, required=False)


class DecisionSerializer(serializers.ModelSerializer[Decision]):
    checker = PersonSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Decision
        fields = ["id", "checker", "verdict", "reason", "created_at"]
        read_only_fields = fields


class PendingChangeSerializer(serializers.ModelSerializer[PendingChange]):
    """One pending change: what, by whom, how far along, and every decision so far."""

    model = serializers.SerializerMethodField()
    maker = PersonSerializer(read_only=True, allow_null=True)
    resolved_by = PersonSerializer(read_only=True, allow_null=True)
    decisions = DecisionSerializer(many=True, read_only=True)

    class Meta:
        model = PendingChange
        fields = [
            "id",
            "model",
            "object_id",
            "action",
            "summary",
            "changes",
            "maker",
            "status",
            "required",
            "approvals",
            "expires_at",
            "escalated_at",
            "resolved_at",
            "resolved_by",
            "reason",
            "decisions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_model(self, pending: PendingChange) -> str:
        return f"{pending.content_type.app_label}.{pending.content_type.model}"


class DecideSerializer(serializers.Serializer[Any]):
    """``POST …/approve/`` and ``…/reject/``: an optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")
