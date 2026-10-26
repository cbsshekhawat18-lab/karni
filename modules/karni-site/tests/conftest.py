"""Shared set-up for the karni-site suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from karni.celery import create_celery_app
from pytest_django import Settings

# One Celery app for the suite, configured from tests.settings. It becomes the current app,
# so the queued listener's shared task honours CELERY_TASK_ALWAYS_EAGER.
celery_app = create_celery_app("karni-site-tests")


@pytest.fixture(autouse=True)
def _media(settings: Settings, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = str(tmp_path / "media")
