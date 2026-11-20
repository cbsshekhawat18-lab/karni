"""Experimental. Drawn placeholder images for demo data: no photo, no download, no paid service.

Demo rows with an image field look empty without a picture, and a picture
fetched from the web is somebody's work, needs a network and changes. A
placeholder is drawn instead: a tinted square, a shape and the initials of
a label, in colours that come from a key. The same label and key give the
same picture on every machine, so a seed stays deterministic::

    from karni.seeding import placeholder_image

    product.image = placeholder_image("Brass Desk Lamp", key="Lighting")

``key`` picks the colour family and the shape (a category, so every
product of a category shares a look), and ``label`` the initials and the
detail. ``placeholder_image`` returns a :class:`~django.core.files.base.ContentFile`
named after the label, ready for an ``ImageField`` or ``FileField``. A
Seeder steers a field with it::

    image = factory.LazyAttribute(lambda row: placeholder_image(row.name, key=row.kind))

It needs Pillow (``karni[images]``, which an ``ImageField`` needs anyway).

Override / escape hatch: :func:`draw` returns the Pillow image for a style
of your own, ``size`` and ``name`` change the file, and :data:`SHAPES` lists
the shapes a key can pick.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import re
from typing import Any, Final

from django.core.files.base import ContentFile

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["SHAPES", "draw", "initials", "placeholder_image"]

#: The shapes a key picks from.
SHAPES: Final = ("circle", "square", "diamond", "bars")


def _numbers(text: str) -> list[int]:
    return list(hashlib.sha256(text.encode("utf-8")).digest())


def _rgb(hue: float, lightness: float, saturation: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hls_to_rgb(hue % 1.0, lightness, saturation)
    return round(red * 255), round(green * 255), round(blue * 255)


def initials(label: str, *, most: int = 2) -> str:
    """Experimental. The first letters of ``label``'s first words: ``Brass Desk Lamp`` is ``BD``."""
    words = re.findall(r"[^\W_]+", label)
    return "".join(word[0] for word in words[:most]).upper() or "?"


def _font(size: int) -> Any:
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def draw(label: str, *, key: str | None = None, size: tuple[int, int] = (800, 800)) -> Any:
    """Experimental. The placeholder as a Pillow ``Image`` (see the module docstring)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - Pillow ships with karni[images]
        raise KarniImproperlyConfigured(
            "placeholder_image() draws with Pillow, which is not installed. Install "
            'karni[images] (pip install "karni[images]"), which an ImageField needs too.',
            code="E501",
        ) from None
    family = _numbers(key if key is not None else label)
    detail = _numbers(label)
    hue = family[0] / 255
    width, height = size
    side = min(width, height)
    image = Image.new("RGB", size, _rgb(hue, 0.9, 0.45))
    pen = ImageDraw.Draw(image)
    shape = SHAPES[family[1] % len(SHAPES)]
    strong = _rgb(hue + (detail[0] - 128) / 2048, 0.45 + detail[1] / 2550, 0.55)
    soft = _rgb(hue + 0.08, 0.78, 0.5)
    cx, cy = width / 2, height / 2
    radius = side * (0.28 + detail[2] / 2550)
    # A soft offset shape behind the main one gives each label its own picture.
    dx = side * (detail[3] - 128) / 1280
    dy = side * (detail[4] - 128) / 1280
    pen.ellipse(
        (cx + dx - radius * 0.9, cy + dy - radius * 0.9, cx + dx + radius * 0.9, cy + dy + radius),
        fill=soft,
    )
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    if shape == "circle":
        pen.ellipse(box, fill=strong)
    elif shape == "square":
        pen.rounded_rectangle(box, radius=int(radius * 0.25), fill=strong)
    elif shape == "diamond":
        pen.polygon(
            [(cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)],
            fill=strong,
        )
    else:
        bar = radius * 2 / 5
        for index in range(3):
            top = cy - radius + index * bar * 1.6
            pen.rounded_rectangle(
                (cx - radius, top, cx + radius * (1 - index * 0.2), top + bar),
                radius=int(bar / 2),
                fill=strong,
            )
    text = initials(label)
    font = _font(int(radius * 0.7))
    pen.text((cx, cy), text, fill=(255, 255, 255), font=font, anchor="mm")
    return image


def placeholder_image(
    label: str,
    *,
    key: str | None = None,
    size: tuple[int, int] = (800, 800),
    name: str | None = None,
) -> ContentFile[bytes]:
    """Experimental. A drawn PNG for ``label`` in ``key``'s colours (see the module docstring)."""
    buffer = io.BytesIO()
    draw(label, key=key, size=size).save(buffer, format="PNG")
    stem = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "placeholder"
    return ContentFile(buffer.getvalue(), name=name or f"{stem}.png")
