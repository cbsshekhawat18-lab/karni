"""Protected file fields: files only whoever may read the row can download.

::

    from karni_storage.fields import ProtectedFileField, ProtectedImageField

    class Contract(BaseModel):
        scan = ProtectedFileField(upload_to="contracts/", max_size=20 * 1024 * 1024,
                                  content_types=["application/pdf"])
        photo = ProtectedImageField(upload_to="contracts/photos/", blank=True)

A protected field is a ``FileField`` (or ``ImageField``) whose files live in
the protected storage (:mod:`karni_storage.storage`): a private bucket, or a
directory the media URL never serves. Its value's ``url`` is the row's
download path, ``<resource>/<id>/files/<field>/``, so the API gives that path
and never a public URL, and the download checks the row through its own
viewset first. Saving the row with a new image queues its thumbnails.

``max_size`` (bytes) and ``content_types`` limit what an upload may be, for a
file sent through the API and for a direct upload alike. An image field
takes JPEG, PNG, GIF and WebP by default.

Override / escape hatch: ``storage=`` gives one field another backend,
``thumbnails=False`` turns an image field's thumbnails off, and a plain
``FileField`` stays public as before.
"""

from __future__ import annotations

from typing import Any, Final

from django.db import models, transaction
from django.db.models import signals
from django.db.models.fields.files import FieldFile, ImageFieldFile

__all__ = [
    "IMAGE_CONTENT_TYPES",
    "ProtectedFieldFile",
    "ProtectedFieldMixin",
    "ProtectedFileField",
    "ProtectedImageField",
    "ProtectedImageFieldFile",
    "download_path",
    "protected_fields",
]

#: The content types an image field takes unless it lists its own (no SVG: it can carry script).
IMAGE_CONTENT_TYPES: Final[tuple[str, ...]] = ("image/jpeg", "image/png", "image/gif", "image/webp")


def download_path(instance: Any, field_name: str) -> str:
    """Experimental. ``<prefix>/<resource>/<id>/files/<field>/`` for one row's protected file.

    :raises karni.exceptions.KarniImproperlyConfigured: ``STORE020`` when the
        model has no viewset on the API or ``karni_storage.urls`` is not included.
    """
    from django.urls import NoReverseMatch, reverse
    from karni.exceptions import KarniImproperlyConfigured

    from karni_storage.access import route_for_model

    model = type(instance)
    resource = route_for_model(model)
    if resource is None:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.{field_name} is protected, but no viewset serves "
            f"{model.__name__} on the API, so its files have no download path. Declare a "
            "BaseViewSet for it.",
            code="STORE020",
        )
    try:
        return reverse(
            "karni_storage:download",
            kwargs={"resource": resource, "pk": str(instance.pk), "field": field_name},
        )
    except NoReverseMatch:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.{field_name} is protected, but karni_storage.urls is not "
            'included. Add path("api/", include("karni_storage.urls")) to config/urls.py.',
            code="STORE020",
        ) from None


class ProtectedFieldFile(FieldFile):
    """Experimental. A protected file's value: its ``url`` is the row's download path.

    Override / escape hatch: subclass it and set ``attr_class`` on a field
    subclass to give the file another ``url``.
    """

    @property
    def url(self) -> str:
        self._require_file()
        return download_path(self.instance, self.field.name)


class ProtectedImageFieldFile(ImageFieldFile, ProtectedFieldFile):
    """Experimental. A protected image's value: dimensions, and the download path as ``url``."""


class ProtectedFieldMixin:
    """Experimental. What both protected fields share: the storage, the limits, the deconstruction.

    ``isinstance(field, ProtectedFieldMixin)`` is how Karni tells a protected
    field. Override / escape hatch: a field of your own mixes it in first.
    """

    max_size: int | None
    content_types: tuple[str, ...] | None

    default_content_types: tuple[str, ...] = ()

    def _protect(
        self,
        kwargs: dict[str, Any],
        max_size: int | None,
        content_types: list[str] | tuple[str, ...] | None,
    ) -> None:
        from karni_storage.storage import ProtectedStorage

        if kwargs.get("storage") is None:
            kwargs["storage"] = ProtectedStorage()
        self.max_size = max_size
        self.content_types = tuple(content_types) if content_types is not None else None

    @property
    def allowed_content_types(self) -> tuple[str, ...]:
        """The content types the field takes; empty means any."""
        if self.content_types is not None:
            return self.content_types
        return self.default_content_types

    @property
    def size_limit(self) -> int:
        """The largest file the field takes, in bytes (``max_size``, else the setting)."""
        from karni_storage import conf

        return int(self.max_size or conf.get("KARNI_STORAGE_MAX_SIZE"))

    def _deconstruct(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        from karni_storage.storage import ProtectedStorage

        if isinstance(kwargs.get("storage"), ProtectedStorage):
            del kwargs["storage"]
        if self.max_size is not None:
            kwargs["max_size"] = self.max_size
        if self.content_types is not None:
            kwargs["content_types"] = list(self.content_types)
        return kwargs


class ProtectedFileField(ProtectedFieldMixin, models.FileField):
    """Experimental. A ``FileField`` whose files only the row's readers can download.

    Override / escape hatch: ``storage=`` for another backend, ``max_size``
    and ``content_types`` for the limits, ``attr_class`` for the file's ``url``.
    """

    attr_class = ProtectedFieldFile
    description = "A protected file"

    def __init__(
        self,
        *args: Any,
        max_size: int | None = None,
        content_types: list[str] | tuple[str, ...] | None = None,
        **kwargs: Any,
    ) -> None:
        self._protect(kwargs, max_size, content_types)
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        return name, path, args, self._deconstruct(kwargs)

    @property
    def makes_thumbnails(self) -> bool:
        return False


class ProtectedImageField(ProtectedFieldMixin, models.ImageField):
    """Experimental. An ``ImageField`` of protected images, with thumbnails.

    Saving a row with a new image queues :func:`karni_storage.tasks.make_thumbnails`
    after the transaction commits, in the sizes ``KARNI_STORAGE_THUMBNAIL_SIZES``
    names. The download path serves them with ``?size=<name>``.

    Override / escape hatch: ``thumbnails=False`` turns them off for the field.
    """

    attr_class = ProtectedImageFieldFile
    description = "A protected image"
    default_content_types = IMAGE_CONTENT_TYPES

    def __init__(
        self,
        *args: Any,
        max_size: int | None = None,
        content_types: list[str] | tuple[str, ...] | None = None,
        thumbnails: bool = True,
        **kwargs: Any,
    ) -> None:
        self._protect(kwargs, max_size, content_types)
        self.thumbnails = thumbnails
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        kwargs = self._deconstruct(kwargs)
        if not self.thumbnails:
            kwargs["thumbnails"] = False
        return name, path, args, kwargs

    @property
    def makes_thumbnails(self) -> bool:
        return self.thumbnails

    def contribute_to_class(self, cls: Any, name: str, **kwargs: Any) -> None:
        super().contribute_to_class(cls, name, **kwargs)
        if not cls._meta.abstract and self.thumbnails:
            signals.post_init.connect(self._remember_name, sender=cls)
            signals.post_save.connect(self._queue_thumbnails, sender=cls)

    def _stored_name(self, instance: Any) -> str:
        value = instance.__dict__.get(self.attname)
        return str(getattr(value, "name", value) or "")

    def _remember_name(self, instance: Any, **kwargs: Any) -> None:
        if self.attname in instance.__dict__:
            names = instance.__dict__.setdefault("_karni_storage_names", {})
            names[self.attname] = self._stored_name(instance)

    def _queue_thumbnails(self, instance: Any, **kwargs: Any) -> None:
        if kwargs.get("raw"):
            return
        names = instance.__dict__.setdefault("_karni_storage_names", {})
        name = self._stored_name(instance)
        if not name or names.get(self.attname) == name:
            return
        names[self.attname] = name

        def queue() -> None:
            from karni_storage.tasks import make_thumbnails

            make_thumbnails.delay(name)

        transaction.on_commit(queue, using=kwargs.get("using"))


def protected_fields(model: type[Any]) -> list[Any]:
    """Experimental. The protected file fields of ``model``, in declaration order."""
    return [field for field in model._meta.get_fields() if isinstance(field, ProtectedFieldMixin)]
