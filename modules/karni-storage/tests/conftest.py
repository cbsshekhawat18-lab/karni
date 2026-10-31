"""Shared fixtures for the karni-storage test suite.

``bucket`` switches protected files to a bucket (``KARNI_STORAGE = "s3"``,
the aws preset, a fake account) and gives a botocore ``Stubber`` on the
storage's client, so the bucket's answers (``head_object``,
``delete_object``) are scripted and no request leaves the process. Signing a
URL or a POST policy is local and needs no stub.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from io import BytesIO
from typing import Any

import pytest
from botocore.stub import Stubber
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from karni.celery import create_celery_app
from rest_framework.test import APIClient

from karni_storage.storage import protected_storage, s3_client
from tests.testapp.models import Product

celery_app = create_celery_app("karni-storage-tests")

ProductFactory = Callable[..., Product]


@pytest.fixture
def owner(db: None) -> Any:
    return get_user_model().objects.create_user(email="owner@example.com", password="pw")


@pytest.fixture
def other(db: None) -> Any:
    return get_user_model().objects.create_user(email="other@example.com", password="pw")


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def owner_api(owner: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(owner)
    return client


@pytest.fixture
def other_api(other: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(other)
    return client


@pytest.fixture
def make_product(owner: Any) -> ProductFactory:
    def make(**fields: Any) -> Product:
        values: dict[str, Any] = {"name": "Desk lamp", "owner": owner}
        values.update(fields)
        return Product.objects.create(**values)

    return make


def png(width: int = 40, height: int = 30, name: str = "photo.png") -> SimpleUploadedFile:
    """A real PNG upload, made with Pillow."""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def bucket() -> Iterator[Stubber]:
    with override_settings(KARNI_STORAGE="s3", KARNI_STORAGE_PROVIDER="aws"):
        stubber = Stubber(s3_client(protected_storage()))
        with stubber:
            yield stubber
        stubber.assert_no_pending_responses()
