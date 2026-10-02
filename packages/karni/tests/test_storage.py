"""Tests for karni.storage: backends, thumbnailing and lazy imports."""

from __future__ import annotations

import sys
from io import BytesIO
from typing import Any

import pytest
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage, Storage
from django.test import override_settings

import karni.storage
from karni.storage import get_storage
from karni.storage.thumbnails import (
    DEFAULT_THUMBNAILER,
    get_thumbnailer,
    make_thumbnail,
)


def _png_bytes(width: int, height: int, mode: str = "RGB") -> bytes:
    """Render a solid-colour PNG of the given dimensions (requires Pillow)."""
    from PIL import Image

    color = (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0)
    buffer = BytesIO()
    Image.new(mode, (width, height), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _block_modules(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make ``import <name>`` raise ImportError for each given module."""
    for name in names:
        monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture()
def storage(tmp_path: Any) -> FileSystemStorage:
    """A tmp_path-backed FileSystemStorage isolated per test."""
    return FileSystemStorage(location=str(tmp_path), base_url="/media/")


class TestMakeThumbnail:
    """Thumbnail roundtrips against a local FileSystemStorage."""

    @pytest.fixture(autouse=True)
    def _require_pillow(self) -> None:
        pytest.importorskip("PIL")

    def test_roundtrip_preserves_aspect_ratio(self, storage: FileSystemStorage) -> None:
        from PIL import Image

        storage.save("photos/source.png", ContentFile(_png_bytes(640, 480)))

        name = make_thumbnail("photos/source.png", size=(64, 64), storage=storage)

        assert name == "thumbs/source_64x64.webp"
        assert storage.exists(name)
        with storage.open(name, "rb") as handle, Image.open(handle) as thumb:
            assert thumb.format == "WEBP"
            assert thumb.size == (64, 48)  # 4:3 aspect preserved within 64x64

    def test_default_size_and_format(self, storage: FileSystemStorage) -> None:
        storage.save("a.png", ContentFile(_png_bytes(640, 480)))

        name = make_thumbnail("a.png", storage=storage)

        assert name == "thumbs/a_256x256.webp"
        assert storage.exists(name)

    def test_never_upscales(self, storage: FileSystemStorage) -> None:
        from PIL import Image

        storage.save("tiny.png", ContentFile(_png_bytes(10, 10)))

        name = make_thumbnail("tiny.png", size=(64, 64), storage=storage)

        assert name == "thumbs/tiny_64x64.webp"  # requested size in the name
        with storage.open(name, "rb") as handle, Image.open(handle) as thumb:
            assert thumb.size == (10, 10)  # image itself is not upscaled

    def test_accepts_file_object(self, storage: FileSystemStorage) -> None:
        source = File(BytesIO(_png_bytes(100, 100)), name="uploads/avatar.png")

        name = make_thumbnail(source, size=(32, 32), storage=storage)

        assert name == "thumbs/avatar_32x32.webp"
        assert storage.exists(name)
        # The caller's file object is rewound, not closed.
        assert not source.closed

    def test_jpeg_output_converts_alpha(self, storage: FileSystemStorage) -> None:
        from PIL import Image

        storage.save("rgba.png", ContentFile(_png_bytes(80, 40, mode="RGBA")))

        name = make_thumbnail("rgba.png", size=(40, 40), fmt="JPEG", storage=storage)

        assert name == "thumbs/rgba_40x40.jpg"
        with storage.open(name, "rb") as handle, Image.open(handle) as thumb:
            assert thumb.format == "JPEG"
            assert thumb.mode == "RGB"
            assert thumb.size == (40, 20)

    def test_jpg_alias_maps_to_jpeg(self, storage: FileSystemStorage) -> None:
        storage.save("b.png", ContentFile(_png_bytes(50, 50)))

        name = make_thumbnail("b.png", size=(16, 16), fmt="jpg", storage=storage)

        assert name == "thumbs/b_16x16.jpg"
        assert storage.exists(name)

    def test_returns_actual_saved_name_on_collision(self, storage: FileSystemStorage) -> None:
        storage.save("c.png", ContentFile(_png_bytes(50, 50)))

        first = make_thumbnail("c.png", size=(16, 16), storage=storage)
        second = make_thumbnail("c.png", size=(16, 16), storage=storage)

        assert first == "thumbs/c_16x16.webp"
        assert second != first  # FileSystemStorage suffixed the name
        assert second.startswith("thumbs/c_16x16")
        assert storage.exists(first)
        assert storage.exists(second)


class TestGetThumbnailer:
    """KARNI_THUMBNAILER resolution via get_thumbnailer()."""

    def test_default_resolves_to_make_thumbnail(self) -> None:
        assert get_thumbnailer() is make_thumbnail

    def test_absent_setting_falls_back_to_default(self) -> None:
        from django.conf import settings

        assert getattr(settings, "KARNI_THUMBNAILER", DEFAULT_THUMBNAILER) == (DEFAULT_THUMBNAILER)
        assert get_thumbnailer() is make_thumbnail

    def test_override_setting_swaps_implementation(self) -> None:
        with override_settings(KARNI_THUMBNAILER=f"{__name__}.fake_thumbnailer"):
            assert get_thumbnailer() is fake_thumbnailer


def fake_thumbnailer(source: Any, **kwargs: Any) -> str:
    """Stand-in thumbnailer used by the KARNI_THUMBNAILER override test."""
    return "thumbs/fake.webp"


class TestGetStorage:
    """get_storage() reflects Django's live STORAGES configuration."""

    def test_returns_default_alias(self) -> None:
        from django.core.files.storage import storages

        instance = get_storage()
        assert instance is storages["default"]
        assert isinstance(instance, Storage)

    def test_returns_named_alias(self) -> None:
        from django.core.files.storage import storages

        assert get_storage("staticfiles") is storages["staticfiles"]


class TestStorageSelection:
    """KARNI_STORAGE drives the STORAGES dict built by karni.conf.base."""

    def test_s3_selects_karni_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from karni.conf import base

        monkeypatch.setenv("KARNI_STORAGE", "s3")
        config = base._storages(base.env)

        assert config["default"]["BACKEND"] == "karni.storage.S3Storage"
        assert (
            config["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )

    def test_local_is_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from karni.conf import base

        monkeypatch.delenv("KARNI_STORAGE", raising=False)
        config = base._storages(base.env)

        assert config["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
        assert (
            config["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )


class TestLazyImports:
    """Optional-dependency access fails with actionable install hints."""

    def test_s3storage_error_mentions_s3_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from karni.storage import s3 as s3_module

        monkeypatch.setattr(s3_module, "_S3StorageClass", None)
        _block_modules(
            monkeypatch,
            "storages",
            "storages.backends",
            "storages.backends.s3",
            "storages.backends.s3boto3",
            "storages.utils",
            "boto3",
        )

        with pytest.raises(ImportError, match=r"karni\[s3\]"):
            _ = s3_module.S3Storage

    def test_package_access_raises_same_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from karni.storage import s3 as s3_module

        monkeypatch.setattr(s3_module, "_S3StorageClass", None)
        _block_modules(
            monkeypatch,
            "storages",
            "storages.backends",
            "storages.backends.s3",
            "storages.backends.s3boto3",
            "storages.utils",
            "boto3",
        )

        with pytest.raises(ImportError, match=r"pip install karni\[s3\]"):
            _ = karni.storage.S3Storage

    def test_make_thumbnail_error_mentions_images_extra(
        self, monkeypatch: pytest.MonkeyPatch, storage: FileSystemStorage
    ) -> None:
        _block_modules(monkeypatch, "PIL", "PIL.Image")

        # Pillow is imported before any storage I/O, so no source is needed.
        with pytest.raises(ImportError, match=r"pip install karni\[images\]"):
            make_thumbnail("missing.png", storage=storage)

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            _ = karni.storage.does_not_exist  # type: ignore[attr-defined]

    def test_lazy_names_appear_in_dir(self) -> None:
        assert "S3Storage" in dir(karni.storage)
        assert "get_storage" in dir(karni.storage)


class TestS3StorageWhenInstalled:
    """Behaviour of the built class when the s3 extra is present."""

    @pytest.fixture(autouse=True)
    def _require_s3_deps(self) -> None:
        pytest.importorskip("storages")
        pytest.importorskip("boto3")

    def test_class_is_cached_and_shared(self) -> None:
        from karni.storage import s3 as s3_module

        assert karni.storage.S3Storage is s3_module.S3Storage
        assert karni.storage.S3Storage is karni.storage.S3Storage
        assert issubclass(karni.storage.S3Storage, Storage)

    def test_reads_aws_settings_including_endpoint(self) -> None:
        with override_settings(
            AWS_STORAGE_BUCKET_NAME="bucket",
            AWS_S3_ENDPOINT_URL="http://minio:9000",
            AWS_S3_REGION_NAME="auto",
            AWS_ACCESS_KEY_ID="key",
            AWS_SECRET_ACCESS_KEY="secret",
        ):
            instance = karni.storage.S3Storage()

        assert instance.bucket_name == "bucket"
        assert instance.endpoint_url == "http://minio:9000"
        assert instance.region_name == "auto"
        assert instance.access_key == "key"
        assert instance.secret_key == "secret"

    def test_file_overwrite_defaults_off_but_is_overridable(self) -> None:
        with override_settings(AWS_STORAGE_BUCKET_NAME="bucket"):
            assert karni.storage.S3Storage().file_overwrite is False
        with override_settings(AWS_STORAGE_BUCKET_NAME="bucket", AWS_S3_FILE_OVERWRITE=True):
            assert karni.storage.S3Storage().file_overwrite is True

    def test_empty_string_settings_coerce_to_none(self) -> None:
        with override_settings(
            AWS_STORAGE_BUCKET_NAME="bucket",
            AWS_S3_ENDPOINT_URL="",
            AWS_S3_REGION_NAME="",
        ):
            instance = karni.storage.S3Storage()

        assert instance.endpoint_url is None
        assert instance.region_name is None

    def test_constructor_kwargs_override_settings(self) -> None:
        with override_settings(AWS_STORAGE_BUCKET_NAME="bucket"):
            instance = karni.storage.S3Storage(bucket_name="other")

        assert instance.bucket_name == "other"
