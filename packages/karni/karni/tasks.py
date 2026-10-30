"""Celery tasks of the ``karni`` app itself."""

from __future__ import annotations

from celery import shared_task

__all__ = ["flush_api_cache"]


@shared_task(name="karni.tasks.flush_api_cache")
def flush_api_cache() -> str:
    """Drop every cached API response (``KARNI_API_CACHE_FLUSH`` schedules it daily).

    Returns how it cleared: ``"delete_pattern"`` or ``"versions"``
    (:func:`karni.api.caching.clear`).
    """
    from karni.api.caching import clear

    return clear()
