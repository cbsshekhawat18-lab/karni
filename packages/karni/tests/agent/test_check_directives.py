"""K005 ESLint directives: only a comment that opens with the directive counts."""

from __future__ import annotations

from karni.agent.check import check_source

PATH = "frontend/src/pages/x.tsx"


def _k005_lines(src: str) -> list[int]:
    return [f.line for f in check_source(PATH, src) if f.code == "K005"]


def test_bare_line_directive_is_flagged() -> None:
    assert _k005_lines("// eslint-disable-next-line karni/no-raw-elements\n") == [1]


def test_bare_block_directive_is_flagged() -> None:
    assert _k005_lines("/* eslint-disable karni/no-raw-elements */\n") == [1]


def test_directive_with_reason_is_accepted() -> None:
    src = "// eslint-disable-next-line karni/no-raw-elements -- vendor widget\n"
    assert _k005_lines(src) == []


def test_prose_mentioning_a_directive_is_not_one() -> None:
    src = (
        "// Every eslint-disable comment in this project needs a reason.\n"
        "/* See docs: eslint-disable-next-line needs `-- why` */\n"
    )
    assert _k005_lines(src) == []
