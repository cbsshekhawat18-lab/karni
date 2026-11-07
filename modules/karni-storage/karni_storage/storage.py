"""Where protected files live: a private bucket, or a directory the media URL never serves.

:func:`protected_storage` is the storage every protected field reads and
writes. It is chosen per call, from the settings at that moment:

1. ``STORAGES[KARNI_STORAGE_ALIAS]`` (``"protected"``) when the project
   defines it: any backend, the escape hatch.
2. ``KARNI_STORAGE = "s3"``: core's :class:`karni.storage.S3Storage`
   configured by the provider preset (:func:`karni_storage.presets.s3_options`),
   with signed URLs only.
3. Otherwise a ``FileSystemStorage`` at ``KARNI_STORAGE_ROOT`` (default:
   ``protected`` next to ``MEDIA_ROOT``) with no base URL, so no URL serves
   it: the API streams its files after the row's access check.

:class:`ProtectedStorage` is what a protected field holds: a thin
``Storage`` that forwards every call to :func:`protected_storage`, so a
setting changed in a test (or per environment) takes effect without
re-creating the model's fields, and migrations never record a backend.

Override / escape hatch: define ``STORAGES["protected"]`` in ``settings.py``,
or pass ``storage=`` to one field.
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage
from django.core.signals import setting_changed
from django.utils.deconstruct import deconstructible

from karni_storage import conf

__all__ = [
    "PrivateFileSystemStorage",
    "ProtectedStorage",
    "is_s3",
    "object_key",
    "protected_storage",
    "s3_client",
]

_cached: Storage | None = None


def _build() -> Storage:
    alias = str(conf.get("KARNI_STORAGE_ALIAS") or "")
    if alias and alias in getattr(settings, "STORAGES", {}):
        from django.core.files.storage import storages

        return storages[alias]
    if conf.on_s3():
        from karni.storage import S3Storage

        from karni_storage.presets import s3_options

        storage: Storage = S3Storage(**s3_options())
        return storage
    root = str(conf.get("KARNI_STORAGE_ROOT") or "").strip()
    if not root:
        root = str(Path(str(getattr(settings, "MEDIA_ROOT", "") or "media")).parent / "protected")
    return PrivateFileSystemStorage(location=root)


def protected_storage() -> Storage:
    """Experimental. The storage of protected files (see the module docstring for the choice)."""
    global _cached
    if _cached is None:
        _cached = _build()
    return _cached


def _forget(**kwargs: Any) -> None:
    """Drop the cached storage when a setting it reads changes (``override_settings``)."""
    global _cached
    _cached = None


setting_changed.connect(_forget, dispatch_uid="karni_storage.storage.forget")


def is_s3(storage: Storage | None = None) -> bool:
    """True when ``storage`` (default: the protected one) talks to an S3-compatible service."""
    target = storage if storage is not None else protected_storage()
    if isinstance(target, ProtectedStorage):
        target = protected_storage()
    return hasattr(target, "bucket_name") and hasattr(target, "connection")


def s3_client(storage: Storage | None = None) -> Any:
    """The boto3 client of the protected S3 storage (signing is local: no request is made)."""
    target = storage if storage is not None else protected_storage()
    return target.connection.meta.client


def object_key(name: str, storage: Storage | None = None) -> str:
    """The object key in the bucket for the file ``name``: the location prefix, then the name."""
    target = storage if storage is not None else protected_storage()
    location = str(getattr(target, "location", "") or "").strip("/")
    clean = posixpath.normpath(name.replace("\\", "/")).lstrip("/")
    if clean.startswith("..") or clean in (".", ""):
        from django.core.exceptions import SuspiciousFileOperation

        raise SuspiciousFileOperation(f"{name!r} is not a file name inside the storage.")
    return f"{location}/{clean}" if location else clean


class PrivateFileSystemStorage(FileSystemStorage):
    """Experimental. A directory of protected files: it has no URL, the API streams them.

    Override / escape hatch: ``STORAGES["protected"]`` replaces it.
    """

    def url(self, name: str | None) -> str:
        from karni.exceptions import KarniValueError

        raise KarniValueError(
            "Protected files have no public URL: the API serves them at the row's download path "
            "(<resource>/<id>/files/<field>/).",
            code="STORE020",
        )


@deconstructible(path="karni_storage.storage.ProtectedStorage")
class ProtectedStorage(Storage):
    """Experimental. A protected field's storage: each call goes to :func:`protected_storage`.

    Override / escape hatch: ``STORAGES["protected"]`` replaces the target,
    or a field takes ``storage=`` of its own.
    """

    @property
    def target(self) -> Storage:
        return protected_storage()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(protected_storage(), name)

    def open(self, name: str, mode: str = "rb") -> Any:
        return self.target.open(name, mode)

    def save(self, name: str | None, content: Any, max_length: int | None = None) -> str:
        return self.target.save(name, content, max_length=max_length)

    def get_valid_name(self, name: str) -> str:
        return self.target.get_valid_name(name)

    def get_alternative_name(self, file_root: str, file_ext: str) -> str:
        return self.target.get_alternative_name(file_root, file_ext)

    def get_available_name(self, name: str, max_length: int | None = None) -> str:
        return self.target.get_available_name(name, max_length=max_length)

    def generate_filename(self, filename: str) -> str:
        return self.target.generate_filename(filename)

    def path(self, name: str) -> str:
        return self.target.path(name)

    def delete(self, name: str) -> None:
        self.target.delete(name)

    def exists(self, name: str) -> bool:
        return self.target.exists(name)

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        return self.target.listdir(path)

    def size(self, name: str) -> int:
        return self.target.size(name)

    def url(self, name: str | None) -> str:
        return self.target.url(name)

    def get_accessed_time(self, name: str) -> Any:
        return self.target.get_accessed_time(name)

    def get_created_time(self, name: str) -> Any:
        return self.target.get_created_time(name)

    def get_modified_time(self, name: str) -> Any:
        return self.target.get_modified_time(name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ProtectedStorage)

    def __hash__(self) -> int:
        return hash(ProtectedStorage)
