"""The hourly sweep that expires or escalates overdue pending changes."""

from __future__ import annotations

from karni.schedule import every

every(hours=1, task="karni_approvals.tasks.sweep_pending", name="karni-approvals-sweep")
