"""The Karni mark for the terminal: a few lines, only where a person will see them.

``print_mark()`` writes a small truecolor rendering of the crown when stdout
is an interactive terminal; it writes nothing when the output is piped, when
``NO_COLOR`` is set (https://no-color.org) or when ``TERM`` is ``dumb``, so
no machine-readable output ever carries it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import IO

ACCENT = "\x1b[38;2;251;93;8m"
LINE = "\x1b[38;2;255;255;255m"
RESET = "\x1b[0m"

#: Rows of the mark, as (ink, text) runs — rings above the crown's legs, peak and crossings.
ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    ((ACCENT, "  ●   ●   ●"),),
    ((LINE, "  │╲ ╱ ╲ ╱│"),),
    ((LINE, "  │ ╳   ╳ │"),),
    ((LINE, "  │╱ ╲ ╱ ╲│"),),
)


def wants_mark(stream: IO[str] | None = None, environ: Mapping[str, str] | None = None) -> bool:
    """Is this an interactive, colour-capable terminal that has not opted out?"""
    stream = stream or sys.stdout
    env: Mapping[str, str] = os.environ if environ is None else environ
    if env.get("NO_COLOR") or env.get("TERM", "") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def mark_lines(*, colour: bool = True) -> list[str]:
    """The mark's rows, with or without ANSI colour."""
    lines = []
    for row in ROWS:
        text = "".join(f"{ink}{run}{RESET}" if colour else run for ink, run in row)
        lines.append(text)
    return lines


def print_mark(stream: IO[str] | None = None) -> bool:
    """Print the mark when :func:`wants_mark`; returns whether it was printed."""
    stream = stream or sys.stdout
    if not wants_mark(stream):
        return False
    stream.write("\n".join(mark_lines()) + "\n\n")
    stream.flush()
    return True
