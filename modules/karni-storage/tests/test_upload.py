"""Direct uploads: POST .../upload/, the browser to the bucket, POST .../confirm/, the row."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from karni_storage.serializers import UPLOAD_REFERENCE_TYPE
from tests.testapp.models import Product

pytestmark = pytest.mark.django_db

UPLOAD = "/api/products/files/manual/upload/"
CONFIRM = "/api/products/files/manual/confirm/"
PDF = {"name": "guide.pdf", "content_type": "application/pdf", "size": 2048}


def _policy(fields: dict[str, str]) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(base64.b64decode(fields["policy"]))
    return decoded


def _head(stubber: Stubber, key: str, size: int, content_type: str) -> None:
    stubber.add_response(
        "head_object",
        {"ContentLength": size, "ContentType": content_type},
        {"Bucket": "karni-test-bucket", "Key": key},
    )


def _upload(client: APIClient, body: dict[str, Any] | None = None, path: str = UPLOAD) -> Any:
    return client.post(path, body or PDF, format="json")


def test_on_local_storage_the_file_goes_through_the_api(owner_api: APIClient) -> None:
    response = _upload(owner_api)
    assert response.status_code == 200
    assert response.json() == {
        "method": "api",
        "max_size": 1024 * 1024,
        "content_types": ["application/pdf", "text/plain"],
    }


def test_the_presigned_post_carries_the_fields_limits(owner_api: APIClient, bucket: Any) -> None:
    data = _upload(owner_api).json()
    assert data["method"] == "post"
    assert data["url"] == "https://karni-test-bucket.s3.eu-west-1.amazonaws.com/"
    assert data["max_size"] == 1024 * 1024 and data["expires_in"] == 900
    key = data["fields"]["key"]
    assert key.startswith("protected/products/manuals/") and key.endswith("/guide.pdf")
    assert data["fields"]["Content-Type"] == "application/pdf"
    assert data["fields"]["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    conditions = _policy(data["fields"])["conditions"]
    assert ["content-length-range", 1, 1024 * 1024] in conditions
    assert {"Content-Type": "application/pdf"} in conditions
    assert {"key": key} in conditions and {"bucket": "karni-test-bucket"} in conditions
    assert data["name"] == "guide.pdf" and data["token"]


def test_two_uploads_of_one_name_get_two_keys(owner_api: APIClient, bucket: Any) -> None:
    first = _upload(owner_api).json()["fields"]["key"]
    assert first != _upload(owner_api).json()["fields"]["key"]


def test_a_preset_without_post_policies_gets_a_presigned_put(
    owner_api: APIClient, bucket: Any, settings: Any
) -> None:
    settings.KARNI_STORAGE_PROVIDER = "r2"
    settings.R2_ACCOUNT_ID = "acct123"
    data = _upload(owner_api).json()
    assert data["method"] == "put"
    assert data["headers"] == {"Content-Type": "application/pdf"}
    url = urlsplit(data["url"])
    assert url.netloc == "acct123.r2.cloudflarestorage.com"
    assert url.path.startswith("/karni-test-bucket/protected/products/manuals/")
    query = parse_qs(url.query)
    assert query["X-Amz-Expires"] == ["900"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]


def test_the_upload_step_refuses_what_the_field_does_not_take(
    owner_api: APIClient, bucket: Any
) -> None:
    big = _upload(owner_api, {**PDF, "size": 5 * 1024 * 1024})
    assert big.status_code == 400 and "STORE011" in str(big.json())
    wrong = _upload(owner_api, {"name": "song.mp3", "content_type": "audio/mpeg", "size": 10})
    assert wrong.status_code == 400 and "STORE012" in str(wrong.json())
    svg = _upload(
        owner_api,
        {"name": "x.svg", "content_type": "image/svg+xml", "size": 10},
        "/api/products/files/photo/upload/",
    )
    assert svg.status_code == 400 and "STORE012" in str(svg.json())


def test_only_callers_who_may_create_or_change_may_upload(
    api: APIClient, owner_api: APIClient
) -> None:
    assert _upload(api).status_code in (401, 403)
    hidden = _upload(owner_api, path="/api/products/files/invoice/upload/")
    assert hidden.status_code == 403  # field_roles: the owner may not write it


def test_confirm_checks_the_object_then_gives_a_token(
    owner_api: APIClient, bucket: Stubber, owner: Any
) -> None:
    upload = _upload(owner_api).json()
    _head(bucket, upload["fields"]["key"], 2048, "application/pdf")
    confirmed = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json")
    assert confirmed.status_code == 200, confirmed.json()
    data = confirmed.json()
    assert data["size"] == 2048 and data["content_type"] == "application/pdf"
    created = owner_api.post(
        "/api/products/", {"name": "Lamp", "manual": data["token"]}, format="json"
    )
    assert created.status_code == 201, created.json()
    product = Product.objects.get(pk=created.json()["id"])
    assert product.manual.name == upload["fields"]["key"].removeprefix("protected/")
    assert product.owner == owner


def test_a_multipart_form_sends_the_token_as_a_reference_part(
    owner_api: APIClient, bucket: Stubber, make_product: Any
) -> None:
    product = make_product()
    upload = _upload(owner_api).json()
    _head(bucket, upload["fields"]["key"], 2048, "application/pdf")
    token = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json").json()["token"]
    reference = SimpleUploadedFile("guide.pdf", token.encode(), content_type=UPLOAD_REFERENCE_TYPE)
    response = owner_api.patch(
        f"/api/products/{product.pk}/", {"manual": reference}, format="multipart"
    )
    assert response.status_code == 200, response.json()
    product.refresh_from_db()
    assert product.manual.name.endswith("/guide.pdf")


@pytest.mark.parametrize(
    ("size", "content_type", "code"),
    [(5 * 1024 * 1024, "application/pdf", "STORE011"), (2048, "text/html", "STORE012")],
)
def test_confirm_deletes_a_wrong_object(
    owner_api: APIClient, bucket: Stubber, size: int, content_type: str, code: str
) -> None:
    upload = _upload(owner_api).json()
    key = upload["fields"]["key"]
    _head(bucket, key, size, content_type)
    bucket.add_response("delete_object", {}, {"Bucket": "karni-test-bucket", "Key": key})
    response = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json")
    assert response.status_code == 400 and code in str(response.json())


def test_confirm_refuses_a_type_other_than_the_one_declared(
    owner_api: APIClient, bucket: Stubber
) -> None:
    upload = _upload(owner_api).json()
    key = upload["fields"]["key"]
    _head(bucket, key, 20, "text/plain")
    bucket.add_response("delete_object", {}, {"Bucket": "karni-test-bucket", "Key": key})
    response = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json")
    assert response.status_code == 400 and "STORE012" in str(response.json())


def test_confirm_refuses_a_missing_object(owner_api: APIClient, bucket: Stubber) -> None:
    upload = _upload(owner_api).json()
    bucket.add_client_error(
        "head_object", service_error_code="404", http_status_code=404, service_message="Not Found"
    )
    response = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json")
    assert response.status_code == 400 and "STORE014" in str(response.json())


def test_confirm_refuses_someone_elses_or_another_fields_token(
    owner_api: APIClient, other_api: APIClient, bucket: Stubber
) -> None:
    token = _upload(owner_api).json()["token"]
    theirs = other_api.post(CONFIRM, {"token": token}, format="json")
    assert theirs.status_code == 400 and "STORE013" in str(theirs.json())
    field = owner_api.post("/api/products/files/photo/confirm/", {"token": token}, format="json")
    assert field.status_code == 400 and "STORE013" in str(field.json())
    junk = owner_api.post(CONFIRM, {"token": "not-a-token"}, format="json")
    assert junk.status_code == 400 and "STORE013" in str(junk.json())


def test_an_expired_upload_token_is_refused(
    owner_api: APIClient, bucket: Stubber, settings: Any
) -> None:
    token = _upload(owner_api).json()["token"]
    settings.KARNI_STORAGE_UPLOAD_EXPIRY = -120
    response = owner_api.post(CONFIRM, {"token": token}, format="json")
    assert response.status_code == 400 and "expired" in str(response.json())


def test_a_row_takes_only_a_confirmed_token_of_its_own_user(
    owner_api: APIClient, other_api: APIClient, bucket: Stubber
) -> None:
    upload = _upload(owner_api).json()
    # The upload token itself is not a confirmed one.
    unconfirmed = owner_api.post(
        "/api/products/", {"name": "Lamp", "manual": upload["token"]}, format="json"
    )
    assert unconfirmed.status_code == 400 and "STORE013" in str(unconfirmed.json())
    _head(bucket, upload["fields"]["key"], 2048, "application/pdf")
    token = owner_api.post(CONFIRM, {"token": upload["token"]}, format="json").json()["token"]
    stolen = other_api.post("/api/products/", {"name": "Lamp", "manual": token}, format="json")
    assert stolen.status_code == 400 and "STORE013" in str(stolen.json())
    other_field = owner_api.post("/api/products/", {"name": "Lamp", "photo": token}, format="json")
    assert other_field.status_code == 400 and "STORE013" in str(other_field.json())


def test_confirm_on_local_storage_says_to_send_the_file_with_the_row(
    owner_api: APIClient,
) -> None:
    response = owner_api.post(CONFIRM, {"token": "x"}, format="json")
    assert response.status_code == 400 and "STORE015" in str(response.json())


def test_files_sent_through_the_api_keep_the_fields_limits(owner_api: APIClient) -> None:
    big = SimpleUploadedFile("big.pdf", b"x" * (1024 * 1024 + 1), content_type="application/pdf")
    response = owner_api.post("/api/products/", {"name": "Lamp", "manual": big})
    assert response.status_code == 400 and "STORE011" in str(response.json())
    html = SimpleUploadedFile("page.html", b"<script>", content_type="text/html")
    response = owner_api.post("/api/products/", {"name": "Lamp", "manual": html})
    assert response.status_code == 400 and "STORE012" in str(response.json())
    text = SimpleUploadedFile("notes.txt", b"fine", content_type="text/plain")
    response = owner_api.post("/api/products/", {"name": "Lamp", "manual": text})
    assert response.status_code == 201, response.json()


def test_a_custom_storage_alias_replaces_the_modules_storage(tmp_path: Any) -> None:
    from karni_storage.storage import protected_storage

    storages = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        "protected": {
            "BACKEND": "django.core.files.storage.InMemoryStorage",
        },
    }
    with override_settings(STORAGES=storages):
        assert type(protected_storage()).__name__ == "InMemoryStorage"
