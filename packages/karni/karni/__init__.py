"""Karni — batteries-included Django framework glue.

Karni packages the settings, Celery, storage and health-check boilerplate that
every Django + DRF + Celery project repeats, behind a handful of small,
overridable entry points:

* :func:`karni.conf.karni_settings` — assemble a full Django settings module.
* :func:`karni.celery.create_celery_app` — a configured Celery application.
* :mod:`karni.storage` — S3-compatible or local file storage plus thumbnails.
* :mod:`karni.health` — liveness and readiness endpoints.
* :mod:`karni.events` — ``<app>/listeners.py`` model lifecycle listeners
  (``on_created`` / ``on_updated`` / ``on_deleted``, ``queued``).
* :mod:`karni.schedule` — ``<app>/schedules.py`` beat schedules
  (``every`` / ``cron``).

Every default Karni applies can be overridden from the project's own
``settings.py``: values defined before ``karni_settings(globals())`` are never
overwritten, and values assigned after the call always win.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
