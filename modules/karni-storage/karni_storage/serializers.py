"""The serializer fields of protected files, and their OpenAPI description.

Every ``ModelSerializer``, Karni's generated ones included, renders a
protected field with :class:`ProtectedFileSerializerField` (or the image
variant): :class:`karni_storage.apps.KarniStorageConfig` maps the model
fields to them in DRF's ``serializer_field_mapping``. The field

* answers the row's **download path** (absolute with the request), never a
  public URL, because the value's ``url`` is that path;
* takes a **file** sent through the API (multipart), checked against the
  field's ``max_size`` and ``content_types``;
* takes a **confirmed upload token** (from ``POST
  <resource>/files/<field>/confirm/``) as a string, or as a file part of
  type ``application/vnd.karni.upload`` whose content is the token, which is
  how a form that sends files as multipart passes one. The token must be this
  user's, for this field.

The OpenAPI schema keeps the file field's types (binary in requests, a URI in
responses) and adds ``x-karni-storage``: ``{"protected": true, "max_size",
"content_types", "thumbnails"}``.

Override / escape hatch: declare the field yourself on a serializer of your
own, or subclass these and map them in ``serializer_field_mapping``.
"""

from __future__ import annotations

import mimetypes
from typing import Any, Final

from django.core.exceptions import FieldDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from rest_framework import serializers

from karni_storage.errorcodes import coded

__all__ = [
    "UPLOAD_REFERENCE_TYPE",
    "ProtectedFileSerializerField",
    "ProtectedImageSerializerField",
    "content_type_of",
    "limit_problem",
]

#: The content type of a file part that carries a confirmed upload token instead of a file.
UPLOAD_REFERENCE_TYPE: Final = "application/vnd.karni.upload"

#: A token is a few hundred bytes. A larger reference part is not one.
_REFERENCE_LIMIT: Final = 4096


def content_type_of(name: str, declared: str | None) -> str:
    """A file's content type: the one declared (without parameters), else guessed from its name."""
    clean = (declared or "").split(";", 1)[0].strip().lower()
    if clean:
        return clean
    guessed, _encoding = mimetypes.guess_type(name)
    return (guessed or "application/octet-stream").lower()


def limit_problem(model_field: Any, size: int, content_type: str) -> tuple[str, str] | None:
    """``(code, message)`` when a file of that size and type breaks the field's limits."""
    limit = int(model_field.size_limit)
    if size > limit:
        return "STORE011", f"The file is {size} bytes. {model_field.name} takes at most {limit}."
    if size <= 0:
        return "STORE011", "The file is empty."
    allowed = model_field.allowed_content_types
    if allowed and content_type not in allowed:
        return (
            "STORE012",
            f"{model_field.name} does not take {content_type}. It takes: {', '.join(allowed)}.",
        )
    return None


class _Protected:
    """What both serializer fields share: tokens, limits and the model field behind them."""

    source: str
    parent: Any
    context: Any

    def model_field(self) -> Any:
        model = self.parent.Meta.model
        return model._meta.get_field(self.source)

    def _token(self, data: Any) -> str | None:
        if isinstance(data, str):
            return data
        if isinstance(data, UploadedFile):
            if content_type_of("", data.content_type) != UPLOAD_REFERENCE_TYPE:
                return None
            if (data.size or 0) > _REFERENCE_LIMIT:
                raise serializers.ValidationError(
                    coded("STORE013", "That is not a valid upload token."), code="STORE013"
                )
            data.seek(0)
            return data.read().decode("utf-8", "replace").strip()
        return None

    def _from_token(self, token: str) -> str:
        from karni_storage.tokens import TokenError, read_confirmed

        field = self.model_field()
        request = self.context.get("request") if isinstance(self.context, dict) else None
        try:
            upload = read_confirmed(
                token,
                model=field.model._meta.label_lower,
                field=field.name,
                user=getattr(request, "user", None),
            )
        except TokenError as exc:
            raise serializers.ValidationError(str(exc), code=exc.code) from None
        return upload.name

    def _check(self, value: Any) -> Any:
        field = self.model_field()
        problem = limit_problem(
            field, int(value.size or 0), content_type_of(value.name or "", value.content_type)
        )
        if problem is not None:
            raise serializers.ValidationError(coded(*problem), code=problem[0])
        return value


class ProtectedFileSerializerField(_Protected, serializers.FileField):
    """Experimental. A protected file: its download path out, a file or an upload token in."""

    def to_internal_value(self, data: Any) -> Any:
        token = self._token(data)
        if token is not None:
            return self._from_token(token)
        return self._check(super().to_internal_value(data))


class ProtectedImageSerializerField(_Protected, serializers.ImageField):
    """Experimental. A protected image: as :class:`ProtectedFileSerializerField`, Pillow-checked."""

    def to_internal_value(self, data: Any) -> Any:
        token = self._token(data)
        if token is not None:
            return self._from_token(token)
        return self._check(super().to_internal_value(data))


def describe(model_field: Any) -> dict[str, Any]:
    """The ``x-karni-storage`` value for one protected model field."""
    from karni_storage import conf

    thumbnails = (
        sorted(dict(conf.get("KARNI_STORAGE_THUMBNAIL_SIZES") or {}))
        if getattr(model_field, "makes_thumbnails", False)
        else []
    )
    return {
        "protected": True,
        "max_size": int(model_field.size_limit),
        "content_types": list(model_field.allowed_content_types),
        "thumbnails": thumbnails,
    }


class ProtectedFileFieldExtension(OpenApiSerializerFieldExtension):
    """Adds ``x-karni-storage`` to protected file fields in the OpenAPI schema."""

    target_class = "karni_storage.serializers.ProtectedFileSerializerField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: Any) -> Any:
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        try:
            field = self.target.model_field()
        except (AttributeError, LookupError, FieldDoesNotExist):  # an unbound field
            return schema
        if isinstance(schema, dict):
            schema["x-karni-storage"] = describe(field)
        return schema


class ProtectedImageFieldExtension(ProtectedFileFieldExtension):
    """Adds ``x-karni-storage`` to protected image fields in the OpenAPI schema."""

    target_class = "karni_storage.serializers.ProtectedImageSerializerField"
