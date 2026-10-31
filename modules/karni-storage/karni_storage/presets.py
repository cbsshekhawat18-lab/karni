"""Provider presets: one setting names the S3-compatible service, the preset knows the rest.

``KARNI_STORAGE_PROVIDER`` names a preset. The preset gives core's S3 backend
(:class:`karni.storage.S3Storage`) the endpoint, the region and the
addressing style of that service, from the credentials and ids already in the
environment, so a project never writes an endpoint URL by hand:

* ``aws``: Amazon S3. AWS's own endpoint, the region required, virtual-hosted
  addressing, uploads by presigned POST.
* ``r2``: Cloudflare R2. ``https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com``,
  region ``auto``, path addressing, uploads by presigned PUT.
* ``minio``: MinIO. Your server's ``AWS_S3_ENDPOINT_URL``, region
  ``us-east-1``, path addressing, uploads by presigned POST.
* ``spaces``: DigitalOcean Spaces. ``https://<region>.digitaloceanspaces.com``,
  the region required, virtual-hosted addressing, uploads by presigned PUT.
* ``b2``: Backblaze B2. ``https://s3.<region>.backblazeb2.com``, the region
  required, virtual-hosted addressing, uploads by presigned PUT.
* ``gcs-interop``: Google Cloud Storage through its XML API with HMAC keys.
  ``https://storage.googleapis.com``, region ``auto``, path addressing,
  uploads by presigned PUT.

The region is ``AWS_S3_REGION_NAME``. Upload is how a browser sends a file
straight to the bucket: a presigned POST, whose policy the service enforces
(size and type), where the service takes one, else a presigned PUT. The
confirm step checks the size and type of every upload either way.

Override / escape hatch: an explicit ``AWS_S3_ENDPOINT_URL`` always wins over
the preset's endpoint (an R2 jurisdiction, a private endpoint),
``AWS_S3_ADDRESSING_STYLE`` over its addressing style and
``KARNI_STORAGE_UPLOAD_METHOD`` over its upload method. A service no preset
knows is ``minio`` with its endpoint in ``AWS_S3_ENDPOINT_URL``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final

from django.conf import settings

from karni_storage import conf

__all__ = ["PRESETS", "Preset", "problems", "s3_options", "upload_method"]


@dataclass(frozen=True)
class Preset:
    """Experimental. What one S3-compatible service needs from core's S3 backend.

    ``endpoint`` is a template with ``{region}`` or ``{account_id}``, empty for
    AWS's own endpoint, or ``"setting"`` when the endpoint is the project's
    ``AWS_S3_ENDPOINT_URL`` (a server of your own). ``region`` is a fixed
    region, or empty when ``AWS_S3_REGION_NAME`` must give it.
    """

    name: str
    title: str
    endpoint: str
    region: str
    addressing_style: str
    upload_method: str

    @property
    def needs_region(self) -> bool:
        return not self.region

    @property
    def needs_account(self) -> bool:
        return "{account_id}" in self.endpoint


PRESETS: Final[dict[str, Preset]] = {
    preset.name: preset
    for preset in (
        Preset("aws", "Amazon S3", "", "", "virtual", "post"),
        Preset(
            "r2",
            "Cloudflare R2",
            "https://{account_id}.r2.cloudflarestorage.com",
            "auto",
            "path",
            "put",
        ),
        Preset("minio", "MinIO", "setting", "us-east-1", "path", "post"),
        Preset(
            "spaces",
            "DigitalOcean Spaces",
            "https://{region}.digitaloceanspaces.com",
            "",
            "virtual",
            "put",
        ),
        Preset("b2", "Backblaze B2", "https://s3.{region}.backblazeb2.com", "", "virtual", "put"),
        Preset(
            "gcs-interop",
            "Google Cloud Storage (XML API, HMAC keys)",
            "https://storage.googleapis.com",
            "auto",
            "path",
            "put",
        ),
    )
}
"""Experimental. Every preset, by the name ``KARNI_STORAGE_PROVIDER`` takes."""

#: Environment variables that say boto3 finds the credentials itself (a role, a profile).
_CHAIN_MARKERS: Final = (
    "AWS_PROFILE",
    "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
)


def _setting(name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def preset() -> Preset:
    """The preset ``KARNI_STORAGE_PROVIDER`` names.

    :raises karni.exceptions.KarniLookupError: ``STORE001`` for a name no preset has.
    """
    from karni.exceptions import KarniLookupError

    name = str(conf.get("KARNI_STORAGE_PROVIDER") or "").strip()
    found = PRESETS.get(name)
    if found is None:
        raise KarniLookupError(
            f"KARNI_STORAGE_PROVIDER is {name!r}, which no preset has. Use one of: "
            f"{', '.join(PRESETS)}.",
            code="STORE001",
        )
    return found


def bucket() -> str:
    """The bucket of protected files: ``KARNI_STORAGE_BUCKET``, else ``AWS_STORAGE_BUCKET_NAME``."""
    return str(conf.get("KARNI_STORAGE_BUCKET") or "").strip() or _setting(
        "AWS_STORAGE_BUCKET_NAME"
    )


def endpoint(found: Preset) -> str:
    """The endpoint URL: ``AWS_S3_ENDPOINT_URL`` when set, else the preset's."""
    explicit = _setting("AWS_S3_ENDPOINT_URL")
    if explicit or found.endpoint == "setting":
        return explicit
    return found.endpoint.format(
        region=_setting("AWS_S3_REGION_NAME"),
        account_id=str(conf.get("R2_ACCOUNT_ID") or "").strip(),
    )


def region(found: Preset) -> str:
    """The region: ``AWS_S3_REGION_NAME`` when set, else the preset's fixed one."""
    return _setting("AWS_S3_REGION_NAME") or found.region


def upload_method(found: Preset | None = None) -> str:
    """``post`` or ``put``: ``KARNI_STORAGE_UPLOAD_METHOD`` when set, else the preset's."""
    chosen = str(conf.get("KARNI_STORAGE_UPLOAD_METHOD") or "").strip().lower()
    if chosen:
        return chosen
    return (found or preset()).upload_method


def s3_options() -> dict[str, Any]:
    """Experimental. The keyword arguments core's S3 backend takes for protected files.

    The preset's endpoint, region and addressing style, SigV4 signing (every
    preset signs that way), the bucket and key prefix of protected files,
    signed URLs only (never a public custom domain) and no overwriting.

    :raises karni.exceptions.KarniLookupError: ``STORE001`` for an unknown preset.
    """
    found = preset()
    addressing = _setting("AWS_S3_ADDRESSING_STYLE") or found.addressing_style
    return {
        "bucket_name": bucket(),
        "location": str(conf.get("KARNI_STORAGE_LOCATION") or "").strip("/"),
        "endpoint_url": endpoint(found) or None,
        "region_name": region(found) or None,
        "addressing_style": addressing,
        "signature_version": "s3v4",
        "querystring_auth": True,
        "querystring_expire": int(conf.get("KARNI_STORAGE_URL_EXPIRY")),
        "custom_domain": None,
        "file_overwrite": False,
    }


def _has_chain_credentials() -> bool:
    return bool(_setting("AWS_S3_SESSION_PROFILE")) or any(
        os.environ.get(name) for name in _CHAIN_MARKERS
    )


def problems() -> list[str]:
    """Experimental. What stops the preset from working, each message starting with its code.

    Empty when protected files stay on local storage (``KARNI_STORAGE`` is
    not ``"s3"``) except for an unknown preset name or upload method, which
    are wrong everywhere.
    """
    found: Preset | None
    out: list[str] = []
    name = str(conf.get("KARNI_STORAGE_PROVIDER") or "").strip()
    found = PRESETS.get(name)
    if found is None:
        out.append(
            f"STORE001: KARNI_STORAGE_PROVIDER is {name!r}, which no preset has. "
            f"Use one of: {', '.join(PRESETS)}."
        )
    method = str(conf.get("KARNI_STORAGE_UPLOAD_METHOD") or "").strip().lower()
    if method and method not in ("post", "put"):
        out.append(
            f"STORE005: KARNI_STORAGE_UPLOAD_METHOD is {method!r}. Use post, put, or leave it "
            "empty for the preset's."
        )
    if found is None or not conf.on_s3():
        return out
    credentials = str(conf.get("KARNI_STORAGE_CREDENTIALS") or "keys").strip()
    keys = _setting("AWS_ACCESS_KEY_ID") and _setting("AWS_SECRET_ACCESS_KEY")
    if credentials not in ("keys", "chain"):
        out.append(f"STORE005: KARNI_STORAGE_CREDENTIALS is {credentials!r}. Use keys or chain.")
    elif not keys and not (credentials == "chain" or _has_chain_credentials()):
        how = (
            " Or, on AWS with an instance or task role, set KARNI_STORAGE_CREDENTIALS=chain."
            if found.name == "aws"
            else ""
        )
        out.append(
            f"STORE002: KARNI_STORAGE is s3 and the {found.name} preset has no credentials: "
            "set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment (.env), with "
            f"the access key of your {found.title} account.{how}"
        )
    missing = []
    if not bucket():
        missing.append("AWS_STORAGE_BUCKET_NAME (or KARNI_STORAGE_BUCKET): the bucket")
    if found.needs_region and not _setting("AWS_S3_REGION_NAME"):
        missing.append(f"AWS_S3_REGION_NAME: the region of the {found.title} bucket")
    if (
        found.needs_account
        and not _setting("AWS_S3_ENDPOINT_URL")
        and not str(conf.get("R2_ACCOUNT_ID") or "").strip()
    ):
        missing.append("R2_ACCOUNT_ID: the account id the R2 dashboard shows")
    if found.endpoint == "setting" and not _setting("AWS_S3_ENDPOINT_URL"):
        missing.append(f"AWS_S3_ENDPOINT_URL: the URL of your {found.title} server")
    for item in missing:
        out.append(f"STORE003: the {found.name} preset needs {item}. Set it in the environment.")
    return out
