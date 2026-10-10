"""S3-compatible media storage for Karni, built on django-storages.

The concrete :class:`S3Storage` class is created lazily (on first attribute
access) so that this module -- and therefore ``karni`` itself -- imports
cleanly when the optional S3 dependencies are not installed. Install them
with::

    pip install karni[s3]

The backend is selected for a project by setting the ``KARNI_STORAGE``
environment variable to ``"s3"`` (see ``karni.conf``), which points Django's
``STORAGES["default"]["BACKEND"]`` at ``"karni.storage.S3Storage"``. Projects
can always swap in their own backend by overriding ``STORAGES`` in
``settings.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karni.exceptions import KarniImportError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from storages.backends.s3 import S3Storage as S3Storage  # noqa: F401

__all__ = ["S3Storage"]

_INSTALL_HINT = (
    "karni.storage.S3Storage requires the optional S3 dependencies "
    "(django-storages and boto3). Install them with: pip install karni[s3]"
)

#: Settings whose empty-string value (the karni.conf env default) is treated
#: as "not configured" and coerced to None so boto3 falls back to its own
#: defaults (region resolution, IAM-role credentials, real AWS endpoint).
_EMPTY_MEANS_UNSET = (
    "access_key",
    "secret_key",
    "security_token",
    "session_profile",
    "region_name",
    "endpoint_url",
)

_S3StorageClass: type | None = None


def _build_s3_storage_class() -> type:
    """Import django-storages and build the Karni ``S3Storage`` subclass.

    Prefers the current ``storages.backends.s3.S3Storage`` base and falls
    back to ``storages.backends.s3boto3.S3Boto3Storage`` on older
    django-storages releases. Raises ``ImportError`` with an install hint
    (``pip install karni[s3]``) when neither is available.
    """
    try:
        from storages.backends.s3 import S3Storage as _BaseS3Storage
    except ImportError:
        try:  # django-storages < 1.14 shipped the backend as s3boto3
            from storages.backends.s3boto3 import (  # type: ignore[no-redef]
                S3Boto3Storage as _BaseS3Storage,
            )
        except ImportError as exc:
            raise KarniImportError(_INSTALL_HINT, code="E501") from exc

    from storages.utils import setting

    class S3Storage(_BaseS3Storage):  # type: ignore[misc, valid-type]
        """S3-compatible media storage with Karni defaults.

        Configuration is read from Django settings (which ``karni.conf``
        populates from environment variables of the same names):

        * ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` -- credentials.
          Left empty, boto3's own credential chain is used (env vars,
          shared config, IAM/instance roles).
        * ``AWS_STORAGE_BUCKET_NAME`` -- the bucket (required for ``"s3"``
          mode; startup validation enforces this).
        * ``AWS_S3_ENDPOINT_URL`` -- point at any S3-compatible endpoint
          such as MinIO or Cloudflare R2; empty means real AWS S3.
        * ``AWS_S3_REGION_NAME`` -- region; empty defers to boto3.
        * ``AWS_S3_FILE_OVERWRITE`` -- Karni flips django-storages' default
          to ``False`` so uploads never silently replace existing objects;
          set this to ``True`` in settings to restore overwriting.
        * Every other ``AWS_*`` setting understood by django-storages
          (``AWS_QUERYSTRING_AUTH``, ``AWS_DEFAULT_ACL``,
          ``AWS_S3_OBJECT_PARAMETERS``, ``AWS_S3_CUSTOM_DOMAIN``, ...)
          works unchanged.

        Override / escape hatch:
            Any of the above can be changed per-instance via constructor
            keyword arguments (e.g. ``S3Storage(bucket_name="other")``),
            per-project via the ``AWS_*`` Django settings, or by
            subclassing and overriding class attributes /
            :meth:`get_default_settings`, exactly as with django-storages.
            To stop using this backend entirely, override
            ``STORAGES["default"]`` in ``settings.py``.
        """

        def get_default_settings(self) -> dict[str, Any]:
            """Return django-storages defaults adjusted for Karni.

            Two adjustments on top of ``super().get_default_settings()``:

            * ``file_overwrite`` defaults to ``False`` (an explicit
              ``AWS_S3_FILE_OVERWRITE`` Django setting still wins).
            * Empty-string values for credentials, session profile, region
              and endpoint URL -- the ``karni.conf`` environment defaults --
              are coerced to ``None`` so boto3 applies its normal fallbacks
              instead of choking on ``""``.

            Override this method in a subclass to change any default; Django
            settings and constructor kwargs continue to take precedence.
            """
            defaults: dict[str, Any] = super().get_default_settings()
            defaults["file_overwrite"] = setting("AWS_S3_FILE_OVERWRITE", False)
            for key in _EMPTY_MEANS_UNSET:
                if key in defaults and defaults[key] == "":
                    defaults[key] = None
            return defaults

    S3Storage.__module__ = __name__
    S3Storage.__qualname__ = "S3Storage"
    return S3Storage


def __getattr__(name: str) -> Any:
    """Build and cache the ``S3Storage`` class on first access.

    Keeps ``import karni.storage.s3`` dependency-free while ensuring every
    access (including Django's ``import_string`` on the ``STORAGES``
    backend path) returns the same class object.
    """
    if name == "S3Storage":
        global _S3StorageClass
        if _S3StorageClass is None:
            _S3StorageClass = _build_s3_storage_class()
        return _S3StorageClass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include the lazily-built class in ``dir()`` output."""
    return sorted(set(globals()) | set(__all__))
