"""The protected fields: migrations, limits, the schema and the download path."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni_storage.fields import IMAGE_CONTENT_TYPES, ProtectedFileField, ProtectedImageField
from karni_storage.storage import PrivateFileSystemStorage, ProtectedStorage
from tests.testapp.models import Product


def test_migrations_never_record_a_backend() -> None:
    field = ProtectedFileField(upload_to="x/", max_size=10, content_types=["text/plain"])
    _name, path, _args, kwargs = field.deconstruct()
    assert path == "karni_storage.fields.ProtectedFileField"
    assert "storage" not in kwargs
    assert kwargs["max_size"] == 10 and kwargs["content_types"] == ["text/plain"]
    image = ProtectedImageField(upload_to="y/", thumbnails=False)
    assert image.deconstruct()[3]["thumbnails"] is False
    assert "thumbnails" not in ProtectedImageField(upload_to="y/").deconstruct()[3]


def test_a_field_with_its_own_storage_keeps_it() -> None:
    from django.core.files.storage import InMemoryStorage

    storage = InMemoryStorage()
    field = ProtectedFileField(upload_to="x/", storage=storage)
    assert field.deconstruct()[3]["storage"] is storage


def test_limits_and_defaults(settings: Any) -> None:
    manual = Product._meta.get_field("manual")
    photo = Product._meta.get_field("photo")
    assert manual.size_limit == 1024 * 1024
    assert manual.allowed_content_types == ("application/pdf", "text/plain")
    assert photo.allowed_content_types == IMAGE_CONTENT_TYPES
    assert "image/svg+xml" not in IMAGE_CONTENT_TYPES
    settings.KARNI_STORAGE_MAX_SIZE = 42
    assert photo.size_limit == 42
    assert isinstance(photo.storage, ProtectedStorage)


def test_local_files_have_no_public_url() -> None:
    from karni_storage.storage import protected_storage

    storage = protected_storage()
    assert isinstance(storage, PrivateFileSystemStorage)
    with pytest.raises(ValueError, match="no public URL"):
        storage.url("a.txt")


@pytest.mark.django_db
def test_the_download_path_needs_the_include(make_product: Any) -> None:
    from karni.exceptions import KarniImproperlyConfigured

    product = make_product(manual="m/a.txt")
    assert product.manual.url == f"/api/products/{product.pk}/files/manual/"
    with override_settings(ROOT_URLCONF="tests.urls_without_storage"):
        with pytest.raises(KarniImproperlyConfigured) as caught:
            _ = product.manual.url
    assert caught.value.code == "STORE020"


@pytest.mark.django_db
def test_a_model_no_viewset_serves_has_no_download_path(owner: Any) -> None:
    from karni.exceptions import KarniImproperlyConfigured

    from tests.testapp.models import Brochure

    brochure = Brochure.objects.create(title="Spring", scan="b/spring.pdf")
    with pytest.raises(KarniImproperlyConfigured, match="no viewset serves Brochure"):
        _ = brochure.scan.url


def test_the_schema_describes_protected_fields() -> None:
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    product = schema["components"]["schemas"]["TestappProduct"]["properties"]
    assert product["manual"]["format"] == "uri"
    assert product["manual"]["x-karni-storage"] == {
        "protected": True,
        "max_size": 1024 * 1024,
        "content_types": ["application/pdf", "text/plain"],
        "thumbnails": [],
    }
    assert product["photo"]["x-karni-storage"]["thumbnails"] == ["medium", "small"]
    request = schema["components"]["schemas"]["TestappProductRequest"]["properties"]
    assert request["photo"]["format"] == "binary"
    assert "StorageUploadRequest" in schema["components"]["schemas"]
    paths = schema["paths"]
    assert "/api/{resource}/files/{field}/upload/" in paths
    assert "/api/{resource}/{id}/files/{field}/" in paths
