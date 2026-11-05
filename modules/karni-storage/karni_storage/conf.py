"""Settings vocabulary for karni-storage.

:data:`DEFAULTS` is the module's **settings fragment**, exposed through the
``karni.settings`` entry point: :func:`karni.conf.karni_settings` merges it
into every project that installs karni-storage, after Karni's defaults and
before the project's own settings, new top-level names only.

Where protected files go follows core's ``KARNI_STORAGE``: ``local`` (the
development default) keeps them on disk under ``KARNI_STORAGE_ROOT`` and
streams them through the API, ``s3`` puts them in the bucket of the service
``KARNI_STORAGE_PROVIDER`` names. So the same project runs on a laptop
without credentials and in production on R2 or AWS.

The fragment is import-light: plain data and django-environ reads, and it
never touches ``django.conf.settings`` at import time. Credentials stay in the
environment (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY`` and, for R2,
``R2_ACCOUNT_ID``), are blank by default and are checked by ``karni check``
and at use, never at boot.

Override / escape hatch: define any of these names in ``settings.py`` (before
or after ``karni_settings()``) or set the environment variable of the same
name. ``STORAGES["protected"]`` (the alias ``KARNI_STORAGE_ALIAS`` names)
replaces the module's storage entirely.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # The S3-compatible service the files go to when KARNI_STORAGE is "s3":
    # aws, r2, minio, spaces, b2 or gcs-interop (karni_storage.presets).
    "KARNI_STORAGE_PROVIDER": env("KARNI_STORAGE_PROVIDER", default="aws"),
    # "keys": AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set. "chain":
    # boto3 finds them itself (an AWS instance or task role, a profile).
    "KARNI_STORAGE_CREDENTIALS": env("KARNI_STORAGE_CREDENTIALS", default="keys"),
    # The bucket of protected files. Empty: AWS_STORAGE_BUCKET_NAME.
    "KARNI_STORAGE_BUCKET": env("KARNI_STORAGE_BUCKET", default=""),
    # The key prefix of protected files inside the bucket.
    "KARNI_STORAGE_LOCATION": env("KARNI_STORAGE_LOCATION", default="protected"),
    # The directory of protected files on local storage. Empty: "protected"
    # next to MEDIA_ROOT, so the media URL never serves them.
    "KARNI_STORAGE_ROOT": env("KARNI_STORAGE_ROOT", default=""),
    # Seconds a signed download URL lives.
    "KARNI_STORAGE_URL_EXPIRY": env.int("KARNI_STORAGE_URL_EXPIRY", default=300),
    # Seconds a direct upload's presigned POST (or PUT) lives.
    "KARNI_STORAGE_UPLOAD_EXPIRY": env.int("KARNI_STORAGE_UPLOAD_EXPIRY", default=900),
    # "post" or "put". Empty: the preset's (POST where the service takes a POST policy).
    "KARNI_STORAGE_UPLOAD_METHOD": env("KARNI_STORAGE_UPLOAD_METHOD", default=""),
    # The size limit of a protected field without max_size, in bytes (10 MiB).
    "KARNI_STORAGE_MAX_SIZE": env.int("KARNI_STORAGE_MAX_SIZE", default=10 * 1024 * 1024),
    # Thumbnails of protected images: name -> [width, height] (a bounding box).
    "KARNI_STORAGE_THUMBNAIL_SIZES": env.json(
        "KARNI_STORAGE_THUMBNAIL_SIZES", default={"small": [160, 160], "medium": [640, 640]}
    ),
    # The format thumbnails are written in (Pillow's name).
    "KARNI_STORAGE_THUMBNAIL_FORMAT": env("KARNI_STORAGE_THUMBNAIL_FORMAT", default="WEBP"),
    # The rate limits of the three endpoints, per caller: download, upload and
    # confirm (scopes storage.download, ...). A rate under the scope in
    # REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] wins. None turns a limit off.
    "KARNI_STORAGE_THROTTLE_RATES": env.json(
        "KARNI_STORAGE_THROTTLE_RATES",
        default={"download": "1000/hour", "upload": "120/hour", "confirm": "120/hour"},
    ),
    # The STORAGES alias that, when the project defines it, replaces the
    # module's storage (an escape hatch: any backend).
    "KARNI_STORAGE_ALIAS": env("KARNI_STORAGE_ALIAS", default="protected"),
    # Cloudflare R2's account id: the r2 preset's endpoint is built from it.
    "R2_ACCOUNT_ID": env("R2_ACCOUNT_ID", default=""),
}
"""The karni-storage settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """Return the effective value of a karni-storage setting.

    Project settings win; :data:`DEFAULTS` is the fallback, so the accessor
    works whether or not the project assembled its settings through
    ``karni_settings()``.

    :raises KeyError: when ``name`` is not a karni-storage setting and the
        project has not defined it either.
    """
    return getattr(settings, name, DEFAULTS[name])


def on_s3() -> bool:
    """True when protected files go to a bucket: core's ``KARNI_STORAGE`` is ``"s3"``."""
    return str(getattr(settings, "KARNI_STORAGE", "local")) == "s3"
