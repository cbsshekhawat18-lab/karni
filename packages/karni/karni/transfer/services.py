"""Import jobs: upload → map → preview → commit, inline or in Celery.

The functions here are what the API actions, the admin page and the Celery
task call; each takes the user (or request) explicitly. ``start_stage``
decides inline versus Celery from ``KARNI_IMPORT_INLINE_ROWS``; progress of
an asynchronous run goes to the cache (the run itself is one transaction,
so a row count written inside it would not be visible until the end).
"""

from __future__ import annotations

from typing import Any, Final

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db.models import Model
from django.test import RequestFactory

from karni.exceptions import KarniValueError
from karni.middleware import current_user
from karni.transfer.formats import detect_format, read_table
from karni.transfer.imports import Importer
from karni.transfer.models import ColumnMapping, ImportJob

__all__ = [
    "PREVIEW",
    "COMMIT",
    "create_job",
    "inline_rows",
    "job_state",
    "max_import_rows",
    "request_for",
    "run_stage",
    "set_mapping",
    "start_stage",
]

PREVIEW: Final = "preview"
COMMIT: Final = "commit"
_PROGRESS_TTL: Final = 3600


def inline_rows() -> int:
    """Files with at most this many rows run inside the request; larger ones in Celery."""
    return int(getattr(settings, "KARNI_IMPORT_INLINE_ROWS", 500))


def max_import_rows() -> int:
    return int(getattr(settings, "KARNI_IMPORT_MAX_ROWS", 100_000))


def _progress_key(job: ImportJob) -> str:
    return f"karni:import:{job.pk}:rows_done"


def request_for(user: Any) -> Any:
    """A request-shaped object carrying ``user`` (the Celery worker has no request)."""
    request = RequestFactory().post("/")
    request.user = user
    return request


def create_job(
    model: type[Model], request: Any, upload: Any, *, mapping: dict[str, Any] | None = None
) -> ImportJob:
    """Store the upload and read its shape; the mapping is suggested, remembered or given."""
    user = getattr(request, "user", None)
    fmt = detect_format(getattr(upload, "name", None), getattr(upload, "content_type", None))
    content = upload.read()
    if isinstance(content, str):
        content = content.encode("utf-8")
    import io

    headers, rows = read_table(io.BytesIO(content), fmt)
    if not headers:
        raise KarniValueError("The file has no header row.", code="E801")
    if len(rows) > max_import_rows():
        raise KarniValueError(
            f"The file has {len(rows)} rows; the limit is {max_import_rows()} "
            "(KARNI_IMPORT_MAX_ROWS). Split it.",
            code="E803",
        )
    importer = Importer(model, request)
    remembered = {
        header: field
        for header, field in ColumnMapping.remembered(user, model).items()
        if header in headers and field
    }
    suggested = importer.suggest_mapping(headers)
    chosen = dict(mapping) if mapping else (remembered or suggested)
    job = ImportJob(
        content_type=ContentType.objects.get_for_model(model),
        original_name=str(getattr(upload, "name", "") or "upload")[:255],
        format=fmt,
        columns=list(headers),
        mapping={header: str(chosen.get(header, "") or "") for header in headers},
        rows_total=len(rows),
    )
    with current_user(user):
        job.file.save(f"{job.pk}.{fmt}", ContentFile(content), save=False)
        job.save()
    return job


def set_mapping(job: ImportJob, request: Any, mapping: dict[str, Any]) -> ImportJob:
    """Validate and store the mapping; a change after a preview needs a new preview."""
    importer = Importer(job.model_class, request)
    importer.validate_mapping(list(job.columns), mapping)
    normalised = {header: str(mapping.get(header, "") or "") for header in job.columns}
    changed = normalised != job.mapping
    job.mapping = normalised
    if changed and job.status in (ImportJob.Status.PREVIEWED, ImportJob.Status.FAILED):
        job.status = ImportJob.Status.UPLOADED
        job.result = None
        job.problems = []
        job.error = ""
    job.save(update_fields=["mapping", "status", "result", "problems", "error", "updated_at"])
    ColumnMapping.remember(getattr(request, "user", None), job.model_class, normalised)
    return job


def start_stage(job: ImportJob, request: Any, stage: str) -> ImportJob:
    """Run the preview or the commit — now, or in Celery when the file is large."""
    if stage == COMMIT and job.status != ImportJob.Status.PREVIEWED:
        raise KarniValueError(
            "Preview first: an import is committed only after its dry run "
            f"(this job is {job.status}).",
            code="E801",
        )
    if stage == PREVIEW and job.status in (
        ImportJob.Status.PREVIEWING,
        ImportJob.Status.COMMITTING,
        ImportJob.Status.DONE,
    ):
        raise KarniValueError(f"This job is {job.status}; it cannot be previewed now.", code="E801")
    user = getattr(request, "user", None)
    if job.rows_total <= inline_rows():
        return run_stage(job, stage, user)
    job.status = ImportJob.Status.PREVIEWING if stage == PREVIEW else ImportJob.Status.COMMITTING
    job.rows_done = 0
    job.save(update_fields=["status", "rows_done", "updated_at"])
    cache.set(_progress_key(job), 0, _PROGRESS_TTL)
    from karni.transfer.tasks import run_import_stage

    run_import_stage.delay(str(job.pk), str(getattr(user, "pk", "")) or None, stage)
    return job


def run_stage(job: ImportJob, stage: str, user: Any) -> ImportJob:
    """The preview or the commit, synchronously, as ``user``."""
    request = request_for(user)
    dry_run = stage == PREVIEW
    job.status = ImportJob.Status.PREVIEWING if dry_run else ImportJob.Status.COMMITTING
    job.save(update_fields=["status", "updated_at"])

    def progress(done: int, _total: int) -> None:
        cache.set(_progress_key(job), done, _PROGRESS_TTL)

    try:
        with current_user(user), job.file.open("rb") as handle:
            headers, rows = read_table(handle, job.format)
            importer = Importer(job.model_class, request)
            result = importer.run(
                headers,
                rows,
                job.mapping,
                dry_run=dry_run,
                progress=progress,
                label=job.original_name,
                meta={"job": str(job.pk)},
            )
    except KarniValueError as exc:
        job.status = ImportJob.Status.FAILED
        job.error = str(exc)
        job.save(update_fields=["status", "error", "updated_at"])
        cache.delete(_progress_key(job))
        return job
    job.result = result.to_dict()
    job.problems = [problem.to_dict() for problem in result.problems]
    job.rows_done = result.rows_total
    job.error = ""
    job.status = ImportJob.Status.PREVIEWED if dry_run else ImportJob.Status.DONE
    if not dry_run:
        job.batch_id = getattr(result, "batch_id", None)
    job.save(
        update_fields=[
            "result",
            "problems",
            "rows_done",
            "error",
            "status",
            "batch_id",
            "updated_at",
        ]
    )
    cache.delete(_progress_key(job))
    return job


def job_state(job: ImportJob, request: Any | None = None) -> dict[str, Any]:
    """The job as the API and the admin page show it."""
    in_flight = job.status in (ImportJob.Status.PREVIEWING, ImportJob.Status.COMMITTING)
    rows_done = job.rows_done
    if in_flight:
        cached = cache.get(_progress_key(job))
        if cached is not None:
            rows_done = int(cached)
    state: dict[str, Any] = {
        "id": str(job.pk),
        "model": job.content_type.model_class()._meta.label_lower
        if job.content_type.model_class()
        else None,
        "status": job.status,
        "file_name": job.original_name,
        "format": job.format,
        "columns": list(job.columns),
        "mapping": dict(job.mapping),
        "rows_total": job.rows_total,
        "rows_done": rows_done,
        "async": job.rows_total > inline_rows(),
        "result": job.result,
        "problems": list(job.problems),
        "error": job.error or None,
        "batch": job.batch_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
    if request is not None:
        importer = Importer(job.model_class, request)
        state["fields"] = [spec.to_dict() for spec in importer.importable()]
    return state
