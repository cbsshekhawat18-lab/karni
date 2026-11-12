"""No AI tool or company names in the tracked files, outside scripts/tool-names.toml's exceptions.

The names themselves live only in that file: these tests take them from its samples.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import REPO_ROOT, requires_git

SCRIPT = REPO_ROOT / "scripts" / "check_tool_names.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="needs the Karni checkout")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_tool_names", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _module()


def test_every_term_matches_its_sample_and_a_neutral_line_passes(checker) -> None:
    config = checker.load()
    assert len(config.terms) >= 20
    for term in config.terms:
        assert term.pattern.search(term.sample), term.name
    neutral = "Karni writes AGENTS.md, which any coding agent reads. cursor.execute(sql)"
    assert checker.scan_text("README.md", neutral, config) == []


def test_a_name_outside_the_exceptions_fails(checker) -> None:
    config = checker.load()
    for term in config.terms:
        hits = checker.scan_text("docs/new-page.md", f"intro\nWorks with {term.sample}.\n", config)
        assert [(h.line, h.term) for h in hits] == [(2, term.name)], term.name


def test_the_exceptions_are_narrow(checker) -> None:
    config = checker.load()
    settings = next(a for a in config.allow if a.path == "docs/settings.md")
    deprecation = next(a for a in config.allow if a.path == "docs/migrations/0.5.md")
    provider = next(t for t in config.terms if settings.allows(t.name)).sample
    deprecated = next(t for t in config.terms if deprecation.allows(t.name)).sample
    # karni-ai's own page may name its providers; a generated settings page only those.
    assert checker.scan_text("docs/ai-extraction.md", deprecated, config) == []
    assert checker.scan_text("docs/settings.md", provider, config) == []
    assert checker.scan_text("docs/settings.md", deprecated, config) != []
    # Released CHANGELOG sections stay; the unreleased part takes only the deprecation note.
    released = "## 9.9.9 (unreleased)\n- x\n## 0.4.0 (2026-10-22)\n- " + provider + "\n"
    assert checker.scan_text("CHANGELOG.md", released, config) == []
    unreleased = "## 9.9.9 (unreleased)\n- " + provider + "\n## 0.4.0 (2026-10-22)\n"
    assert [h.line for h in checker.scan_text("CHANGELOG.md", unreleased, config)] == [2]
    assert checker.scan_text("CHANGELOG.md", "- " + deprecated + " is deprecated\n", config) == []


@requires_git
def test_every_exception_has_a_reason_and_matches_a_tracked_file(checker) -> None:
    config = checker.load()
    tracked = [path for path, _ in checker.tracked_files(REPO_ROOT)]
    for allow in config.allow:
        assert allow.reason.strip(), allow.path
        assert any(allow.covers(path) for path in tracked), f"stale exception: {allow.path}"


@requires_git
def test_the_repository_names_no_ai_tool_outside_the_exceptions(checker) -> None:
    """The check CI runs: a name that creeps back into a tracked file fails here."""
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    hits = checker.scan(checker.tracked_files(REPO_ROOT), checker.load())
    assert hits == [], "\n".join(hit.render() for hit in hits)


@requires_git
def test_the_command_line_fails_on_a_tracked_file(checker, tmp_path: Path) -> None:
    config = (REPO_ROOT / "scripts" / "tool-names.toml").read_text()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool-names.toml").write_text(config)
    sample = checker.load().terms[0].sample
    (tmp_path / "notes.md").write_text(f"Built for {sample}.\n")
    (tmp_path / "ok.md").write_text("Built for coding agents.\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0\0" + sample.encode())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert checker.main(["--root", str(tmp_path)]) == 1
    (tmp_path / "notes.md").write_text("Built for coding agents.\n")
    assert checker.main(["--root", str(tmp_path)]) == 0
