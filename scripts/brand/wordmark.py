"""Build the horizontal lockups: the mark plus the "karni" wordmark as outlines.

    python scripts/brand/wordmark.py <Jost[wght].ttf> assets/brand/

The wordmark is set in Jost (SIL Open Font License) at weight 600 and
converted to paths with fontTools, so the SVG depends on no installed font.
Two files come out: ``karni-horizontal.svg`` for light surfaces (black
ground, black wordmark) and ``karni-horizontal-dark.svg`` for dark surfaces
(the light-ground mark, white wordmark); a README ``<picture>`` element picks
one per colour scheme. ``wordmark_paths()`` is reused by the social preview.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

WEIGHT = 600
TEXT = "karni"
TRACKING = 0.02  # of the em, between letters
MARK = 1000  # the mark's canvas (viewBox) size
CAP = 400  # wordmark cap height in canvas units
GAP = 90  # space between the mark's clear-space box and the wordmark


def wordmark_paths(font_path: str, *, cap: float, x: float, baseline: float) -> tuple[str, float]:
    """``<path d>`` for the text at the given cap height; returns (d, advance width)."""
    font = instantiateVariableFont(TTFont(font_path), {"wght": WEIGHT})
    upem = font["head"].unitsPerEm
    cap_height = font["OS/2"].sCapHeight or upem * 0.7
    scale = cap / cap_height
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    hmtx = font["hmtx"]
    parts: list[str] = []
    pen_x = x
    for char in TEXT:
        name = cmap[ord(char)]
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".replace(".0", ""))
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, pen_x, baseline)))
        parts.append(pen.getCommands())
        pen_x += hmtx[name][0] * scale + TRACKING * upem * scale
    return "".join(parts), pen_x - x - TRACKING * upem * scale


def mark_paths(svg_text: str) -> list[tuple[str, str]]:
    """``[(fill, d), ...]`` of a traced mark file."""
    return re.findall(r'<path fill="([^"]+)" d="([^"]+)"/>', svg_text)


def lockup(mark_svg: str, font_path: str, *, wordmark_fill: str) -> str:
    paths = mark_paths(mark_svg)
    text_x = MARK + GAP
    baseline = MARK * 0.5 + CAP * 0.5 - MARK * 0.015  # x-height centred on the optical centre
    d, advance = wordmark_paths(font_path, cap=CAP, x=text_x, baseline=baseline)
    width = round(text_x + advance + MARK * 0.08)
    body = "\n".join(f'<path fill="{fill}" d="{path}"/>' for fill, path in paths)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {MARK}" '
        f'width="{width}" height="{MARK}" role="img" aria-label="Karni">\n'
        f"{body}\n"
        f'<path fill="{wordmark_fill}" d="{d}"/>\n'
        "</svg>\n"
    )


def main(font_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    dark_mark = (out / "karni-mark.svg").read_text()
    light_mark = (out / "karni-mark-light.svg").read_text()
    files = {
        "karni-horizontal.svg": lockup(dark_mark, font_path, wordmark_fill="#000000"),
        "karni-horizontal-dark.svg": lockup(light_mark, font_path, wordmark_fill="#FFFFFF"),
    }
    for name, content in files.items():
        (out / name).write_text(content)
        print(f"{name:<26} {len(content.encode()):>6} bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
