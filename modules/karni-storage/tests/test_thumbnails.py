"""Thumbnails of protected images: core's thumbnailer, a Celery task, the protected path."""

from __future__ import annotations

from io import BytesIO
from typing import Any
from unittest import mock

import pytest
from botocore.stub import Stubber
from django.core.management import call_command
from rest_framework.test import APIClient

from karni_storage import thumbnails
from karni_storage.models import Thumbnail
from tests.conftest import png
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db


def _post_photo(client: APIClient, capture: Any) -> Product:
    with capture(execute=True):
        response = client.post("/api/products/", {"name": "Lamp", "photo": png(400, 300)})
    assert response.status_code == 201, response.json()
    return Product.objects.get(pk=response.json()["id"])


def test_saving_an_image_makes_its_thumbnails(
    owner_api: APIClient, django_capture_on_commit_callbacks: Any
) -> None:
    from PIL import Image

    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    made = dict(Thumbnail.objects.filter(source=product.photo.name).values_list("size", "name"))
    assert set(made) == {"small", "medium"}
    response = owner_api.get(f"/api/products/{product.pk}/files/photo/", {"size": "small"})
    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    image = Image.open(BytesIO(b"".join(response.streaming_content)))
    assert image.size == (160, 120)  # inside 160x160, never upscaled, aspect kept


def test_the_thumbnail_follows_the_rows_access(
    owner_api: APIClient, other_api: APIClient, django_capture_on_commit_callbacks: Any
) -> None:
    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    path = f"/api/products/{product.pk}/files/photo/"
    assert other_api.get(path, {"size": "small"}).status_code == 404


def test_an_unknown_size_and_a_thumbnail_not_ready(owner_api: APIClient, make_product: Any) -> None:
    product = make_product(photo="products/photos/abc/photo.png")
    path = f"/api/products/{product.pk}/files/photo/"
    unknown = owner_api.get(path, {"size": "huge"})
    assert unknown.status_code == 400 and "STORE016" in str(unknown.json())
    assert "small, medium" in str(unknown.json())
    waiting = owner_api.get(path, {"size": "small"})
    assert waiting.status_code == 404 and "STORE017" in str(waiting.json())
    plain = owner_api.get(
        f"/api/products/{make_product(manual='m/a.txt').pk}/files/manual/", {"size": "small"}
    )
    assert plain.status_code == 404 and "STORE017" in str(plain.json())


def test_make_is_idempotent_and_follows_the_setting(
    owner_api: APIClient, django_capture_on_commit_callbacks: Any, settings: Any
) -> None:
    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    assert thumbnails.make(product.photo.name) == {}
    settings.KARNI_STORAGE_THUMBNAIL_SIZES = {"small": [160, 160], "tiny": [32, 32]}
    assert set(thumbnails.make(product.photo.name)) == {"tiny"}


def test_a_projects_own_thumbnailer_is_used(
    owner_api: APIClient, django_capture_on_commit_callbacks: Any, settings: Any
) -> None:
    calls: list[tuple[str, tuple[int, int]]] = []

    def thumbnailer(source: str, *, size: tuple[int, int], fmt: str, storage: Any) -> str:
        calls.append((source, size))
        return f"custom/{size[0]}.webp"

    settings.KARNI_THUMBNAILER = f"{__name__}.CUSTOM"
    globals()["CUSTOM"] = thumbnailer
    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    assert sorted(calls) == [(product.photo.name, (160, 160)), (product.photo.name, (640, 640))]
    assert thumbnails.find(product.photo.name, "medium") == "custom/640.webp"


def test_an_unchanged_image_queues_nothing(
    owner_api: APIClient, django_capture_on_commit_callbacks: Any
) -> None:
    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    with mock.patch("karni_storage.tasks.make_thumbnails.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            product.name = "Desk lamp"
            product.save()
    delay.assert_not_called()


def test_confirm_queues_the_thumbnails_of_an_image(
    owner_api: APIClient, bucket: Stubber, django_capture_on_commit_callbacks: Any
) -> None:
    upload = owner_api.post(
        "/api/products/files/photo/upload/",
        {"name": "shot.png", "content_type": "image/png", "size": 900},
        format="json",
    ).json()
    key = upload["fields"]["key"]
    bucket.add_response(
        "head_object",
        {"ContentLength": 900, "ContentType": "image/png"},
        {"Bucket": "karni-test-bucket", "Key": key},
    )
    with mock.patch("karni_storage.tasks.make_thumbnails.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = owner_api.post(
                "/api/products/files/photo/confirm/", {"token": upload["token"]}, format="json"
            )
    assert response.status_code == 200, response.json()
    delay.assert_called_once_with(key.removeprefix("protected/"))


def test_thumbnails_on_a_bucket_redirect_to_their_signed_url(
    owner_api: APIClient, make_product: Any, bucket: Stubber
) -> None:
    product = make_product(photo="products/photos/abc/shot.png")
    Thumbnail.objects.create(
        source="products/photos/abc/shot.png", size="small", name="thumbs/shot_160x160.webp"
    )
    response = owner_api.get(f"/api/products/{product.pk}/files/photo/", {"size": "small"})
    assert response.status_code == 302
    assert "/protected/thumbs/shot_160x160.webp?" in response["Location"]


def test_the_command_makes_what_is_missing(
    owner_api: APIClient, django_capture_on_commit_callbacks: Any, capsys: Any
) -> None:
    product = _post_photo(owner_api, django_capture_on_commit_callbacks)
    Thumbnail.objects.filter(source=product.photo.name, size="medium").delete()
    call_command("karni_thumbnails")
    assert "karni_thumbnails: 1 made." in capsys.readouterr().out
