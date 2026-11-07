"""Celery tasks of karni-site: the smaller copies of an uploaded image.

:func:`make_renditions` is queued by an upload and by the first page that
shows an image without copies (:mod:`karni_site.renditions`). It is
idempotent: copies that match the stored file are kept, so a task queued
twice does the work once.

Override / escape hatch: ``KARNI_SITE_RENDITIONER`` replaces what the task
calls. ``KARNI_SITE_QUEUE_RENDITIONS = False`` queues nothing, and
:func:`karni_site.renditions.make` makes the copies where you choose.
"""

from __future__ import annotations

from celery import shared_task

from karni_site import renditions

__all__ = ["make_renditions"]


@shared_task(name="karni_site.tasks.make_renditions", ignore_result=True)
def make_renditions(name: str, ref: str = "", force: bool = False) -> None:
    """Make the WebP copies and the manifest of the stored image ``name``.

    ``ref`` names the file field whose storage holds it
    (``"app_label.Model.field"``), ``""`` the default storage. ``force``
    makes them again even when a manifest exists.
    """
    renditions.make(name, ref, force=force)
