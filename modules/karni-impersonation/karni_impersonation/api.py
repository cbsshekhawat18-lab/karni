"""Serializers of the impersonation API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from karni_impersonation.models import ImpersonationSession

__all__ = ["PersonSerializer", "SessionSerializer", "StartSerializer", "StopSerializer"]


class PersonSerializer(serializers.Serializer[Any]):
    id = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True, required=False)


class SessionSerializer(serializers.ModelSerializer[ImpersonationSession]):
    actor = PersonSerializer(read_only=True)
    target = PersonSerializer(read_only=True)
    active = serializers.BooleanField(source="is_active", read_only=True)

    class Meta:
        model = ImpersonationSession
        fields = [
            "id",
            "actor",
            "target",
            "reason",
            "started_at",
            "expires_at",
            "ended_at",
            "end_reason",
            "active",
            "batch_id",
            "created_at",
        ]
        read_only_fields = fields


class StartSerializer(serializers.Serializer[Any]):
    """``POST …/start/``: the user to act as (id or email) and the reason."""

    user = serializers.CharField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class StopSerializer(serializers.Serializer[Any]):
    """``POST …/stop/``: optionally the impersonation refresh token, to blacklist it."""

    refresh = serializers.CharField(required=False, allow_blank=True, default="")
