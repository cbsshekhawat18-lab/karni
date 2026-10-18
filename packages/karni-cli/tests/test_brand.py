"""The terminal mark prints only to a person at a colour terminal."""

from __future__ import annotations

from io import StringIO
from typing import Any

from karni_cli import brand


class _Tty(StringIO):
    def isatty(self) -> bool:
        return True


def test_mark_is_four_lines_with_the_brand_colours() -> None:
    lines = brand.mark_lines()
    assert len(lines) == 4
    assert lines[0].startswith(brand.ACCENT) and lines[1].startswith(brand.LINE)
    assert all(line.endswith(brand.RESET) for line in lines)
    assert "\x1b" not in "".join(brand.mark_lines(colour=False))


def test_not_a_tty_prints_nothing() -> None:
    out = StringIO()
    assert brand.print_mark(out) is False
    assert out.getvalue() == ""


def test_no_color_and_dumb_terminals_opt_out() -> None:
    assert brand.wants_mark(_Tty(), {"NO_COLOR": "1"}) is False
    assert brand.wants_mark(_Tty(), {"TERM": "dumb"}) is False
    assert brand.wants_mark(_Tty(), {}) is True


def test_tty_gets_the_mark(monkeypatch: Any) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    out = _Tty()
    assert brand.print_mark(out) is True
    assert out.getvalue().count("\n") == 5  # four rows and a blank line
