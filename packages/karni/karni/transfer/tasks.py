"""The Celery side of large imports: the same run, off the request."""

from __future__ import annotations

from typing import Any

from celery import shared_task

__all__ = ["run_import_stage"]


@shared_task(name="karni.transfer.tasks.run_import_stage")
def run_import_stage(job_id: str, user_id: str | None, stage: str) -> dict[str, Any]:
    """Preview or commit ``job_id`` as ``user_id`` (``services.run_stage``)."""
    from django.contrib.auth import get_user_model

    from karni.transfer.models import ImportJob
    from karni.transfer.services import job_state, run_stage

    job = ImportJob.objects.get(pk=job_id)
    user = get_user_model()._default_manager.filter(pk=user_id).first() if user_id else None
    return job_state(run_stage(job, stage, user))
