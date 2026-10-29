"""A design's own images, sized: ``width`` and ``height``, and smaller WebP copies in a ``srcset``.

``karni import design`` calls :class:`Sizer` for every ``<img>`` whose
``src`` is a file of the design:

* without both ``width`` and ``height``, the missing ones are written from
  the file's own pixel size (read from its first bytes, no Pillow needed),
  with ``data-karni-image``. ``{% karni_seo %}`` gives such an image
  ``height: auto`` (and, when both sizes came from the file, ``width: auto``,
  ``data-karni-image="natural"``), so CSS that sets only one side still
  keeps it in shape, as before;
* a JPEG, PNG or WebP wider than the narrowest copy, without a ``srcset``
  of its own and outside a ``<picture>``, gets WebP copies at
  :data:`WIDTHS` below its width and at its own width (unless it is a WebP),
  named ``<name>.<width>w.webp`` next to it under ``static/<app>/``, and a
  ``srcset`` and ``sizes``. A lazily loaded image
  gets ``sizes="auto, ..."``, so the browser loads the copy that fits the
  layout: a picture in a card at the card's size. The copies need Pillow
  where karni runs (``pip install pillow``). Without it only the sizes are
  written, and the report says how many images could have copies.

The copies use the same names and widths as karni-site's copies of
uploaded images (``KARNI_SITE_IMAGE_WIDTHS``' default), so a client's
upload replaces them in the same markup.

Override / escape hatch: an ``<img>`` with its own ``srcset``, ``width``
and ``height`` is left as it is. Remove the copies' ``srcset`` from a
template to stop using them.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Final

from karni_cli.design.parse import Node

__all__ = [
    "MARKER",
    "NATURAL",
    "QUALITY",
    "WIDTHS",
    "Sizer",
    "copy_targets",
    "image_size",
    "make_copy",
    "pillow_available",
    "rendition_name",
]

#: The widths of the copies, in pixels (karni-site's KARNI_SITE_IMAGE_WIDTHS default).
WIDTHS: Final = (320, 480, 640, 800, 960, 1280, 1600, 1920)
#: The WebP quality of the copies (KARNI_SITE_IMAGE_QUALITY's default).
QUALITY: Final = 80
#: The attribute karni-site's {% karni_seo %} CSS keeps in proportion.
MARKER: Final = "data-karni-image"
NATURAL: Final = "natural"
_COPYABLE: Final = (".jpg", ".jpeg", ".png", ".webp")
_SIZED: Final = (*_COPYABLE, ".gif", ".svg", ".avif")
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_SVG_ROOT = re.compile(rb"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SVG_ATTR = re.compile(
    rb"""\b(width|height)\s*=\s*["']\s*([0-9.]+)\s*(px)?\s*["']""", re.IGNORECASE
)


def rendition_name(path: str, width: int) -> str:
    return f"{path}.{width}w.webp"


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


# reading sizes (the same reader as karni_site.imagesize: the CLI does not import karni-site)


def image_size(head: bytes) -> tuple[int, int] | None:
    """``(width, height)`` of the image whose first bytes are ``head``, or ``None``."""
    try:
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            return _valid(*struct.unpack(">II", head[16:24]))
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return _valid(*struct.unpack("<HH", head[6:10]))
        if head.startswith(b"\xff\xd8"):
            return _jpeg(head)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return _webp(head)
        if head[4:8] == b"ftyp":
            found = head.find(b"ispe")
            return (
                _valid(*struct.unpack(">II", head[found + 8 : found + 16])) if found > 0 else None
            )
        if b"<svg" in head[:4096].lower():
            return _svg(head)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _valid(width: int, height: int) -> tuple[int, int] | None:
    return (int(width), int(height)) if width > 0 and height > 0 else None


def _jpeg(data: bytes) -> tuple[int, int] | None:
    position, rotated = 2, False
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
            position += 1 if marker == 0xFF else 2
            continue
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        segment = data[position + 4 : position + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            rotated = _orientation(segment[6:]) in (5, 6, 7, 8)
        elif marker in _SOF and len(segment) >= 5:
            height, width = struct.unpack(">HH", segment[1:5])
            size = _valid(width, height)
            return (size[1], size[0]) if size and rotated else size
        elif marker == 0xDA:
            return None
        position += 2 + length
    return None


def _orientation(tiff: bytes) -> int:
    order = "<" if tiff[:2] == b"II" else ">"
    (offset,) = struct.unpack(order + "I", tiff[4:8])
    (count,) = struct.unpack(order + "H", tiff[offset : offset + 2])
    for index in range(count):
        entry = tiff[offset + 2 + 12 * index : offset + 14 + 12 * index]
        if len(entry) < 12:
            break
        tag, kind = struct.unpack(order + "HH", entry[:4])
        if tag == 0x0112:
            short = kind == 3
            (value,) = struct.unpack(
                order + ("H" if short else "I"), entry[8 : 10 if short else 12]
            )
            return int(value)
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
        return _valid(
            int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
        )
    return None


def _svg(data: bytes) -> tuple[int, int] | None:
    root = _SVG_ROOT.search(data)
    if root is None:
        return None
    values = {m.group(1).lower(): float(m.group(2)) for m in _SVG_ATTR.finditer(root.group(0))}
    if b"width" in values and b"height" in values:
        return _valid(round(values[b"width"]), round(values[b"height"]))
    return None


# the copies


def make_copy(source: bytes, width: int, quality: int = QUALITY) -> bytes:
    """A WebP copy of the image ``source`` at ``width`` pixels, upright. Needs Pillow."""
    from PIL import Image, ImageOps

    with Image.open(BytesIO(source)) as image:
        icc = image.info.get("icc_profile")
        upright = ImageOps.exif_transpose(image) or image
        height = max(1, round(upright.height * width / upright.width))
        copy = upright.resize((width, height), Image.Resampling.LANCZOS)
        if copy.mode not in ("RGB", "RGBA"):
            alpha = copy.mode in ("LA", "PA", "RGBA") or "transparency" in copy.info
            copy = copy.convert("RGBA" if alpha else "RGB")
        buffer = BytesIO()
        options: dict[str, Any] = {"quality": quality}
        if icc:
            options["icc_profile"] = icc
        copy.save(buffer, format="WEBP", **options)
    return buffer.getvalue()


def _copyable(file: Path) -> bool:
    """Whether Pillow reads ``file`` as one still picture."""
    from PIL import Image

    try:
        with Image.open(file) as image:
            return getattr(image, "n_frames", 1) == 1 or image.format in ("JPEG", "MPO")
    except Exception:  # noqa: BLE001 - not an image Pillow reads
        return False


# the markup


@dataclass
class Sizer:
    """Sizes the ``<img>`` tags of one import and lists the copies to make."""

    app: str
    files: dict[str, Path]
    copies: bool = field(default_factory=lambda: pillow_available())
    #: design path -> the widths of its copies (``static/<app>/<path>.<width>w.webp``).
    planned: dict[str, list[int]] = field(default_factory=dict)
    #: design paths that could have had copies without Pillow.
    without_pillow: set[str] = field(default_factory=set)
    #: ``"<page>: <src>"`` for images whose size could not be read.
    unsized: list[str] = field(default_factory=list)
    _sizes: dict[str, tuple[int, int] | None] = field(default_factory=dict)
    _copyable_cache: dict[str, bool] = field(default_factory=dict)
    _noted: set[str] = field(default_factory=set)

    def size(self, path: str) -> tuple[int, int] | None:
        if path not in self._sizes:
            file = self.files.get(path)
            found = None
            if file is not None and path.lower().endswith(_SIZED):
                with file.open("rb") as handle:
                    found = image_size(handle.read(512 * 1024))
            self._sizes[path] = found
        return self._sizes[path]

    def widths(self, path: str, width: int) -> list[int]:
        if not path.lower().endswith(_COPYABLE):
            return []
        wanted = [w for w in WIDTHS if w < width]
        if not wanted:
            return []
        if not path.lower().endswith(".webp"):
            wanted.append(width)  # the full picture in WebP, for the widest screens
        if not self.copies:
            self.without_pillow.add(path)
            return []
        if path not in self._copyable_cache:
            self._copyable_cache[path] = _copyable(self.files[path])
        if not self._copyable_cache[path]:
            return []
        self.planned[path] = wanted
        return wanted

    def tag(self, node: Node, source: str, text: str, path: str | None, where: str) -> str:
        """The rewritten ``<img>`` start tag ``text`` with the attributes this adds."""
        if path is None:
            return text
        attrs = node.attrs(source)
        size = self.size(path)
        if size is None:
            if not (attrs.get("width") and attrs.get("height")) and where not in self._noted:
                self._noted.add(where)
                self.unsized.append(f"{where}: {path}")
            return text
        width, height = size
        added: dict[str, str] = {}
        given_width = _number(attrs.get("width"))
        given_height = _number(attrs.get("height"))
        if given_width is None and given_height is None:
            added["width"], added["height"] = str(width), str(height)
            added[MARKER] = NATURAL
        elif given_width is None and given_height is not None:
            added["width"] = str(max(1, round(given_height * width / height)))
            added[MARKER] = ""
        elif given_height is None and given_width is not None:
            added["height"] = str(max(1, round(given_width * height / width)))
            added[MARKER] = ""
        shown = given_width or width
        inside_picture = node.parent is not None and node.parent.tag == "picture"
        if "srcset" not in attrs and not inside_picture:
            copies = self.widths(path, width)
            if copies:
                lazy = (attrs.get("loading") or "").lower() == "lazy"
                natural = added.get(MARKER) == NATURAL
                if lazy and natural:
                    # A width taken from the layout (sizes=auto) needs a width that is not auto.
                    added[MARKER] = ""
                static = f"{self.app}/{path}"
                entries = [f"{{% static '{rendition_name(static, w)}' %}} {w}w" for w in copies]
                if width not in copies:
                    entries.append(f"{{% static '{static}' %}} {width}w")
                added["srcset"] = ", ".join(entries)
                base = f"(max-width: {shown}px) 100vw, {shown}px"
                added["sizes"] = f"auto, {base}" if lazy else base
        if not added:
            return text
        return _append(text, added)


def _number(value: str | None) -> int | None:
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def _append(tag: str, added: dict[str, str]) -> str:
    end = "/>" if tag.rstrip().endswith("/>") else ">"
    body = tag.rstrip()[: -len(end)].rstrip()
    pieces = [f' {name}="{value}"' if value else f" {name}" for name, value in added.items()]
    return body + "".join(pieces) + (" />" if end == "/>" else ">")


def copy_targets(app_static: Path, planned: dict[str, list[int]]) -> list[tuple[str, int, Path]]:
    """``(design path, width, file)`` of every copy, under the app's ``static/<app>/``."""
    return [
        (path, width, app_static.joinpath(*rendition_name(path, width).split("/")))
        for path, widths in sorted(planned.items())
        for width in widths
    ]
