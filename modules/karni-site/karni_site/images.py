"""Images a client uploads, and the design's own image markup with a new picture in it.

:func:`validate_image` accepts a file whose extension ``KARNI_SITE_IMAGE_TYPES``
lists and whose first bytes are that kind of image, so a renamed file is
refused. It needs no Pillow. SVG is not in the default list: an SVG file can
carry script, which runs when someone opens the file's own address.

:func:`replace_image` is how ``{% editable_image %}`` and ``{% site_image %}``
show an uploaded picture without changing the design's markup: the first
``<img>`` keeps its classes, loading hints and every other attribute, and
only ``src`` (and ``alt``) change. ``srcset``, ``sizes`` and ``<source>``
elements point at the design's own files, so they go when the picture is
replaced.

Override / escape hatch: ``KARNI_SITE_IMAGE_TYPES``. Add ``"svg"`` only when
everyone who uploads is trusted with script on the site's origin.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape, unescape
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

from karni_site import conf

__all__ = [
    "ImageValidator",
    "image_kind",
    "img_attributes",
    "replace_image",
    "set_attributes",
    "validate_image",
]

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SOURCE = re.compile(r"[ \t]*<source\b[^>]*>[ \t]*\n?", re.I)
_ATTR = re.compile(
    r"""(?P<space>\s+)(?P<name>[^\s"'=<>/`]+)(?:\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>[^\s"'=<>`]+)))?""",
)
_EXTENSION_KIND = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "avif": "avif",
    "ico": "ico",
    "svg": "svg",
}


def image_kind(head: bytes) -> str | None:
    """What kind of image the first bytes of a file are, or ``None``."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if head[:4] == b"\x00\x00\x01\x00":
        return "ico"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith((b"<svg", b"<?xml")) and b"<svg" in head.lower():
        return "svg"
    return None


@deconstructible
class ImageValidator:
    """Refuses a file that is not one of ``KARNI_SITE_IMAGE_TYPES``, by name and by content."""

    def __call__(self, value: Any) -> None:
        name = str(getattr(value, "name", "") or "")
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        allowed = [str(kind).lower() for kind in conf.get("KARNI_SITE_IMAGE_TYPES") or ()]
        if extension not in allowed or extension not in _EXTENSION_KIND:
            raise ValidationError(
                "Upload an image of one of these types: %(types)s.",
                code="invalid_extension",
                params={"types": ", ".join(allowed)},
            )
        handle = getattr(value, "file", value)
        try:
            position = handle.tell()
            handle.seek(0)
            head = handle.read(512)
            handle.seek(position)
        except (AttributeError, OSError, ValueError):
            return  # a stored file that cannot be read here was checked when it was uploaded
        if isinstance(head, str):
            head = head.encode("utf-8", "replace")
        if image_kind(head) != _EXTENSION_KIND[extension]:
            raise ValidationError(
                "This file is not a %(kind)s image, whatever its name says.",
                code="invalid_image",
                params={"kind": extension.upper()},
            )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ImageValidator)

    def __hash__(self) -> int:
        return hash(type(self))


validate_image = ImageValidator()


def img_attributes(markup: str) -> dict[str, str]:
    """The attributes of the first ``<img>`` in ``markup``, values decoded."""
    match = _IMG.search(markup)
    if match is None:
        return {}
    found: dict[str, str] = {}
    for attr in _ATTR.finditer(match.group(0)[4:]):
        value = next((attr.group(g) for g in ("dq", "sq", "uq") if attr.group(g) is not None), "")
        found.setdefault(attr.group("name").lower(), unescape(value))
    return found


def _rewrite_tag(tag: str, src: str | None, alt: str | None) -> str:
    """One ``<img>`` start tag with a new ``src`` (and ``alt``), the rest as written."""
    head = tag[:4]
    body = tag[4:]
    end = "/>" if body.rstrip().endswith("/>") else ">"
    body = body.rstrip()[: -len(end)]
    pieces: list[str] = []
    seen: set[str] = set()
    for attr in _ATTR.finditer(body):
        name = attr.group("name").lower()
        seen.add(name)
        if src is not None and name in ("srcset", "sizes", "data-srcset"):
            continue
        if src is not None and name in ("src", "data-src"):
            pieces.append(f'{attr.group("space")}{attr.group("name")}="{escape(src)}"')
            continue
        if alt is not None and name == "alt":
            pieces.append(f'{attr.group("space")}{attr.group("name")}="{escape(alt)}"')
            continue
        pieces.append(attr.group(0))
    if src is not None and "src" not in seen:
        pieces.append(f' src="{escape(src)}"')
    if alt is not None and "alt" not in seen:
        pieces.append(f' alt="{escape(alt)}"')
    return head + "".join(pieces) + (" />" if end == "/>" else ">")


def set_attributes(tag: str, changes: Mapping[str, str | None]) -> str:
    """One start tag with attributes set (a value) or removed (``None``), the rest as written."""
    head = tag[: 1 + len(tag[1:].split(None, 1)[0].rstrip("/>"))]
    body = tag[len(head) :]
    end = "/>" if body.rstrip().endswith("/>") else ">"
    body = body.rstrip()[: -len(end)]
    pieces: list[str] = []
    done: set[str] = set()
    for attr in _ATTR.finditer(body):
        name = attr.group("name").lower()
        if name in changes:
            if name in done:
                continue
            done.add(name)
            value = changes[name]
            if value is not None:
                written = f'="{escape(value)}"' if value else ""
                pieces.append(f"{attr.group('space')}{attr.group('name')}{written}")
            continue
        pieces.append(attr.group(0))
    for name, value in changes.items():
        if name not in done and value is not None:
            pieces.append(f' {name}="{escape(value)}"' if value else f" {name}")
    return head + "".join(pieces) + (" />" if end == "/>" else ">")


def replace_image(
    markup: str,
    src: str | None,
    alt: str | None = None,
    attributes: Mapping[str, str | None] | None = None,
) -> str:
    """The design's image markup showing ``src`` (and ``alt``), every other byte kept.

    ``None`` keeps the design's value. When ``markup`` has no ``<img>`` (a
    ``url`` block holds a bare address), the address itself is replaced.
    ``attributes`` sets (or, as ``None``, removes) more of the ``<img>``'s
    attributes: the uploaded picture's ``srcset``, ``sizes``, ``width`` and
    ``height`` (:func:`karni_site.renditions.replacement`).
    """
    match = _IMG.search(markup)
    if match is None:
        return escape(src) if src is not None else markup
    tag = _rewrite_tag(match.group(0), src, alt)
    if attributes:
        tag = set_attributes(tag, attributes)
    out = markup[: match.start()] + tag + markup[match.end() :]
    if src is not None:
        out = _SOURCE.sub("", out)
    return out
