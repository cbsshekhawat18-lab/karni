"""docs/tutorial.md quotes examples/eventhub: every quoted block must still be in its file."""

from __future__ import annotations

import re

from .conftest import REPO_ROOT

TUTORIAL = REPO_ROOT / "docs" / "tutorial.md"
SNIPPET = re.compile(r"<!-- karni:snippet (?P<path>\S+) -->\s*```\w*\n(?P<code>.*?)```", re.DOTALL)


def _normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def test_every_tutorial_snippet_is_verbatim_from_its_file() -> None:
    matches = list(SNIPPET.finditer(TUTORIAL.read_text(encoding="utf-8")))
    assert len(matches) >= 8, "the tutorial lost its snippet markers"
    stale = []
    for match in matches:
        source = (REPO_ROOT / match["path"]).read_text(encoding="utf-8")
        if _normalized(match["code"]) not in source:
            stale.append(match["path"])
    assert not stale, f"these tutorial snippets no longer match their files: {stale}"


def test_the_tutorial_quotes_the_measured_line_count() -> None:
    readme = (REPO_ROOT / "examples" / "eventhub" / "README.md").read_text(encoding="utf-8")
    count = re.search(r"\*\*Project code: (\d+) lines\*\*", readme)
    assert count, "the EventHub README lost its measured count"
    assert f"{count.group(1)} lines of project code" in TUTORIAL.read_text(encoding="utf-8")
