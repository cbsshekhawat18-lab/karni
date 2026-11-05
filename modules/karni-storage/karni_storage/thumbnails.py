"""Thumbnails of protected images, made with core's thumbnailer.

:func:`make` renders every size ``KARNI_STORAGE_THUMBNAIL_SIZES`` names
(``{"small": [160, 160], ...}``, bounding boxes, never upscaled) with
:func:`karni.storage.thumbnails.get_thumbnailer` (core's ``make_thumbnail``
unless ``KARNI_THUMBNAILER`` names another) into the protected storage, in
``KARNI_STORAGE_THUMBNAIL_FORMAT``, and records each in
:class:`karni_storage.models.Thumbnail`. It skips a size already made, so it
is safe to run again. The confirm step and saving a row with a new image
queue it as a Celery task (:mod:`karni_storage.tasks`), and ``manage.py
karni_thumbnails`` makes whatever is missing.

Override / escape hatch: ``KARNI_THUMBNAILER`` replaces the rendering,
``KARNI_STORAGE_THUMBNAIL_SIZES`` the sizes, ``thumbnails=False`` on a field
turns them off.
"""

from __future__ import annotations

from typing import Any

from karni.exceptions import KarniValueError

from karni_storage import conf

__all__ = ["find", "make", "size_problems", "sizes"]


def _parse(raw: Any) -> dict[str, tuple[int, int]]:
    if not isinstance(raw, dict):
        raise KarniValueError(
            "KARNI_STORAGE_THUMBNAIL_SIZES must map a name to [width, height].", code="STORE005"
        )
    out: dict[str, tuple[int, int]] = {}
    for name, box in raw.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(box, list | tuple)
            or len(box) != 2
            or not all(isinstance(side, int) and not isinstance(side, bool) for side in box)
            or min(box) <= 0
        ):
            raise KarniValueError(
                f"KARNI_STORAGE_THUMBNAIL_SIZES[{name!r}] is {box!r}: give [width, height] in "
                'pixels, e.g. {"small": [160, 160]}.',
                code="STORE005",
            )
        out[name] = (int(box[0]), int(box[1]))
    return out


def sizes() -> dict[str, tuple[int, int]]:
    """Experimental. The thumbnail sizes, by name: ``KARNI_STORAGE_THUMBNAIL_SIZES``, checked."""
    return _parse(conf.get("KARNI_STORAGE_THUMBNAIL_SIZES"))


def size_problems() -> list[str]:
    """What is wrong with ``KARNI_STORAGE_THUMBNAIL_SIZES``, as ``STORE005`` messages."""
    try:
        sizes()
    except KarniValueError as exc:
        return [f"{exc.code}: {exc.message}"]
    return []


def find(source: str, size: str) -> str | None:
    """Experimental. The stored name of ``source``'s thumbnail of ``size``, or ``None``."""
    from karni_storage.models import Thumbnail

    return Thumbnail.objects.filter(source=source, size=size).values_list("name", flat=True).first()


def make(source: str) -> dict[str, str]:
    """Experimental. Make the missing thumbnails of the protected image ``source``.

    Returns ``{size name: stored name}`` for the ones made by this call.

    :raises karni.exceptions.KarniImportError: ``E501`` without Pillow (``karni[images]``).
    """
    from django.db import IntegrityError, transaction
    from karni.storage.thumbnails import get_thumbnailer

    from karni_storage.models import Thumbnail
    from karni_storage.storage import protected_storage

    wanted = sizes()
    rows = Thumbnail.objects.without(
        "soft_delete", reason="a deleted thumbnail is made again, under the same unique key"
    ).filter(source=source)
    rows.filter(deleted_at__isnull=False).hard_delete()
    done = set(rows.filter(deleted_at__isnull=True).values_list("size", flat=True))
    missing = {name: box for name, box in wanted.items() if name not in done}
    if not missing:
        return {}
    storage = protected_storage()
    thumbnailer = get_thumbnailer()
    fmt = str(conf.get("KARNI_STORAGE_THUMBNAIL_FORMAT") or "WEBP")
    made: dict[str, str] = {}
    for name, box in missing.items():
        stored = thumbnailer(source, size=box, fmt=fmt, storage=storage)
        try:
            with transaction.atomic():
                Thumbnail.objects.create(source=source, size=name, name=stored)
        except IntegrityError:  # another worker made it meanwhile: keep theirs
            storage.delete(stored)
            continue
        made[name] = stored
    return made
