"""Storage backends and helpers for Karni.

This package provides:

* :class:`karni.storage.S3Storage` -- an S3-compatible media backend built on
  django-storages/boto3 (works with AWS S3, MinIO, Cloudflare R2, ...). It is
  exposed lazily via module ``__getattr__`` so that ``import karni.storage``
  succeeds with only the core dependencies installed; the optional
  dependencies are only required when the class is actually accessed
  (install them with ``pip install karni[s3]``).
* :func:`get_storage` -- a small helper returning the storage backend Django
  has configured for a given alias.

Which backend serves as the project default is driven by the
``KARNI_STORAGE`` environment variable (``"local"`` or ``"s3"``) through
``karni.conf``, and can always be overridden by assigning ``STORAGES`` in the
project's ``settings.py`` after (or instead of) calling ``karni_settings()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.core.files.storage import Storage

    from karni.storage.s3 import S3Storage as S3Storage  # noqa: F401

__all__ = ["S3Storage", "get_storage"]


def get_storage(alias: str = "default") -> Storage:
    """Return the storage backend Django has configured for ``alias``.

    This is a thin convenience wrapper around
    ``django.core.files.storage.storages[alias]`` so Karni code (and project
    code) never has to hard-code a backend class.

    Args:
        alias: The ``STORAGES`` alias to resolve. Defaults to ``"default"``,
            i.e. the media storage selected via the ``KARNI_STORAGE``
            environment variable (or an explicit ``STORAGES`` override in the
            project's ``settings.py``).

    Returns:
        The configured, ready-to-use :class:`~django.core.files.storage.Storage`
        instance for that alias.

    Override / escape hatch:
        Change the backend by setting ``STORAGES[alias]["BACKEND"]`` in the
        project's ``settings.py`` (or by pointing ``KARNI_STORAGE`` at
        ``"s3"``/``"local"``); this helper always reflects the live Django
        configuration and needs no changes of its own.
    """
    from django.core.files.storage import storages

    return storages[alias]


def __getattr__(name: str) -> Any:
    """Lazily expose :class:`S3Storage` without importing optional deps.

    Accessing ``karni.storage.S3Storage`` (including via Django's
    ``import_string``, which is how the ``STORAGES`` setting resolves it)
    imports :mod:`karni.storage.s3` on first use. If django-storages/boto3
    are not installed, that access raises an ``ImportError`` telling you to
    ``pip install karni[s3]``.
    """
    if name == "S3Storage":
        from karni.storage import s3

        return s3.S3Storage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include lazy attributes in ``dir(karni.storage)`` for discoverability."""
    return sorted(set(globals()) | set(__all__))
