"""An image's width and height in pixels, read from its first bytes, without Pillow.

:func:`image_size` reads the header of a PNG, JPEG (with its EXIF
orientation, so a photo taken upright reports upright), GIF, WebP, AVIF or
SVG file. It answers the size a browser shows the image at when nothing
else sizes it. ``{% image %}``, the renditions task and ``karni check
--seo`` use it, so width and height are known even where Pillow is not
installed.

Override / escape hatch: none needed. A file it cannot read gives ``None``,
and every caller then leaves the size out rather than guess.
"""

from __future__ import annotations

import re
import struct
from typing import BinaryIO

__all__ = ["HEADER_BYTES", "image_size", "read_size"]

#: Bytes read from the start of a file. A JPEG's size can sit after large EXIF and ICC blocks.
HEADER_BYTES = 512 * 1024

_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_SVG_ROOT = re.compile(rb"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SVG_ATTR = re.compile(
    rb"""\b(width|height)\s*=\s*["']\s*([0-9.]+)\s*(px)?\s*["']""", re.IGNORECASE
)


def read_size(handle: BinaryIO) -> tuple[int, int] | None:
    """The size of the image in an open binary file, read from its start."""
    return image_size(handle.read(HEADER_BYTES))


def image_size(head: bytes) -> tuple[int, int] | None:
    """``(width, height)`` of the image whose first bytes are ``head``, or ``None``."""
    try:
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            width, height = struct.unpack(">II", head[16:24])
            return _valid(width, height)
        if head[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", head[6:10])
            return _valid(width, height)
        if head.startswith(b"\xff\xd8"):
            return _jpeg(head)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return _webp(head)
        if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis", b"mif1", b"msf1"):
            return _avif(head)
        if b"<svg" in head[:4096].lower():
            return _svg(head)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _valid(width: int, height: int) -> tuple[int, int] | None:
    return (int(width), int(height)) if width > 0 and height > 0 else None


def _jpeg(data: bytes) -> tuple[int, int] | None:
    position = 2
    size: tuple[int, int] | None = None
    rotated = False
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            position += 1 if marker == 0xFF else 2
            continue
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        segment = data[position + 4 : position + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            rotated = _exif_orientation(segment[6:]) in (5, 6, 7, 8)
        elif marker in _SOF and len(segment) >= 5:
            height, width = struct.unpack(">HH", segment[1:5])
            size = _valid(width, height)
            break
        elif marker == 0xDA:
            break
        position += 2 + length
    if size is None:
        return None
    return (size[1], size[0]) if rotated else size


def _exif_orientation(tiff: bytes) -> int:
    """The EXIF orientation tag (1 to 8) of a TIFF block, 1 when absent."""
    order = "<" if tiff[:2] == b"II" else ">"
    (offset,) = struct.unpack(order + "I", tiff[4:8])
    (count,) = struct.unpack(order + "H", tiff[offset : offset + 2])
    for index in range(count):
        entry = tiff[offset + 2 + 12 * index : offset + 14 + 12 * index]
        if len(entry) < 12:
            break
        tag, kind = struct.unpack(order + "HH", entry[:4])
        if tag == 0x0112:
            value = struct.unpack(
                order + ("H" if kind == 3 else "I"), entry[8 : 10 if kind == 3 else 12]
            )
            return int(value[0])
    return 1


def _webp(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return _valid(width & 0x3FFF, height & 0x3FFF)
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return _valid((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _valid(width, height)
    return None


def _avif(data: bytes) -> tuple[int, int] | None:
    found = data.find(b"ispe")
    if found < 0:
        return None
    width, height = struct.unpack(">II", data[found + 8 : found + 16])
    return _valid(width, height)


def _svg(data: bytes) -> tuple[int, int] | None:
    """An SVG's own width and height in pixels. Without both, ``None``: a page sizes it."""
    root = _SVG_ROOT.search(data)
    if root is None:
        return None
    values = {
        match.group(1).lower(): float(match.group(2)) for match in _SVG_ATTR.finditer(root.group(0))
    }
    if b"width" in values and b"height" in values:
        return _valid(round(values[b"width"]), round(values[b"height"]))
    return None
