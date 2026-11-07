"""Smaller WebP copies of uploaded images, stored next to the original, and markup that uses them.

When a save uploads an image (an ``ImageField``, or a file field with
karni_site's image validator), a Celery task (:mod:`karni_site.tasks`)
reads it through the field's own storage (local files or S3 alike) and:

* scales the original down to ``KARNI_SITE_IMAGE_MAX_SIZE`` when it is
  larger (the upload cap), turned upright from its EXIF orientation;
* writes a WebP copy at every width of ``KARNI_SITE_IMAGE_WIDTHS`` below
  its own, and one at its own width unless it is a WebP already, at
  ``KARNI_SITE_IMAGE_QUALITY``, named ``<name>.<width>w.webp`` next to the
  original;
* writes ``<name>.renditions.json``, the manifest: the image's width and
  height and the widths it has copies at.

At render time :func:`info` reads the manifest from the cache, else from
the storage. A missing manifest is never an error: the page shows the
original, and the copies are queued (once per ten minutes per image), so
an image uploaded before karni_site was installed, or loaded in bulk, gets
them too.

Without Pillow (``pip install karni-site[images]``) nothing is scaled or
copied: the original is shown as uploaded, and the manifest still records
its width and height (read by :mod:`karni_site.imagesize`), so pages keep
their ``width`` and ``height``.

Inside :func:`made_inline` the missing copies are made at once, in this
process, instead of queued: ``karni check --seo`` does that, so it judges
the copies a worker would make even where no worker runs (development).
The site itself always queues them.

Override / escape hatch: ``KARNI_SITE_IMAGE_WIDTHS``, ``KARNI_SITE_IMAGE_QUALITY``,
``KARNI_SITE_IMAGE_MAX_SIZE``, ``KARNI_SITE_QUEUE_RENDITIONS`` and
``KARNI_SITE_RENDITIONER`` (a ``(name, storage) -> Manifest`` function that
makes the copies another way).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from io import BytesIO
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.db import models, transaction
from django.db.models.fields.files import FieldFile
from django.utils.module_loading import import_string

from karni_site import caching, conf, imagesize

__all__ = [
    "MARKER",
    "NATURAL",
    "STYLE",
    "Manifest",
    "Source",
    "attributes",
    "connect",
    "default_sizes",
    "forget",
    "generate",
    "info",
    "is_derived",
    "make",
    "made_inline",
    "manifest_name",
    "queue",
    "read_manifest",
    "rendition_name",
    "replacement",
    "source_of",
    "storage_for",
]

logger = logging.getLogger("karni_site")

#: The attribute that marks an ``<img>`` sized by Karni. ``{% karni_seo %}`` gives such an
#: image ``height: auto``, and one marked ``natural`` (its width and height are its file's
#: own, not the designer's) ``width: auto`` too, so CSS that sets one side keeps it in shape.
MARKER = "data-karni-image"
NATURAL = "natural"
#: The rule that does it, in every page's head (``KARNI_SITE_IMAGE_STYLE``).
STYLE = f":where(img[{MARKER}]){{height:auto}}:where(img[{MARKER}={NATURAL}]){{width:auto}}"
_DERIVED = re.compile(r"\.\d+w\.webp$|\.renditions\.json$")
#: The cache answer for "no manifest yet": looked up again after this many seconds.
_RETRY = 60
#: An image is queued at most once per this many seconds.
_QUEUE_LOCK = 600
_ENCODINGS: dict[str, dict[str, Any]] = {
    "JPEG": {"quality": 90, "optimize": True},
    "PNG": {"optimize": True},
    "WEBP": {"quality": 90},
}
_pillow_missing_logged = False
#: The names whose copies were made at once, inside :func:`made_inline`; ``None`` outside.
_INLINE: ContextVar[list[str] | None] = ContextVar("karni_site_inline_copies", default=None)


@contextmanager
def made_inline() -> Iterator[list[str]]:
    """Make missing copies at once instead of queueing them, and list the names made.

    For a run that judges the copies (``karni check --seo``) where no Celery
    worker may be running. Outside it, copies are queued as always.
    """
    made: list[str] = []
    token = _INLINE.set(made)
    try:
        yield made
    finally:
        _INLINE.reset(token)


@dataclass(frozen=True)
class Manifest:
    """An image's width and height, and the widths it has WebP copies at."""

    width: int
    height: int
    widths: tuple[int, ...] = ()
    #: The original's size in bytes when the copies were made (a replaced file differs).
    size: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "width": self.width,
            "height": self.height,
            "widths": list(self.widths),
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Manifest | None:
        try:
            return cls(
                int(data["width"]),
                int(data["height"]),
                tuple(sorted(int(w) for w in data.get("widths") or ())),
                int(data.get("size") or 0),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Source:
    """A stored image: its name, its storage, how a task finds that storage, its address."""

    name: str
    storage: Storage = field(compare=False)
    #: ``"app_label.Model.field"`` (the field's storage), or ``""`` for the default storage.
    ref: str = ""
    url: str = ""


def rendition_name(name: str, width: int) -> str:
    """``"<name>.<width>w.webp"``: the copy of ``name`` at ``width`` pixels, next to it."""
    return f"{name}.{width}w.webp"


def manifest_name(name: str) -> str:
    return f"{name}.renditions.json"


def is_derived(name: str) -> bool:
    """Whether ``name`` is a copy or a manifest this module wrote."""
    return bool(_DERIVED.search(name))


# finding the storage


def storage_for(ref: str) -> Storage:
    """The storage of the field ``ref`` names (``"app_label.Model.field"``), else the default."""
    from django.apps import apps
    from django.core.files.storage import default_storage

    if ref.count(".") == 2:
        app_label, model_name, field_name = ref.split(".")
        try:
            found = apps.get_model(app_label, model_name)._meta.get_field(field_name)
        except (LookupError, ValueError, FieldDoesNotExist):
            return default_storage
        storage = getattr(found, "storage", None)
        if isinstance(storage, Storage):
            return storage
    return default_storage


def source_of(value: Any) -> Source | None:
    """The :class:`Source` of a file field's value, or of a name in the default storage."""
    if isinstance(value, Source):
        return value
    if isinstance(value, FieldFile):
        if not value.name:
            return None
        bound = value.field
        ref = f"{bound.model._meta.label}.{bound.name}"
        return Source(str(value.name), value.storage, ref, _url(value.storage, str(value.name)))
    if isinstance(value, str) and value.strip():
        from django.core.files.storage import default_storage

        name = value.strip()
        return Source(name, default_storage, "", _url(default_storage, name))
    return None


def _url(storage: Storage, name: str) -> str:
    try:
        return str(storage.url(name))
    except Exception:  # noqa: BLE001 - a storage that cannot name an address shows nothing
        logger.exception("karni_site: no address for the image %s", name)
        return ""


# the manifest at render time


def _cache_key(name: str) -> str:
    return caching.key("image", hashlib.sha256(name.encode("utf-8")).hexdigest()[:40])


def read_manifest(name: str, storage: Storage) -> Manifest | None:
    """The manifest stored next to ``name``, or ``None``."""
    try:
        with storage.open(manifest_name(name), "rb") as handle:
            return Manifest.from_dict(json.loads(handle.read()))
    except Exception:  # noqa: BLE001 - missing, unreadable or another storage's error
        return None


def remember(name: str, manifest: Manifest) -> None:
    caching.cache().set(_cache_key(name), manifest.as_dict(), caching.timeout())


def forget(name: str) -> None:
    """Drop what the cache knows of ``name`` (its file was replaced)."""
    caching.cache().delete(_cache_key(name))


def _local_size(source: Source) -> Manifest | None:
    """For a file on this machine, its size read now: a page has width and height at once."""
    if not isinstance(source.storage, FileSystemStorage):
        return None
    try:
        with source.storage.open(source.name, "rb") as handle:
            size = imagesize.read_size(handle)
    except OSError:
        return None
    return Manifest(*size) if size else None


def info(value: Any) -> Manifest | None:
    """The manifest of an image (a file field's value or a :class:`Source`), or ``None``.

    Never raises. A missing manifest queues the copies and is looked up
    again a minute later. Until then, a file on this machine reports its
    width and height without copies.
    """
    source = source_of(value)
    if source is None:
        return None
    store = caching.cache()
    key = _cache_key(source.name)
    try:
        found = store.get(key)
    except Exception:  # noqa: BLE001 - a cache that is down shows the original
        logger.exception("karni_site: the image cache could not be read")
        return None
    if found is not None:
        return Manifest.from_dict(found) if found else None
    manifest = read_manifest(source.name, source.storage)
    if manifest is not None:
        store.set(key, manifest.as_dict(), caching.timeout())
        return manifest
    queue(source)
    try:
        made = store.get(key)  # made already: an eager Celery, or made_inline()
    except Exception:  # noqa: BLE001 - a cache that is down shows the original
        made = None
    if made:
        return Manifest.from_dict(made)
    interim = _local_size(source)
    store.set(key, interim.as_dict() if interim else {}, _RETRY)
    return interim


def queue(value: Any, *, force: bool = False) -> None:
    """Queue the copies of an image (Celery), at most once per ten minutes. Never raises."""
    source = source_of(value)
    if source is None or is_derived(source.name):
        return
    if not conf.get("KARNI_SITE_QUEUE_RENDITIONS"):
        return
    inline = _INLINE.get()
    if inline is not None:
        try:
            if make(source.name, source.ref, force=force) is not None:
                inline.append(source.name)
        except Exception:  # noqa: BLE001 - an unreadable image is judged as it is
            logger.warning("karni_site: the copies of %s could not be made", source.name)
        return
    store = caching.cache()
    lock = caching.key("image-queued", hashlib.sha256(source.name.encode()).hexdigest()[:40])
    try:
        if not force and not store.add(lock, 1, _QUEUE_LOCK):
            return
        if force:
            store.set(lock, 1, _QUEUE_LOCK)
    except Exception:  # noqa: BLE001 - no cache, no queueing: the original is shown
        return

    def send() -> None:
        try:
            from karni_site.tasks import make_renditions

            make_renditions.apply_async((source.name, source.ref, force), retry=False)
        except Exception:  # noqa: BLE001 - a broker that is down never fails the page
            logger.warning(
                "karni_site: the copies of %s could not be queued (is the Celery broker "
                "running?). The original is shown until they are made.",
                source.name,
                exc_info=True,
            )

    transaction.on_commit(send)


# making the copies


def _pillow() -> Any:
    """``(PIL.Image, PIL.ImageOps)``, or ``None`` without Pillow (logged once)."""
    global _pillow_missing_logged
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if not _pillow_missing_logged:
            _pillow_missing_logged = True
            logger.warning(
                "karni_site: Pillow is not installed, so uploaded images are shown as uploaded: "
                "no smaller WebP copies, no upload cap. Install it with "
                "`pip install karni-site[images]`."
            )
        return None
    return Image, ImageOps


def _write(storage: Storage, name: str, content: bytes) -> None:
    """Store ``content`` under exactly ``name``, replacing what is there."""
    try:
        if storage.exists(name):
            storage.delete(name)
    except NotImplementedError:
        pass
    saved = storage.save(name, ContentFile(content))
    if saved != name:
        logger.warning("karni_site: the storage saved %s as %s", name, saved)


def _encode(image: Any, fmt: str, **options: Any) -> bytes:
    buffer = BytesIO()
    if fmt == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    if fmt == "WEBP" and image.mode not in ("RGB", "RGBA"):
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def _widths() -> list[int]:
    return sorted({int(w) for w in conf.get("KARNI_SITE_IMAGE_WIDTHS") or () if int(w) > 0})


def generate(name: str, storage: Storage) -> Manifest | None:
    """Make the copies of the stored image ``name`` and its manifest (``KARNI_SITE_RENDITIONER``).

    Returns the manifest, or ``None`` for a file that is not an image.
    """
    with storage.open(name, "rb") as handle:
        data = handle.read()
    size = imagesize.image_size(data[: imagesize.HEADER_BYTES])
    pillow = _pillow()
    manifest: Manifest | None = Manifest(*size, (), len(data)) if size else None
    if pillow is not None:
        manifest = _with_pillow(name, storage, data, pillow) or manifest
    if manifest is not None:
        _write(storage, manifest_name(name), json.dumps(manifest.as_dict()).encode())
    return manifest


def _with_pillow(name: str, storage: Storage, data: bytes, pillow: Any) -> Manifest | None:
    image_module, image_ops = pillow
    try:
        image = image_module.open(BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001 - not an image Pillow reads (or a decompression bomb)
        return None
    with image:
        fmt = str(image.format or "")
        fmt = "JPEG" if fmt == "MPO" else fmt  # a camera's JPEG with a second, preview frame
        animated = fmt != "JPEG" and getattr(image, "n_frames", 1) > 1
        if animated or fmt not in _ENCODINGS:
            upright = image_ops.exif_transpose(image) or image
            return Manifest(upright.width, upright.height, (), len(data))
        icc = image.info.get("icc_profile")
        upright = image_ops.exif_transpose(image) or image
        cap = conf.get("KARNI_SITE_IMAGE_MAX_SIZE")
        if cap and max(upright.size) > int(cap):
            upright.thumbnail((int(cap), int(cap)), image_module.Resampling.LANCZOS)
            options = dict(_ENCODINGS[fmt])
            if icc:
                options["icc_profile"] = icc
            data = _encode(upright, fmt, **options)
            _write(storage, name, data)
        quality = int(conf.get("KARNI_SITE_IMAGE_QUALITY"))
        made: list[int] = []
        wanted = [w for w in _widths() if w < upright.width]
        if wanted and fmt != "WEBP":
            wanted.append(upright.width)  # the full picture in WebP, for the widest screens
        for width in wanted:
            height = max(1, round(upright.height * width / upright.width))
            copy = upright.resize((width, height), image_module.Resampling.LANCZOS)
            options = {"quality": quality}
            if icc:
                options["icc_profile"] = icc
            _write(storage, rendition_name(name, width), _encode(copy, "WEBP", **options))
            made.append(width)
        return Manifest(upright.width, upright.height, tuple(made), len(data))


def make(name: str, ref: str = "", *, force: bool = False) -> Manifest | None:
    """What the task runs: the copies of ``name`` unless current ones exist. Remembers them."""
    storage = storage_for(ref)
    if is_derived(name) or not storage.exists(name):
        return None
    if not force:
        current = read_manifest(name, storage)
        if current is not None and (not current.size or current.size == storage.size(name)):
            remember(name, current)
            return current
    renditioner = import_string(str(conf.get("KARNI_SITE_RENDITIONER")))
    manifest = renditioner(name, storage)
    if manifest is not None:
        remember(name, manifest)
    else:
        forget(name)
    return manifest


# markup


def default_sizes(width: int | None, *, lazy: bool) -> str:
    """``sizes`` for an image shown ``width`` pixels wide at most (``auto`` when it loads lazily).

    A lazy image lets the browser use the width the layout gives it
    (``auto``, Chrome 126 and later), so a picture in a card loads at the
    card's size. The rest of the list is for the browsers that do not.
    """
    base = f"(max-width: {width}px) 100vw, {width}px" if width else "100vw"
    return f"auto, {base}" if lazy else base


def candidates(source: Source, manifest: Manifest | None) -> list[tuple[str, int]]:
    """``(address, width)`` of every copy and of the original, smallest first."""
    if manifest is None or not manifest.widths:
        return []
    found = [(_url(source.storage, rendition_name(source.name, w)), w) for w in manifest.widths]
    if manifest.width not in manifest.widths:
        found.append((source.url, manifest.width))
    return found


def attributes(
    value: Any,
    *,
    width: int | None = None,
    height: int | None = None,
    sizes: str | None = None,
    lazy: bool = True,
) -> dict[str, str]:
    """``src``, ``srcset``, ``sizes``, ``width`` and ``height`` for an ``<img>`` of an image.

    ``width`` is the width the page shows it at (the image's own without
    one), ``height`` follows its proportions unless given. Without copies
    there is no ``srcset``: ``src`` is the original. Never raises.
    """
    source = source_of(value)
    if source is None:
        return {}
    manifest = info(source)
    shown_width = width or (manifest.width if manifest else None)
    shown_height = height
    if shown_height is None and shown_width and manifest:
        shown_height = max(1, round(shown_width * manifest.height / manifest.width))
    found: dict[str, str] = {"src": source.url}
    options = candidates(source, manifest)
    if options:
        wanted = shown_width or options[-1][1]
        found["src"] = next((url for url, w in options if w >= wanted), options[-1][0])
        found["srcset"] = ", ".join(f"{url} {w}w" for url, w in options)
        found["sizes"] = sizes or default_sizes(shown_width, lazy=lazy)
    elif sizes:
        found["sizes"] = sizes
    if shown_width:
        found["width"] = str(shown_width)
    if shown_height:
        found["height"] = str(shown_height)
    return found


def replacement(value: Any, design: Mapping[str, str]) -> dict[str, str | None]:
    """The attributes an uploaded image changes in the design's ``<img>`` (``None`` removes one).

    ``design`` is the design's attributes. A width the designer wrote stays
    and the height follows the upload's proportions. A width the import
    took from the design's own file (``data-karni-image="natural"``), or
    none, becomes the upload's. The design's ``sizes`` stays.
    """
    source = source_of(value)
    if source is None:
        return {}
    manifest = info(source)
    designed = _number(design.get("width"))
    natural = design.get(MARKER) == NATURAL or designed is None
    changes: dict[str, str | None] = {"srcset": None, "sizes": None}
    if manifest is None:
        changes["height"] = None
        if natural:
            changes["width"] = None
        return changes
    if natural or designed is None:
        width, height = manifest.width, manifest.height
        changes[MARKER] = NATURAL
    else:
        width = designed
        height = max(1, round(width * manifest.height / manifest.width))
    changes["width"], changes["height"] = str(width), str(height)
    options = candidates(source, manifest)
    if options:
        # A width the browser works out (natural) cannot also come from the layout (auto).
        lazy = not natural and (design.get("loading") or "").lower() == "lazy"
        changes["srcset"] = ", ".join(f"{url} {w}w" for url, w in options)
        changes["sizes"] = design.get("sizes") or default_sizes(width, lazy=lazy)
    return changes


def _number(value: str | None) -> int | None:
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


# uploads


_IMAGE_FIELDS: dict[type[models.Model], tuple[str, ...]] = {}


def _image_fields(model: type[models.Model]) -> tuple[str, ...]:
    """The file fields of ``model`` that hold images (cached per model)."""
    found = _IMAGE_FIELDS.get(model)
    if found is None:
        from karni_site.images import ImageValidator

        found = tuple(
            f.attname
            for f in model._meta.concrete_fields
            if isinstance(f, models.ImageField)
            or (
                isinstance(f, models.FileField)
                and any(isinstance(v, ImageValidator) for v in f.validators)
            )
        )
        _IMAGE_FIELDS[model] = found
    return found


def _before_save(sender: type[models.Model], instance: Any, raw: bool = False, **_: Any) -> None:
    if raw:
        return
    uploads = [
        name
        for name in _image_fields(sender)
        if isinstance(file := getattr(instance, name, None), FieldFile)
        and file.name
        and not getattr(file, "_committed", True)
    ]
    if uploads:
        instance.__dict__["_karni_site_uploads"] = uploads


def _after_save(sender: type[models.Model], instance: Any, raw: bool = False, **_: Any) -> None:
    uploads = instance.__dict__.pop("_karni_site_uploads", None)
    if raw or not uploads:
        return
    for name in uploads:
        source = source_of(getattr(instance, name, None))
        if source is None or is_derived(source.name):
            continue
        forget(source.name)
        transaction.on_commit(partial(queue, source, force=True))


def connect() -> None:
    """Queue the copies of every image a save uploads (``karni_site.apps``)."""
    from django.db.models.signals import post_save, pre_save

    pre_save.connect(_before_save, dispatch_uid="karni_site:renditions:before")
    post_save.connect(_after_save, dispatch_uid="karni_site:renditions:after")
