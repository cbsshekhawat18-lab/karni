"""Provider presets: one setting gives core's S3 backend its endpoint, region and addressing."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import pytest
from django.test import override_settings

from karni_storage import presets
from karni_storage.storage import protected_storage

S3 = {"KARNI_STORAGE": "s3"}


@pytest.mark.parametrize(
    ("provider", "extra", "endpoint", "region", "addressing", "method", "host"),
    [
        ("aws", {}, None, "eu-west-1", "virtual", "post", "karni-test-bucket.s3.eu-west-1"),
        (
            "r2",
            {"R2_ACCOUNT_ID": "acct123", "AWS_S3_REGION_NAME": ""},
            "https://acct123.r2.cloudflarestorage.com",
            "auto",
            "path",
            "put",
            "acct123.r2.cloudflarestorage.com",
        ),
        (
            "minio",
            {"AWS_S3_ENDPOINT_URL": "http://minio.internal:9000", "AWS_S3_REGION_NAME": ""},
            "http://minio.internal:9000",
            "us-east-1",
            "path",
            "post",
            "minio.internal:9000",
        ),
        (
            "spaces",
            {"AWS_S3_REGION_NAME": "nyc3"},
            "https://nyc3.digitaloceanspaces.com",
            "nyc3",
            "virtual",
            "put",
            "karni-test-bucket.nyc3.digitaloceanspaces.com",
        ),
        (
            "b2",
            {"AWS_S3_REGION_NAME": "us-west-004"},
            "https://s3.us-west-004.backblazeb2.com",
            "us-west-004",
            "virtual",
            "put",
            "karni-test-bucket.s3.us-west-004.backblazeb2.com",
        ),
        (
            "gcs-interop",
            {"AWS_S3_REGION_NAME": ""},
            "https://storage.googleapis.com",
            "auto",
            "path",
            "put",
            "storage.googleapis.com",
        ),
    ],
)
def test_each_preset_configures_cores_s3_backend(
    provider: str,
    extra: dict[str, str],
    endpoint: str | None,
    region: str,
    addressing: str,
    method: str,
    host: str,
) -> None:
    from karni.storage import S3Storage

    with override_settings(**S3, KARNI_STORAGE_PROVIDER=provider, **extra):
        options = presets.s3_options()
        assert options["endpoint_url"] == endpoint
        assert options["region_name"] == region
        assert options["addressing_style"] == addressing
        assert options["signature_version"] == "s3v4"
        assert options["bucket_name"] == "karni-test-bucket"
        assert options["location"] == "protected"
        assert options["custom_domain"] is None and options["querystring_auth"] is True
        assert presets.upload_method() == method
        assert presets.problems() == []
        storage = protected_storage()
        assert isinstance(storage, S3Storage)
        url = urlsplit(storage.url("manuals/guide.pdf"))
        assert url.netloc.startswith(host)
        if addressing == "path":
            assert url.path == "/karni-test-bucket/protected/manuals/guide.pdf"
        else:
            assert url.path == "/protected/manuals/guide.pdf"
        assert "X-Amz-Signature=" in url.query


def test_an_explicit_endpoint_and_addressing_style_win() -> None:
    with override_settings(
        **S3,
        KARNI_STORAGE_PROVIDER="r2",
        R2_ACCOUNT_ID="acct123",
        AWS_S3_ENDPOINT_URL="https://acct123.eu.r2.cloudflarestorage.com",
        AWS_S3_ADDRESSING_STYLE="virtual",
        KARNI_STORAGE_UPLOAD_METHOD="post",
    ):
        options = presets.s3_options()
        assert options["endpoint_url"] == "https://acct123.eu.r2.cloudflarestorage.com"
        assert options["addressing_style"] == "virtual"
        assert presets.upload_method() == "post"


def test_an_unknown_preset_fails_with_store001() -> None:
    from karni.exceptions import KarniLookupError

    with override_settings(KARNI_STORAGE_PROVIDER="azure"):
        with pytest.raises(KarniLookupError) as caught:
            presets.s3_options()
        assert caught.value.code == "STORE001"
        found = presets.problems()
        assert len(found) == 1 and found[0].startswith("STORE001")
        assert "aws, r2, minio, spaces, b2, gcs-interop" in found[0]


def test_missing_credentials_fail_with_store002() -> None:
    with override_settings(**S3, AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY=""):
        found = presets.problems()
    assert len(found) == 1 and found[0].startswith("STORE002")
    assert "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY" in found[0]
    assert "KARNI_STORAGE_CREDENTIALS=chain" in found[0]
    with override_settings(
        **S3, AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="", KARNI_STORAGE_CREDENTIALS="chain"
    ):
        assert presets.problems() == []


def test_a_role_in_the_environment_counts_as_credentials(monkeypatch: Any) -> None:
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/credentials/x")
    with override_settings(**S3, AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY=""):
        assert presets.problems() == []


@pytest.mark.parametrize(
    ("provider", "extra", "needs"),
    [
        ("aws", {"AWS_S3_REGION_NAME": ""}, "AWS_S3_REGION_NAME"),
        ("r2", {"R2_ACCOUNT_ID": ""}, "R2_ACCOUNT_ID"),
        ("minio", {"AWS_S3_ENDPOINT_URL": ""}, "AWS_S3_ENDPOINT_URL"),
        ("spaces", {"AWS_S3_REGION_NAME": ""}, "AWS_S3_REGION_NAME"),
        ("b2", {"AWS_S3_REGION_NAME": ""}, "AWS_S3_REGION_NAME"),
        ("gcs-interop", {"AWS_STORAGE_BUCKET_NAME": ""}, "AWS_STORAGE_BUCKET_NAME"),
    ],
)
def test_a_missing_value_fails_with_store003(
    provider: str, extra: dict[str, str], needs: str
) -> None:
    with override_settings(**S3, KARNI_STORAGE_PROVIDER=provider, **extra):
        found = presets.problems()
    assert len(found) == 1 and found[0].startswith("STORE003"), found
    assert needs in found[0]


def test_local_storage_needs_no_credentials() -> None:
    with override_settings(AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="", AWS_S3_REGION_NAME=""):
        assert presets.problems() == []


def test_values_a_setting_does_not_take_fail_with_store005() -> None:
    with override_settings(KARNI_STORAGE_UPLOAD_METHOD="multipart"):
        assert presets.problems()[0].startswith("STORE005")
    with override_settings(**S3, KARNI_STORAGE_CREDENTIALS="vault"):
        assert presets.problems()[0].startswith("STORE005")
