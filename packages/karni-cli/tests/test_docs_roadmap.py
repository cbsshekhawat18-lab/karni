"""The roadmap pages say what is merged: statuses agree with the CHANGELOG (A6-08)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

ROADMAP = REPO_ROOT / "docs" / "roadmap"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

pytestmark = pytest.mark.skipif(
    not ROADMAP.is_dir(), reason="needs the repository checkout (docs/roadmap/)"
)

ROW = re.compile(r"^\| (?P<item>[A-Z]?\d+[a-z]?) \| .+ \| (?P<status>[^|]+) \|$", re.MULTILINE)
STATUS = re.compile(r"^(planned|in progress|done)\b")


def _statuses(page: Path) -> dict[str, str]:
    return {match["item"]: match["status"].strip() for match in ROW.finditer(page.read_text())}


def _pages() -> dict[str, dict[str, str]]:
    return {page.stem: _statuses(page) for page in sorted(ROADMAP.glob("*.md"))}


def test_every_status_is_planned_in_progress_or_done() -> None:
    for name, statuses in _pages().items():
        assert statuses, f"docs/roadmap/{name}.md: no item rows found"
        wrong = {item: status for item, status in statuses.items() if not STATUS.match(status)}
        assert wrong == {}, f"docs/roadmap/{name}.md: {wrong}"


def test_every_sub_item_a_status_names_has_a_row() -> None:
    for name, statuses in _pages().items():
        for item, status in statuses.items():
            for sub in re.findall(rf"\b({re.escape(item)}[a-z])\b", status):
                assert sub in statuses, f"docs/roadmap/{name}.md: {item} names {sub}, no row"


ITEM = re.compile(r"\b(large-apps|app-builder) item ([A-Z]?\d+[a-z]?)\b")


def _newest_cited() -> list[tuple[str, str]]:
    """The roadmap items the newest CHANGELOG section that cites any of them ships.

    A patch release (0.5.1) fixes and cites no roadmap item; the release before it does.
    """
    for section in re.split(r"^## ", CHANGELOG.read_text(), flags=re.MULTILINE)[1:]:
        cited = ITEM.findall(section)
        if cited:
            return cited
    return []


def test_an_item_the_changelog_ships_is_not_planned() -> None:
    pages = _pages()
    cited = _newest_cited()
    assert cited, "no CHANGELOG section cites a roadmap item"
    planned = [
        f"{page} item {item}"
        for page, item in cited
        if pages[page].get(item, "planned").startswith("planned")
    ]
    assert planned == [], f"the CHANGELOG ships {planned}, the roadmap says planned"
