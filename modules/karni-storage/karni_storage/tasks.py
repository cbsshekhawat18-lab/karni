"""The Celery task that makes the thumbnails of a protected image.

Queued after a direct upload is confirmed and after a row is saved with a new
image (on commit), so a request never waits for Pillow. It is idempotent:
each size is made once (:func:`karni_storage.thumbnails.make`).

Override / escape hatch: ``thumbnails=False`` on a field stops the queueing,
and ``KARNI_THUMBNAILER`` replaces the rendering.
"""

from __future__ import annotations

from celery import shared_task

__all__ = ["make_thumbnails"]


@shared_task(name="karni_storage.make_thumbnails", ignore_result=True)
def make_thumbnails(source: str) -> dict[str, str]:
    """Experimental. Make the missing thumbnails of the protected image ``source``."""
    from karni_storage.thumbnails import make

    return make(source)
