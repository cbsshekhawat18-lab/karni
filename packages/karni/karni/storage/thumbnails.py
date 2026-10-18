"""Image thumbnailing helper for Karni.

:func:`make_thumbnail` renders an aspect-preserving thumbnail of an image
stored in (or destined for) a Django storage backend and saves it under
``thumbs/`` in that same backend -- so it works identically for local
filesystem media and S3-compatible media.

Pillow is an optional dependency: it is imported lazily, and calling
:func:`make_thumbnail` without it raises ``ImportError`` telling you to
``pip install karni[images]``.

Projects can swap the implementation wholesale by pointing the
``KARNI_THUMBNAILER`` setting at any callable with the same signature;
framework code obtains the active implementation via :func:`get_thumbnailer`.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from django.core.files.base import ContentFile, File

from karni.exceptions import KarniImportError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.core.files.storage import Storage

__all__ = ["DEFAULT_THUMBNAILER", "get_thumbnailer", "make_thumbnail"]

#: Dotted path of the default thumbnailer; the fallback used when a project
#: defines no ``KARNI_THUMBNAILER`` setting.
DEFAULT_THUMBNAILER = "karni.storage.thumbnails.make_thumbnail"

_INSTALL_HINT = (
    "karni.storage.thumbnails.make_thumbnail requires Pillow. "
    "Install it with: pip install karni[images]"
)

#: Pillow format spelling for common user-supplied aliases.
_FORMAT_ALIASES = {"JPG": "JPEG", "TIF": "TIFF"}

#: File extension per Pillow format where ``fmt.lower()`` is not it.
_FORMAT_EXTENSIONS = {"JPEG": "jpg", "TIFF": "tif"}


def _load_pillow() -> Any:
    """Pillow's ``Image`` module, or ``E501`` with the ``karni[images]`` install hint."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise KarniImportError(_INSTALL_HINT, code="E501") from exc
    return Image


def make_thumbnail(
    source: File | str,
    *,
    size: tuple[int, int] = (256, 256),
    fmt: str = "WEBP",
    storage: Storage | None = None,
) -> str:
    """Create an aspect-preserving thumbnail of ``source`` and save it.

    The image is downscaled in place-of-aspect to fit within ``size`` (it is
    never upscaled), re-encoded as ``fmt`` and saved to the storage backend
    under ``thumbs/{stem}_{w}x{h}.{ext}``, where ``stem`` is the source
    file's base name without extension and ``w``/``h`` are the *requested*
    bounding-box dimensions (stable, predictable names even though the
    rendered image may be smaller on one axis).

    Args:
        source: Either a name within ``storage`` (a ``str``, opened via
            ``storage.open``) or an already-open Django ``File`` object
            (its ``.name`` provides the stem; the caller keeps ownership of
            the file -- it is rewound before reading and never closed).
        size: Maximum ``(width, height)`` bounding box. Default ``(256, 256)``.
        fmt: Output image format understood by Pillow (``"WEBP"``,
            ``"JPEG"``/``"JPG"``, ``"PNG"``, ...). Default ``"WEBP"``.
            Sources with palette/alpha are converted to RGB automatically
            for formats without alpha support (JPEG).
        storage: The storage backend to read from and write to. ``None``
            (the default) uses the project's default storage, i.e.
            ``django.core.files.storage.storages["default"]``.

    Returns:
        The name the thumbnail was actually saved under -- exactly what
        ``storage.save`` returned, so a suffixed name is returned when the
        target name was already taken and the backend does not overwrite.

    Raises:
        ImportError: When Pillow is not installed
            (``pip install karni[images]``).

    Override / escape hatch:
        Point the ``KARNI_THUMBNAILER`` setting at your own callable with
        this signature to replace the implementation everywhere Karni
        resolves it through :func:`get_thumbnailer`; pass ``storage=`` to
        target a non-default backend for a single call.
    """
    image_module = _load_pillow()

    if storage is None:
        from karni.storage import get_storage

        storage = get_storage()

    if isinstance(source, str):
        source_name = source
        handle: Any = storage.open(source, "rb")
        should_close = True
    else:
        source_name = getattr(source, "name", None) or "thumbnail"
        # File.open() rewinds an open file and reopens a closed on-disk one.
        handle = source.open("rb") if hasattr(source, "open") else source
        should_close = False

    pil_format = _FORMAT_ALIASES.get(fmt.upper(), fmt.upper())
    extension = _FORMAT_EXTENSIONS.get(pil_format, pil_format.lower())
    width, height = size
    stem = PurePosixPath(str(source_name)).stem or "thumbnail"
    thumb_name = f"thumbs/{stem}_{width}x{height}.{extension}"

    # Read the payload up front so Pillow only ever owns an in-memory copy:
    # Image.close() would otherwise close a caller-provided file object.
    try:
        payload = handle.read()
    finally:
        if should_close:
            handle.close()

    buffer = BytesIO()
    image = image_module.open(BytesIO(payload))
    try:
        if image.mode in ("P", "PA"):
            image = image.convert("RGBA")
        if pil_format == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")
        image.thumbnail(size, image_module.Resampling.LANCZOS)
        image.save(buffer, format=pil_format)
    finally:
        image.close()

    return storage.save(thumb_name, ContentFile(buffer.getvalue()))


def get_thumbnailer() -> Callable[..., str]:
    """Resolve and return the active thumbnailer callable.

    Reads the dotted path from the ``KARNI_THUMBNAILER`` Django setting
    (``karni.conf`` defaults it to
    ``"karni.storage.thumbnails.make_thumbnail"``; the same fallback applies
    when the setting is absent entirely) and imports it with
    ``django.utils.module_loading.import_string``.

    Returns:
        A callable with :func:`make_thumbnail`'s signature:
        ``(source, *, size=..., fmt=..., storage=...) -> str``.

    Override / escape hatch:
        Set ``KARNI_THUMBNAILER = "myapp.images.my_thumbnailer"`` in the
        project's ``settings.py`` to swap the implementation globally.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    dotted_path: str = getattr(settings, "KARNI_THUMBNAILER", DEFAULT_THUMBNAILER)
    return import_string(dotted_path)
