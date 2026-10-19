"""Hourly: end sessions past their limit that no request ended."""

from __future__ import annotations

from karni.schedule import every

every(hours=1, task="karni_impersonation.tasks.sweep_sessions", name="karni-impersonation-sweep")
