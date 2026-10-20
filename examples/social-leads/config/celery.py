"""Celery entry point for Social Leads.

Used by ``celery -A config worker`` and ``celery -A config beat``. The app
is configured from Django settings (every ``CELERY_*`` name), so override
Celery behaviour in config/settings.py, or pass keyword overrides to
``create_celery_app()`` here.
"""

import os

from karni.celery import create_celery_app

# create_celery_app() requires DJANGO_SETTINGS_MODULE to be set already;
# setdefault here covers the `celery -A config ...` entry points.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = create_celery_app()
