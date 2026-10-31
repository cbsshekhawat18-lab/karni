"""The three endpoints of protected files, mounted by ``karni_storage.urls`` under the API.

* ``GET <resource>/<id>/files/<field>/`` retrieves the row through the
  model's own viewset first (:func:`karni_storage.access.retrieve`): 401 or
  403 from its gate, 404 for a row out of the caller's scope, a soft-deleted
  row or a missing one. Then, on a bucket, it redirects (302) to a signed URL
  that lives ``KARNI_STORAGE_URL_EXPIRY`` seconds, and on local storage it
  streams the file. ``?size=<name>`` serves a thumbnail instead,
  ``?download=1`` asks for an attachment. With ``Accept: application/json``
  it answers ``{"url", "expires_in", "name"}`` instead, for clients that send
  a token header and cannot follow a link with it: on local storage the url
  is this path with a signed ``?sig=``, which opens without a session.
* ``POST <resource>/files/<field>/upload/`` (callers the viewset lets create
  or change rows) takes ``{"name", "content_type", "size"}`` and answers a
  presigned POST (``{"method": "post", "url", "fields", ...}``) or PUT
  (``{"method": "put", "url", "headers", ...}``) for the browser to send the
  file straight to the bucket, with a ``token``. On local storage it answers
  ``{"method": "api"}``: send the file with the row instead.
* ``POST <resource>/files/<field>/confirm/`` takes ``{"token"}``, checks the
  object is in the bucket with an allowed size and type (deleting it when
  not), queues its thumbnails and answers ``{"token", "name", "size",
  "content_type"}``. The row's create or update takes that token as the
  field's value.

Files are served inline only for types a browser shows safely (images other
than SVG, PDF, plain text, audio and video), else as an attachment, always
with ``X-Content-Type-Options: nosniff``.

Override / escape hatch: the row's viewset decides who may do what. Put your
own ``path()`` before the include to replace one endpoint.
"""

from __future__ import annotations

import posixpath
import secrets
from typing import Any, ClassVar
from urllib.parse import urlencode

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import FileResponse, HttpResponseRedirect
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni_storage import conf
from karni_storage.access import Target, may_upload, resolve, retrieve
from karni_storage.errorcodes import coded
from karni_storage.serializers import content_type_of, limit_problem
from karni_storage.storage import is_s3, object_key, protected_storage, s3_client
from karni_storage.tokens import (
    TokenError,
    Upload,
    confirmed_token,
    download_token,
    read_download,
    read_upload,
    upload_token,
    user_key,
)

__all__ = ["ConfirmView", "FileView", "UploadView", "basename", "inline"]

#: Types a browser shows without running anything: served inline, the rest as attachments.
_INLINE = ("image/", "audio/", "video/")
_INLINE_EXACT = frozenset({"application/pdf", "text/plain"})


def basename(name: str) -> str:
    """The file name a download is saved as: the last part of the stored name."""
    return posixpath.basename(name) or "file"


def inline(content_type: str) -> bool:
    """True when a browser may show ``content_type`` inline (never SVG: it can carry script)."""
    if content_type == "image/svg+xml":
        return False
    return content_type in _INLINE_EXACT or content_type.startswith(_INLINE)


def _bad(code: str, message: str, field: str | None = None) -> ValidationError:
    detail = coded(code, message)
    return ValidationError({field: [detail]} if field else [detail], code=code)


_PATH = [
    OpenApiParameter("resource", OpenApiTypes.STR, OpenApiParameter.PATH, description="resource"),
    OpenApiParameter("field", OpenApiTypes.STR, OpenApiParameter.PATH, description="field"),
]


class FileView(APIView):
    """Experimental. ``GET <resource>/<id>/files/<field>/``: one row's protected file."""

    #: The row's own viewset is the gate (karni_storage.access.retrieve).
    permission_classes: ClassVar[list[Any]] = []

    def _name(self, target: Target, row: Any, size: str) -> str:
        value = getattr(row, target.field.attname, None)
        name = str(getattr(value, "name", "") or "")
        if not name:
            raise NotFound(coded("STORE018", "This row has no file in that field."), "STORE018")
        if not size:
            return name
        from karni_storage.thumbnails import find, sizes

        names = sizes()
        if size not in names:
            raise _bad(
                "STORE016",
                f"No thumbnail size {size!r}. Sizes: {', '.join(names) or 'none'}.",
                "size",
            )
        found = find(name, size) if target.field.makes_thumbnails else None
        if found is None:
            raise NotFound(
                coded("STORE017", f"The {size} thumbnail of this file is not ready."), "STORE017"
            )
        return found

    def _row_by_signature(self, target: Target, pk: str, size: str, signature: str) -> str:
        try:
            row = target.model._default_manager.filter(pk=pk).first()
        except (ValueError, TypeError, DjangoValidationError):  # a malformed key
            row = None
        if row is None:
            raise PermissionDenied(coded("STORE019", "That is not a valid download link."))
        stored = str(getattr(getattr(row, target.field.attname, None), "name", "") or "")
        try:
            read_download(
                signature,
                model=target.model._meta.label_lower,
                pk=pk,
                field=target.field.name,
                size=size,
                name=stored,
            )
        except TokenError as exc:
            raise PermissionDenied(str(exc)) from None
        return self._name(target, row, size)

    @extend_schema(
        parameters=[
            *_PATH,
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH, description="row"),
            OpenApiParameter("size", OpenApiTypes.STR, description="a thumbnail size name"),
            OpenApiParameter("download", OpenApiTypes.BOOL, description="as an attachment"),
            OpenApiParameter("sig", OpenApiTypes.STR, description="a signed link's signature"),
        ],
        responses={
            (200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY),
            302: OpenApiResponse(description="redirect to a signed URL in the bucket"),
        },
    )
    def get(self, request: Request, resource: str, pk: str, field: str) -> Any:
        """The file, a thumbnail of it (``?size=``) or, as JSON, a link to it."""
        target = resolve(resource, field)
        size = str(request.query_params.get("size") or "")
        signature = request.query_params.get("sig")
        if signature is not None:
            name = self._row_by_signature(target, pk, size, str(signature))
            return self._stream(name, request)
        row = retrieve(target, request, pk)
        name = self._name(target, row, size)
        expiry = int(conf.get("KARNI_STORAGE_URL_EXPIRY"))
        if "application/json" in request.META.get("HTTP_ACCEPT", ""):
            return Response(
                {
                    "url": self._link(request, target, row, size, name),
                    "expires_in": expiry,
                    "name": basename(name),
                }
            )
        if is_s3():
            response = HttpResponseRedirect(self._signed_url(request, name))
            response["Cache-Control"] = "private, no-store"
            return response
        return self._stream(name, request)

    def _disposition(self, request: Request, name: str) -> tuple[str, bool]:
        content_type = content_type_of(name, None)
        attachment = str(request.query_params.get("download") or "") in ("1", "true", "yes")
        return content_type, attachment or not inline(content_type)

    def _signed_url(self, request: Request, name: str) -> str:
        _content_type, attachment = self._disposition(request, name)
        storage = protected_storage()
        disposition = content_disposition_header(attachment, basename(name)) or "inline"
        url: str = storage.url(
            name,
            parameters={"ResponseContentDisposition": disposition},
            expire=int(conf.get("KARNI_STORAGE_URL_EXPIRY")),
        )
        return url

    def _link(self, request: Request, target: Target, row: Any, size: str, name: str) -> str:
        if is_s3():
            return self._signed_url(request, name)
        stored = str(getattr(getattr(row, target.field.attname, None), "name", "") or "")
        query = {
            "sig": download_token(
                model=target.model._meta.label_lower,
                pk=row.pk,
                field=target.field.name,
                size=size,
                name=stored,
            )
        }
        if size:
            query["size"] = size
        if request.query_params.get("download"):
            query["download"] = "1"
        return request.build_absolute_uri(f"{request.path}?{urlencode(query)}")

    def _stream(self, name: str, request: Request) -> FileResponse:
        content_type, attachment = self._disposition(request, name)
        try:
            handle = protected_storage().open(name, "rb")
        except FileNotFoundError:
            raise NotFound(
                coded("STORE018", "The file is missing from the storage."), "STORE018"
            ) from None
        response = FileResponse(
            handle, content_type=content_type, as_attachment=attachment, filename=basename(name)
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = f"private, max-age={int(conf.get('KARNI_STORAGE_URL_EXPIRY'))}"
        return response


class UploadRequestSerializer(serializers.Serializer):
    """What the upload step takes: the file's name, type and size, before sending it."""

    name = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=255, required=False, allow_blank=True)
    size = serializers.IntegerField(min_value=0)


class ConfirmRequestSerializer(serializers.Serializer):
    """What confirm takes: the token the upload step gave."""

    token = serializers.CharField()


def _storage_name(target: Target, filename: str) -> str:
    """A fresh name for an upload: the field's upload_to, a random directory, the file's name."""
    field = target.field
    generated = field.generate_filename(target.model(), basename(filename))
    directory, base = posixpath.split(generated)
    stem, dot, extension = base.rpartition(".")
    if not dot:
        stem, extension = base, ""
    room = int(field.max_length or 100) - len(directory) - 20 - len(extension)
    if room < 1:
        raise _bad("STORE011", f"{field.name}'s upload_to leaves no room for a file name.")
    stem = stem[:room] or "file"
    return posixpath.join(directory, secrets.token_hex(8), f"{stem}{dot}{extension}")


class UploadView(APIView):
    """Experimental. ``POST <resource>/files/<field>/upload/``: where the browser sends a file."""

    permission_classes: ClassVar[list[Any]] = []

    @extend_schema(
        parameters=_PATH, request=UploadRequestSerializer, responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request: Request, resource: str, field: str) -> Response:
        """A presigned POST or PUT for one file, or ``{"method": "api"}`` on local storage."""
        target = resolve(resource, field)
        may_upload(target, request)
        payload = UploadRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        name = str(payload.validated_data["name"])
        size = int(payload.validated_data["size"])
        content_type = content_type_of(name, payload.validated_data.get("content_type"))
        problem = limit_problem(target.field, size, content_type)
        if problem is not None:
            raise _bad(*problem)
        limit = int(target.field.size_limit)
        answer: dict[str, Any] = {
            "max_size": limit,
            "content_types": list(target.field.allowed_content_types),
        }
        if not is_s3():
            return Response({"method": "api", **answer})
        from karni_storage.presets import upload_method

        stored = _storage_name(target, name)
        storage = protected_storage()
        key = object_key(stored, storage)
        bucket = str(getattr(storage, "bucket_name", ""))
        expiry = int(conf.get("KARNI_STORAGE_UPLOAD_EXPIRY"))
        client = s3_client(storage)
        method = upload_method()
        if method == "put":
            url = client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expiry,
                HttpMethod="PUT",
            )
            answer.update(method="put", url=url, headers={"Content-Type": content_type})
        else:
            post = client.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, limit]],
                ExpiresIn=expiry,
            )
            answer.update(method="post", url=post["url"], fields=post["fields"])
        token = upload_token(
            Upload(
                name=stored,
                model=target.model._meta.label_lower,
                field=target.field.name,
                user=user_key(request.user),
                max_size=limit,
                content_type=content_type,
            )
        )
        answer.update(token=token, name=basename(stored), expires_in=expiry)
        return Response(answer)


class ConfirmView(APIView):
    """Experimental. ``POST <resource>/files/<field>/confirm/``: check a direct upload."""

    permission_classes: ClassVar[list[Any]] = []

    @extend_schema(
        parameters=_PATH, request=ConfirmRequestSerializer, responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request: Request, resource: str, field: str) -> Response:
        """The object checked (exists, size, type) and a token the row's save takes."""
        target = resolve(resource, field)
        may_upload(target, request)
        if not is_s3():
            raise _bad(
                "STORE015",
                "Protected files are on local storage: send the file with the row instead.",
            )
        payload = ConfirmRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        label = target.model._meta.label_lower
        try:
            upload = read_upload(
                str(payload.validated_data["token"]),
                model=label,
                field=target.field.name,
                user=request.user,
            )
        except TokenError as exc:
            raise _bad(exc.code, exc.message, "token") from None
        storage = protected_storage()
        client = s3_client(storage)
        bucket = str(getattr(storage, "bucket_name", ""))
        key = object_key(upload.name, storage)
        head = _head(client, bucket, key)
        if head is None:
            raise _bad("STORE014", "The file is not in the bucket. Send it, then confirm.")
        size = int(head.get("ContentLength") or 0)
        content_type = content_type_of(upload.name, head.get("ContentType"))
        problem = limit_problem(target.field, size, content_type)
        if problem is None and upload.content_type and content_type != upload.content_type:
            problem = (
                "STORE012",
                f"The file was sent as {content_type}, not the {upload.content_type} declared.",
            )
        if problem is not None:
            client.delete_object(Bucket=bucket, Key=key)
            raise _bad(*problem)
        if target.field.makes_thumbnails:
            name = upload.name

            def queue() -> None:
                from karni_storage.tasks import make_thumbnails

                make_thumbnails.delay(name)

            transaction.on_commit(queue)
        token = confirmed_token(
            Upload(name=upload.name, model=label, field=target.field.name, user=upload.user)
        )
        return Response(
            {
                "token": token,
                "name": basename(upload.name),
                "size": size,
                "content_type": content_type,
            },
            status=status.HTTP_200_OK,
        )


def _head(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    """The object's metadata, or ``None`` when the bucket has no such object."""
    from botocore.exceptions import ClientError

    try:
        head: dict[str, Any] = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("404", "NoSuchKey", "NotFound") or status_code == 404:
            return None
        raise
    return head
