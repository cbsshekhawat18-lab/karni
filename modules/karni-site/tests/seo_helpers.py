"""Shared set-up for the SEO tests: the small site of tests/seo_urls.py and images to upload."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from karni.celery import create_celery_app
from pytest_django import Settings

# The current Celery app, configured from tests.settings, so the renditions task runs eagerly.
celery_app = create_celery_app("karni-site-seo-tests")


def jpeg(width: int, height: int, colour: tuple[int, int, int] = (180, 120, 60)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def upload(name: str, width: int, height: int) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, jpeg(width, height), content_type="image/jpeg")


@pytest.fixture
def seo_site(settings: Settings, tmp_path: Path) -> Settings:
    """The SEO test site at "/", its media in a fresh folder, the website pages left alone."""
    settings.ROOT_URLCONF = "tests.seo_urls"
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.KARNI_SITE_SEO_IGNORE = [r"^/web/"]
    settings.KARNI_SITE_SITEMAP_EXCLUDE = ["website:*", "seo:bare"]
    return settings
