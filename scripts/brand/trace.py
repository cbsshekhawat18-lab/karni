"""Vectorise the Karni mark from the source PNG into the SVG asset set.

    python scripts/brand/trace.py <source.png> assets/brand/

Reads the hand-drawn raster, separates it into its three flat colours
(ground #000000, accent #FB5D08, line #FFFFFF — anti-aliasing shades are
merged to the nearest), traces each colour with potrace so the organic
strokes keep their character, and writes:

* ``karni-mark.svg``        the full mark on a square canvas, transparent ground
* ``karni-mark-light.svg``  the same mark with the ground inverted for dark surfaces
* ``karni-mark-mono.svg``   one colour (``currentColor``), the lines knocked out
* ``karni-mark-simple.svg`` the small-size variant (hand-authored geometry below)
* ``favicon.svg``           the simple variant

The square canvas has equal clear space on every side and the artwork sits
on the optical centre (1.5% above the geometric one). No raster, filters or
clip paths are used; coordinates are rounded to keep every file small.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import potrace
from PIL import Image

GROUND = (0, 0, 0)
ACCENT = (0xFB, 0x5D, 0x08)
LINE = (0xFF, 0xFF, 0xFF)
WORK = 1400  # working raster width in px; trace precision vs file size
CANVAS = 1000  # viewBox size of the square assets
CLEAR = 0.10  # clear space on each side, as a fraction of the canvas
OPTICAL_LIFT = 0.015  # artwork centre sits this much above the geometric centre


def classify(image: Image.Image) -> dict[str, np.ndarray]:
    """Masks for the ground silhouette, the accent and the line, nearest-colour."""
    rgba = np.asarray(image.convert("RGBA")).astype(int)
    alpha = rgba[..., 3] >= 128
    rgb = rgba[..., :3]
    palette = np.array([GROUND, ACCENT, LINE])
    distances = ((rgb[..., None, :] - palette[None, None, :, :]) ** 2).sum(-1)
    nearest = distances.argmin(-1)
    return {
        "silhouette": alpha,
        "accent": alpha & (nearest == 1),
        "line": alpha & (nearest == 2),
    }


def trace(mask: np.ndarray, scale: float, offset: tuple[float, float], **options: object) -> str:
    """potrace a boolean mask into one SVG path string in canvas units."""
    # potracer traces the pixels *below* its black level, so the shape is 0.
    bitmap = potrace.Bitmap(np.logical_not(mask))
    path = bitmap.trace(turdsize=12, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY, **options)

    def pt(point: object) -> str:
        x, y = point.x, point.y  # type: ignore[attr-defined]
        return f"{x * scale + offset[0]:.1f} {y * scale + offset[1]:.1f}"

    parts: list[str] = []
    for curve in path:
        parts.append(f"M{pt(curve.start_point)}")
        for segment in curve.segments:
            if segment.is_corner:
                parts.append(f"L{pt(segment.c)}L{pt(segment.end_point)}")
            else:
                parts.append(f"C{pt(segment.c1)} {pt(segment.c2)} {pt(segment.end_point)}")
        parts.append("Z")
    return (
        "".join(parts)
        .replace(".0 ", " ")
        .replace(".0C", "C")
        .replace(".0L", "L")
        .replace(".0Z", "Z")
    )


def crop_to_artwork(image: Image.Image) -> Image.Image:
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    ys, xs = np.nonzero(alpha > 0)
    return image.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def svg(body: str, *, size: int = CANVAS) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" role="img" aria-label="Karni">\n{body}\n</svg>\n'
    )


SIMPLE_BODY = """\
<path fill="{ground}" d="{blob}"/>
<circle cx="340" cy="300" r="44" fill="{accent}"/>
<circle cx="500" cy="276" r="44" fill="{accent}"/>
<circle cx="660" cy="300" r="44" fill="{accent}"/>
<path fill="none" stroke="{line}" stroke-width="58" stroke-linecap="round" stroke-linejoin="round"
      d="M318 420v280l182-250 182 250V420M500 450 410 700M500 450l90 250"/>"""


def simple_variant(blob: str, *, ground: str, accent: str, line: str) -> str:
    """The small-size variant: solid dots, thick strokes, two crossings instead of four.

    The crown keeps its silhouette — three points under three dots, the
    outer legs dropping straight — so it reads as the same mark next to the
    full one, while the strokes stay above 1.5px at 16px.
    """
    return svg(SIMPLE_BODY.format(blob=blob, ground=ground, accent=accent, line=line))


def main(source: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    art = crop_to_artwork(Image.open(source))
    width, height = art.size
    work_h = round(WORK * height / width)
    art = art.resize((WORK, work_h), Image.LANCZOS)
    masks = classify(art)

    # Fit the artwork's longer side inside the clear-space box, centred optically.
    box = CANVAS * (1 - 2 * CLEAR)
    scale = box / max(WORK, work_h)
    offset_x = (CANVAS - WORK * scale) / 2
    offset_y = (CANVAS - work_h * scale) / 2 - CANVAS * OPTICAL_LIFT
    offset = (offset_x, offset_y)

    blob = trace(masks["silhouette"], scale, offset, alphamax=1.2, opttolerance=0.8)
    accent = trace(masks["accent"], scale, offset, alphamax=1.0, opttolerance=0.6)
    line = trace(masks["line"], scale, offset, alphamax=1.0, opttolerance=0.6)
    simple_blob = trace(masks["silhouette"], scale, offset, alphamax=1.334, opttolerance=2.0)

    full = svg(
        f'<path fill="#000000" d="{blob}"/>\n'
        f'<path fill="#FB5D08" d="{accent}"/>\n'
        f'<path fill="#FFFFFF" d="{line}"/>'
    )
    light = svg(
        f'<path fill="#FFFFFF" d="{blob}"/>\n'
        f'<path fill="#FB5D08" d="{accent}"/>\n'
        f'<path fill="#000000" d="{line}"/>'
    )
    mono = svg(f'<path fill="currentColor" fill-rule="evenodd" d="{blob}{accent}{line}"/>')
    simple = simple_variant(simple_blob, ground="#000000", accent="#FB5D08", line="#FFFFFF")

    files = {
        "karni-mark.svg": full,
        "karni-mark-light.svg": light,
        "karni-mark-mono.svg": mono,
        "karni-mark-simple.svg": simple,
        "favicon.svg": simple,
    }
    for name, content in files.items():
        (out / name).write_text(content)
        print(f"{name:<24} {len(content.encode()):>6} bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
