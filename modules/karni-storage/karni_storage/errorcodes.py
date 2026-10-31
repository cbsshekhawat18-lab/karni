"""karni-storage's error codes (prefix ``STORE``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain
STORE011`` and ``docs/errors.md`` include them. Codes are permanent: never
renumber or reuse one; append new codes at the end. This module's codes run
from STORE001 to STORE099.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode, docs_url

__all__ = ["CODES", "coded"]

_SOURCE = "karni_storage"


def coded(code: str, message: str) -> str:
    """``"<code>: <message> See <docs url>"``, the form every answer of the module takes."""
    return f"{code}: {message} See {docs_url(code)}"


CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="STORE001",
        title="KARNI_STORAGE_PROVIDER names no preset",
        kind="check",
        source=f"{_SOURCE}.presets",
        why=(
            "The preset gives core's S3 backend the endpoint, region and addressing style of "
            "the service. Without one, protected files have nowhere to go."
        ),
        fix=(
            "Set KARNI_STORAGE_PROVIDER to aws, r2, minio, spaces, b2 or gcs-interop (in "
            "karni.yaml: modules: {storage: {provider: r2}}). A service no preset knows is "
            "minio with its endpoint in AWS_S3_ENDPOINT_URL."
        ),
    ),
    ErrorCode(
        code="STORE002",
        title="The storage provider has no credentials",
        kind="check",
        source=f"{_SOURCE}.presets",
        why=(
            "With KARNI_STORAGE=s3 every upload and every signed download URL is signed with "
            "the access key. Without it each one fails in production."
        ),
        fix=(
            "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment (.env), with "
            "the access key of the provider's account (R2, Spaces, B2 and GCS HMAC keys use "
            "the same two names). On AWS with an instance or task role, set "
            "KARNI_STORAGE_CREDENTIALS=chain instead. Credentials never go in karni.yaml."
        ),
    ),
    ErrorCode(
        code="STORE003",
        title="The storage preset needs a value it does not have",
        kind="check",
        source=f"{_SOURCE}.presets",
        why=(
            "A preset builds the endpoint from the bucket's region (aws, spaces, b2), the "
            "account id (r2) or your server's URL (minio). Without it the backend talks to "
            "the wrong host."
        ),
        fix=(
            "Set what the message names in the environment: AWS_STORAGE_BUCKET_NAME (or "
            "KARNI_STORAGE_BUCKET), AWS_S3_REGION_NAME, R2_ACCOUNT_ID or AWS_S3_ENDPOINT_URL."
        ),
    ),
    ErrorCode(
        code="STORE004",
        title="karni_storage.urls is not included",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "The API gives each protected file as its download path, "
            "<resource>/<id>/files/<field>/. Without the include those paths answer 404 and "
            "nothing can be uploaded."
        ),
        fix=(
            'Add path("api/", include("karni_storage.urls")) to config/urls.py, next to '
            'path("api/", include("karni.api.urls")).'
        ),
    ),
    ErrorCode(
        code="STORE005",
        title="A karni-storage setting has a value it does not take",
        kind="check",
        source=f"{_SOURCE}.checks",
        why="The module would fail on the first upload or the first thumbnail.",
        fix=(
            "KARNI_STORAGE_UPLOAD_METHOD takes post, put or nothing. KARNI_STORAGE_CREDENTIALS "
            "takes keys or chain. KARNI_STORAGE_THUMBNAIL_SIZES maps a name to [width, height] "
            'in pixels, e.g. {"small": [160, 160]}.'
        ),
    ),
    ErrorCode(
        code="STORE006",
        title="A model with protected files has no viewset on the API",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "A protected file is served only after its row is retrieved through the model's "
            "own viewset. A model the API does not serve has files nobody can download."
        ),
        fix=(
            "Declare a BaseViewSet for the model (karni make viewset), or use a plain "
            "FileField if the files are not meant to be downloaded through the API."
        ),
    ),
    ErrorCode(
        code="STORE010",
        title="No protected file field there",
        kind="api",
        source=f"{_SOURCE}.access (answered with HTTP 404)",
        why=(
            "The path names a resource the API does not route, or a field that is not one of "
            "its model's protected fields, or one Karni.field_roles hides from you."
        ),
        fix="Use the download path the API returned for the field, or the field's own name.",
    ),
    ErrorCode(
        code="STORE011",
        title="The file is larger than the field allows",
        kind="api",
        source=f"{_SOURCE} (upload, confirm and the serializer field)",
        why="Each protected field has a size limit: its max_size, else KARNI_STORAGE_MAX_SIZE.",
        fix=(
            "Send a smaller file, or raise the field's max_size "
            "(ProtectedFileField(max_size=...)) or KARNI_STORAGE_MAX_SIZE."
        ),
    ),
    ErrorCode(
        code="STORE012",
        title="The field does not take files of that type",
        kind="api",
        source=f"{_SOURCE} (upload, confirm and the serializer field)",
        why=(
            "Each protected field lists the content types it takes. An image field takes "
            "JPEG, PNG, GIF and WebP by default. SVG is left out because it can carry script."
        ),
        fix="Send a file of an allowed type, or list the type in the field's content_types.",
    ),
    ErrorCode(
        code="STORE013",
        title="The upload token is not valid",
        kind="api",
        source=f"{_SOURCE}.tokens",
        why=(
            "A direct upload is attached to a row only with the token the upload and confirm "
            "steps gave this user for this field. A token that expired, was altered, belongs "
            "to someone else or to another field is refused, so nobody can attach another "
            "user's object."
        ),
        fix=(
            "Upload the file again: POST <resource>/files/<field>/upload/, send it to the "
            "bucket, POST .../confirm/, then save the row with the token confirm returned."
        ),
    ),
    ErrorCode(
        code="STORE014",
        title="The uploaded file is not in the bucket",
        kind="api",
        source=f"{_SOURCE}.views (confirm)",
        why="Confirm checks the object before any row may point at it.",
        fix=(
            "Send the file to the URL the upload step returned before its expiry, then "
            "confirm again."
        ),
    ),
    ErrorCode(
        code="STORE015",
        title="Direct uploads need the bucket",
        kind="api",
        source=f"{_SOURCE}.views (confirm)",
        why=(
            "On local storage (KARNI_STORAGE=local) the upload step answers method 'api': "
            "the file goes through the API with the row, so there is nothing to confirm."
        ),
        fix="Send the file in the row's create or update request (multipart).",
    ),
    ErrorCode(
        code="STORE016",
        title="No thumbnail size of that name",
        kind="api",
        source=f"{_SOURCE}.views (?size=)",
        why="Thumbnails are made in the sizes KARNI_STORAGE_THUMBNAIL_SIZES names.",
        fix="Use one of the names the message lists, or add the size to the setting.",
    ),
    ErrorCode(
        code="STORE017",
        title="The thumbnail is not ready",
        kind="api",
        source=f"{_SOURCE}.views (?size=, answered with HTTP 404)",
        why=(
            "Thumbnails are made by a Celery task after the image is confirmed or saved. "
            "Until it has run, or for a field that is not a protected image, there is none."
        ),
        fix=(
            "Try again shortly, show the full image meanwhile, and keep a Celery worker "
            "running. manage.py karni_thumbnails makes the missing ones."
        ),
    ),
    ErrorCode(
        code="STORE018",
        title="The row has no file in that field",
        kind="api",
        source=f"{_SOURCE}.views (answered with HTTP 404)",
        why="The field is empty on this row.",
        fix="Upload a file to the field first.",
    ),
    ErrorCode(
        code="STORE019",
        title="The download link is not valid",
        kind="api",
        source=f"{_SOURCE}.views (answered with HTTP 403)",
        why=(
            "A signed download link opens one file for KARNI_STORAGE_URL_EXPIRY seconds. "
            "It expired, was altered, or the file was replaced since."
        ),
        fix="Ask for a fresh link: GET the download path again.",
    ),
    ErrorCode(
        code="STORE020",
        title="A protected file's download path cannot be built",
        kind="exception",
        source=f"{_SOURCE}.fields (ProtectedFieldFile.url)",
        why=(
            "The path is <resource>/<id>/files/<field>/ under karni_storage.urls. It needs "
            "the include and a viewset that serves the model."
        ),
        fix=(
            'Add path("api/", include("karni_storage.urls")) to config/urls.py and declare '
            "a BaseViewSet for the model. karni check names which is missing (STORE004, "
            "STORE006)."
        ),
    ),
)
