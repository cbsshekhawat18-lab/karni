"""The experimental mark is shown once per feature (docs/stability.md#where-the-mark-is-shown).

scripts/check_experimental.py reads scripts/experimental.toml: the features that are
experimental now, their docs sections and their entry points. These tests run it on
the repository, and on a small checkout of their own to show what it refuses.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import REPO_ROOT, requires_git

SCRIPT = REPO_ROOT / "scripts" / "check_experimental.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="needs the Karni checkout")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_experimental", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _module()


@requires_git
def test_the_repository_shows_the_mark_only_where_the_rule_puts_it(checker) -> None:
    problems = checker.problems(REPO_ROOT)
    assert problems == [], "\n".join(problems[:40])


def test_every_exception_has_a_reason() -> None:
    data = tomllib.loads((REPO_ROOT / "scripts" / "experimental.toml").read_text(encoding="utf-8"))
    for allow in data["allow"]:
        assert allow.get("reason", "").strip(), allow["path"]


STABILITY = """# Stability promise

## Experimental names

Experimental now:

- [Widgets](widgets.md): `karni.widgets`.

Stable since 0.1.0:

- nothing

## Supported platforms
"""

PAGE = """---
description: Widgets.
---

# Widgets

!!! warning "Experimental"
    Widgets are [experimental](stability.md#experimental-names).

Widgets do things.
"""

CONFIG = """[[feature]]
name = "Widgets"
docs = ["docs/widgets.md"]
marks = ["pkg/widgets.py", "pkg/shared.py::make"]
"""

WIDGETS = '"""Experimental. Widgets."""\n'
SHARED = 'def make():\n    """Experimental. Make a widget."""\n\n\ndef other():\n    """Other."""\n'


def _checkout(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    contents = {
        "docs/stability.md": STABILITY,
        "docs/widgets.md": PAGE,
        "scripts/experimental.toml": CONFIG,
        "pkg/widgets.py": WIDGETS,
        "pkg/shared.py": SHARED,
        **(extra or {}),
    }
    for name, text in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


@requires_git
def test_a_feature_with_its_line_note_and_entry_points_passes(checker, tmp_path) -> None:
    assert checker.problems(_checkout(tmp_path)) == []


@requires_git
def test_a_mark_in_a_place_the_rule_does_not_name_fails(checker, tmp_path) -> None:
    extra = {
        "pkg/helpers.py": 'def helper():\n    """Experimental. A helper of widgets."""\n',
        "docs/other.md": "# Other\n\nWidgets (experimental) appear here too.\n",
        "pkg/conf.py": 'HELP = "Experimental. A setting of widgets."\n',
    }
    problems = checker.problems(_checkout(tmp_path, extra))
    assert any(p.startswith("pkg/helpers.py:2:") for p in problems), problems
    assert any(p.startswith("docs/other.md:3:") for p in problems), problems
    assert any(p.startswith("pkg/conf.py:1:") for p in problems), problems


@requires_git
def test_a_second_mark_in_an_entry_point_file_fails(checker, tmp_path) -> None:
    shared = SHARED.replace('"""Other."""', '"""Experimental. Other."""')
    problems = checker.problems(_checkout(tmp_path, {"pkg/shared.py": shared}))
    assert any("pkg/shared.py: 2 marks" in p for p in problems), problems


@requires_git
def test_a_feature_without_its_note_or_its_line_fails(checker, tmp_path) -> None:
    page = PAGE.replace(
        '!!! warning "Experimental"\n    Widgets are [experimental](stability.md#experimental-names).\n\n',
        "",
    )
    stability = STABILITY.replace("- [Widgets](widgets.md): `karni.widgets`.\n", "")
    problems = checker.problems(
        _checkout(tmp_path, {"docs/widgets.md": page, "docs/stability.md": stability})
    )
    assert "Widgets: docs/widgets.md: the page does not open with the note" in problems
    assert any("no line in docs/stability.md" in p for p in problems), problems


@requires_git
def test_an_entry_point_without_the_mark_fails(checker, tmp_path) -> None:
    problems = checker.problems(_checkout(tmp_path, {"pkg/widgets.py": '"""Widgets."""\n'}))
    assert "Widgets: pkg/widgets.py: the docstring does not start with 'Experimental.'" in problems


def test_the_anchors_follow_mkdocs_and_github(checker) -> None:
    heading = "Taking a module out (`karni remove <x>`)"
    assert checker.mkdocs_slug(heading) == "taking-a-module-out-karni-remove-x"
    assert checker.mkdocs_slug("Query plans: `karni queries --explain`") == (
        "query-plans-karni-queries-explain"
    )
    assert checker.github_slug("ResourceBoard: a board by state (experimental)") == (
        "resourceboard-a-board-by-state-experimental"
    )
