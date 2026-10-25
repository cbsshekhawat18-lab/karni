"""Enough colour arithmetic for ``karni ui detect --css``: parsing, luminance, contrast.

It reads the notations a hand-written stylesheet uses (hex, ``rgb()``,
``hsl()``, the named colours) so the detector can tell a dark design from a
light one and pick a readable text colour for a button. A notation it does
not compute (``oklch()``, ``color-mix()``, ``light-dark()``) is still copied
into karni-theme.css as written: only the derived values need the numbers.

Escape hatch: none needed, the values written are the stylesheet's own.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass

__all__ = ["Rgba", "contrast", "is_dark", "luminance", "parse", "readable_on"]

#: The CSS named colours a stylesheet is likely to use for a role.
NAMED: dict[str, str] = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "orange": "#ffa500",
    "purple": "#800080",
    "gray": "#808080",
    "grey": "#808080",
    "silver": "#c0c0c0",
    "maroon": "#800000",
    "navy": "#000080",
    "teal": "#008080",
    "olive": "#808000",
    "lime": "#00ff00",
    "aqua": "#00ffff",
    "cyan": "#00ffff",
    "fuchsia": "#ff00ff",
    "magenta": "#ff00ff",
    "crimson": "#dc143c",
    "firebrick": "#b22222",
    "darkred": "#8b0000",
    "tomato": "#ff6347",
    "coral": "#ff7f50",
    "gold": "#ffd700",
    "indigo": "#4b0082",
    "violet": "#ee82ee",
    "pink": "#ffc0cb",
    "brown": "#a52a2a",
    "chocolate": "#d2691e",
    "tan": "#d2b48c",
    "beige": "#f5f5dc",
    "ivory": "#fffff0",
    "linen": "#faf0e6",
    "snow": "#fffafa",
    "whitesmoke": "#f5f5f5",
    "gainsboro": "#dcdcdc",
    "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3",
    "darkgray": "#a9a9a9",
    "darkgrey": "#a9a9a9",
    "dimgray": "#696969",
    "dimgrey": "#696969",
    "slategray": "#708090",
    "slategrey": "#708090",
    "lightslategray": "#778899",
    "darkslategray": "#2f4f4f",
    "steelblue": "#4682b4",
    "royalblue": "#4169e1",
    "dodgerblue": "#1e90ff",
    "midnightblue": "#191970",
    "darkblue": "#00008b",
    "skyblue": "#87ceeb",
    "lightblue": "#add8e6",
    "seagreen": "#2e8b57",
    "forestgreen": "#228b22",
    "darkgreen": "#006400",
    "limegreen": "#32cd32",
    "darkorange": "#ff8c00",
    "orangered": "#ff4500",
    "salmon": "#fa8072",
    "khaki": "#f0e68c",
    "wheat": "#f5deb3",
    "lavender": "#e6e6fa",
    "plum": "#dda0dd",
    "orchid": "#da70d6",
    "rebeccapurple": "#663399",
    "darkslateblue": "#483d8b",
    "transparent": "#00000000",
}

_HEX = re.compile(r"^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.IGNORECASE)
_FUNCTION = re.compile(r"^(rgba?|hsla?)\((.*)\)$", re.IGNORECASE | re.DOTALL)
_NUMBER = re.compile(r"^-?\d*\.?\d+$")


@dataclass(frozen=True)
class Rgba:
    """A colour as 0..255 channels and a 0..1 alpha."""

    r: float
    g: float
    b: float
    a: float = 1.0


def _channel(text: str, scale: float = 255.0) -> float | None:
    """A colour channel: a number, or a percentage of ``scale``."""
    text = text.strip()
    if text.endswith("%"):
        return float(text[:-1]) * scale / 100 if _NUMBER.match(text[:-1]) else None
    return float(text) if _NUMBER.match(text) else None


def _alpha(text: str) -> float | None:
    value = _channel(text, scale=1.0)
    return None if value is None else max(0.0, min(1.0, value))


def _hue(text: str) -> float | None:
    text = text.strip().lower()
    for unit, turn in (("deg", 360.0), ("grad", 400.0), ("rad", 6.283185307179586), ("turn", 1.0)):
        if text.endswith(unit):
            number = text[: -len(unit)]
            return float(number) * 360 / turn if _NUMBER.match(number) else None
    return float(text) if _NUMBER.match(text) else None


def _split_arguments(inner: str) -> tuple[list[str], str | None]:
    """``(channels, alpha)`` from ``r, g, b, a`` or ``r g b / a``."""
    alpha: str | None = None
    if "/" in inner:
        inner, _, alpha = inner.partition("/")
    parts = [p for p in re.split(r"[,\s]+", inner.strip()) if p]
    if alpha is None and len(parts) == 4:
        alpha = parts.pop()
    return parts, alpha


def parse(value: str) -> Rgba | None:
    """The colour ``value`` names, or ``None`` when it is not one this module computes."""
    text = value.strip().lower()
    named = NAMED.get(text)
    if named is not None:
        text = named
    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits)
        red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        a = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return Rgba(red, green, blue, a)
    match = _FUNCTION.match(text)
    if not match:
        return None
    name, inner = match.group(1), match.group(2)
    parts, alpha_text = _split_arguments(inner)
    if len(parts) != 3:
        return None
    alpha = 1.0 if alpha_text is None else _alpha(alpha_text)
    if alpha is None:
        return None
    if name.startswith("rgb"):
        channels = [_channel(part) for part in parts]
        if any(c is None for c in channels):
            return None
        r, g, b = (max(0.0, min(255.0, c)) for c in channels if c is not None)
        return Rgba(r, g, b, alpha)
    hue = _hue(parts[0])
    sat = _channel(parts[1], scale=1.0)
    light = _channel(parts[2], scale=1.0)
    if hue is None or sat is None or light is None:
        return None
    r, g, b = colorsys.hls_to_rgb(
        (hue % 360) / 360, max(0.0, min(1.0, light)), max(0.0, min(1.0, sat))
    )
    return Rgba(r * 255, g * 255, b * 255, alpha)


def _linear(channel: float) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: Rgba) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    return 0.2126 * _linear(colour.r) + 0.7152 * _linear(colour.g) + 0.0722 * _linear(colour.b)


def contrast(one: Rgba, other: Rgba) -> float:
    """WCAG contrast ratio, 1 to 21."""
    a, b = luminance(one), luminance(other)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def is_dark(colour: Rgba) -> bool:
    """Whether text on this colour should be light."""
    return luminance(colour) < 0.5


def readable_on(background: Rgba, candidates: list[str]) -> str:
    """The candidate with the most contrast on ``background``, else white or black.

    ``candidates`` are colour values (the stylesheet's own text and page
    colours, say); ones this module cannot compute are skipped.
    """
    best: tuple[float, str] | None = None
    for candidate in candidates:
        parsed = parse(candidate)
        if parsed is None or parsed.a < 1:
            continue
        ratio = contrast(background, parsed)
        if best is None or ratio > best[0]:
            best = (ratio, candidate)
    if best is not None and best[0] >= 4.5:
        return best[1]
    return "white" if is_dark(background) else "black"
