"""``karni upgrade``: the changelog <-> codemod registry, version selection, the command.

The command tests run on a throwaway git project holding code that uses
every 0.2 deprecation, with the installed-version probe replaced.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import karni_cli.commands.upgrade as upgrade_mod
from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.upgrades import changelog, engine
from karni_cli.upgrades.codemod import Codemod, Outcome, load_codemod
from karni_cli.upgrades.python import RenameSetting, RenameSymbol
from karni_cli.upgrades.typescript import RenameExport

UPGRADES = Path(changelog.__file__).resolve().parent
FIXTURE_CHANGELOG = Path(__file__).parent / "fixtures" / "upgrade_changelog"
#: FIXTURE codemod for the fixture changelog entry (no shipped @karni/ui change yet).
FIXTURE_TS = RenameExport(module="@karni/ui", old="DataTable", new="ResourceTable")


# the changelog and the codemods agree


def test_every_mechanical_change_resolves_to_an_editing_codemod() -> None:
    for change in changelog.load():
        if change.mechanical:
            assert load_codemod(change.codemod).edits, change.id
        elif change.codemod:
            assert load_codemod(change.codemod).edits is False, f"{change.id}: detector edits"


def test_every_codemod_module_is_recorded_and_named_by_its_breaking_version() -> None:
    modules = {
        f"{path.parent.name}.{path.stem}"
        for path in UPGRADES.glob("v*_*/*.py")
        if path.stem != "__init__"
    }
    recorded = {change.codemod: change for change in changelog.load() if change.codemod}
    assert modules == set(recorded)
    for codemod_id, change in recorded.items():
        version: str = change.breaks_in
        parts = [*version.split("."), "0"]
        assert codemod_id.split(".")[0] == f"v{parts[0]}_{parts[1]}", codemod_id


def test_rename_codemods_carry_the_changelog_data() -> None:
    for change in changelog.load():
        if change.kind in ("setting-rename", "import-move", "base-rename") and change.codemod:
            codemod = load_codemod(change.codemod)
            assert isinstance(codemod, RenameSymbol | RenameSetting), change.id
            assert (codemod.old, codemod.new) == (change.symbol, change.replacement)


def test_the_shipped_0_2_entries() -> None:
    by_id = {change.id: change for change in changelog.load()}
    assert by_id["all-objects"].codemod == "v1_0.all_objects_to_without"
    assert by_id["agent-guidance-files"].codemod == "v0_2.agent_guidance"
    assert by_id["mandatory-access"].mechanical is False
    assert changelog.newest_release(by_id.values()) == "0.3.0"
    assert by_id["django-5-2"].release == "0.3.0" and not by_id["django-5-2"].mechanical
    assert by_id["role-scope-paths-checked"].release == "0.3.0"
    assert str(changelog.horizon(by_id.values())) == "1.0"
    assert changelog.docs_url("migrations/0.2.md#all_objects").endswith(
        "migrations/0.2/#all_objects"
    )


# selection


def _ids(current: str, target: str) -> list[str]:
    return [change.id for change in changelog.select(changelog.load(), current, target)]


def test_selection_between_versions() -> None:
    every = [change.id for change in changelog.load() if change.release == "0.2.0"]
    in_0_3 = {"django-5-2", "role-scope-paths-checked"}
    from_0_1 = _ids("0.1.0", "0.2.0")
    assert sorted(from_0_1) == sorted(every)
    # What breaks in 0.2 runs first, then what breaks in 1.0.
    assert from_0_1.index("agent-guidance-files") < from_0_1.index("all-objects")
    deprecations = {"all-objects", "all-with-deleted", "deleted-only", "soft-delete-manager-mixin"}
    # From the deprecating release itself: the deprecations, not the 0.2 breaks again.
    assert deprecations <= set(_ids("0.2.0", "0.2.0"))
    assert "mandatory-access" not in _ids("0.2.0", "1.0")
    assert set(_ids("0.2.0", "1.0")) == set(_ids("0.2.0", "0.2.0")) | in_0_3
    assert in_0_3 <= set(_ids("0.2.0", "0.3.0"))
    assert not in_0_3 & set(_ids("0.1.0", "0.2.0"))  # a 0.2 target never sees 0.3 changes
    assert _ids("1.0.0", "1.1") == []
    assert _ids("0.1.0", "0.1.9") == []  # replacements do not exist before 0.2
    assert set(_ids("0.2.0.dev3", "0.2.0")) == set(every)  # pre-releases count as before


# the command: helpers

MODELS = """\
from karni.managers import BaseManager, SoftDeleteManagerMixin
from karni.models import BaseModel


class BookManager(SoftDeleteManagerMixin, BaseManager):
    pass


class Book(BaseModel):
    objects = BookManager()
"""
VIEWS = """\
from library.models import Book


def everything():
    return Book.all_objects.filter(title__isnull=False)


def removed(shelf):
    return shelf.books.deleted_only(), Book.objects.all_with_deleted()


def unrelated():
    all_objects = [1, 2]
    return all_objects
"""
VIEWSETS = """\
from karni.api import BaseViewSet
from karni.accounts.permissions import IsOwner


class BookViewSet(BaseViewSet):
    object_permission_classes = [IsOwner]
"""


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Karni", "-c", "user.email=karni@example.com", *args],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "library_site"
    (root / "library").mkdir(parents=True)
    (root / "library" / "migrations").mkdir()
    (root / "manage.py").write_text("#!/usr/bin/env python\n")
    (root / "library" / "models.py").write_text(MODELS)
    (root / "library" / "views.py").write_text(VIEWS)
    (root / "library" / "viewsets.py").write_text(VIEWSETS)
    (root / "library" / "migrations" / "0001_initial.py").write_text("Book.all_objects\n")
    monkeypatch.chdir(root)
    calls: list[str] = []

    def probe(project: Path, docker: Any, service: str) -> str:
        calls.append(str(project))
        return "0.1.0"

    monkeypatch.setattr(upgrade_mod, "_installed_version", probe)
    return root


@pytest.fixture
def git_project(project: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "initial")
    return project


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in root.rglob("*.py")
        if ".git" not in path.parts
    }


# the command


def test_list_needs_no_project(runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["upgrade", "--list"])
    assert result.exit_code == 0, result.output
    assert "default --to: 0.3.0" in result.output
    assert "all-objects  [api-change, codemod v1_0.all_objects_to_without, removed in 1.0]" in (
        result.output
    )
    assert "object-permission-classes  [api-change, manual, detector" in result.output


def test_apply_and_report(runner, git_project: Path) -> None:
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "karni 0.1.0 -> 0.3.0: 25 change(s), 5 mechanical, 20 manual" in out

    views = (git_project / "library" / "views.py").read_text()
    assert (
        'Book.objects.without("soft_delete", reason="<auto: migrated from all_objects>")' in views
    )
    assert (
        'shelf.books.without("soft_delete", reason="<auto: migrated from deleted_only()>").dead()'
        in views
    )
    assert "all_objects = [1, 2]" in views  # a local variable stays
    models = (git_project / "library" / "models.py").read_text()
    assert "class BookManager(ScopedManagerMixin, BaseManager):" in models
    # Migrations are history: never rewritten.
    assert (git_project / "library/migrations/0001_initial.py").read_text() == "Book.all_objects\n"

    applied, manual = out.split("Could not fix automatically")
    assert "Applied automatically:" in applied
    assert "all-objects: Model.all_objects ->" in applied
    assert "      library/views.py: 1" in applied
    assert "      library/models.py: 2" in applied
    # A detector site, with its migration note.
    assert "library/viewsets.py:6: express this rule in the access declaration" in manual
    assert "migrations/0.2/#object_permission_classes" in manual
    # A manual-only entry: summary and link, no detector.
    assert "mandatory-access: karni.api.BaseViewSet" in manual
    assert "migrations/0.2/#every-baseviewset-declares-access" in manual
    assert "related-lookups: no uses found" in out
    assert "agent-guidance-files: nothing to change" in out
    assert "django-5-2: Django" in manual
    assert "Next: review `git diff`, pin karni to 0.3.0" in out

    changed = set(_git(git_project, "status", "--porcelain").split())
    assert {"library/views.py", "library/models.py"} <= changed
    _git(git_project, "commit", "-qam", "upgrade")
    again = runner.invoke(app, ["upgrade"])
    assert again.exit_code == 0, again.output
    assert "Applied automatically" not in again.output  # idempotent
    assert _git(git_project, "status", "--porcelain") == ""


def test_a_dirty_tree_is_refused_with_the_reason(runner, git_project: Path) -> None:
    (git_project / "library" / "views.py").write_text(VIEWS + "# work in progress\n")
    before = _snapshot(git_project)
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CliError)
    message = str(result.exception)
    assert "uncommitted changes (library/views.py)" in message
    assert "git diff" in message and "--allow-dirty" in message and "--dry-run" in message
    assert _snapshot(git_project) == before

    allowed = runner.invoke(app, ["upgrade", "--allow-dirty"])
    assert allowed.exit_code == 0, allowed.output
    assert "Continuing because of --allow-dirty" in allowed.output
    assert "# work in progress" in (git_project / "library" / "views.py").read_text()
    assert "objects.without" in (git_project / "library" / "views.py").read_text()


def test_outside_git_needs_allow_dirty(runner, project: Path) -> None:
    result = runner.invoke(app, ["upgrade"])
    assert isinstance(result.exception, CliError)
    assert "not in a git work tree" in str(result.exception)
    allowed = runner.invoke(app, ["upgrade", "--allow-dirty"])
    assert allowed.exit_code == 0, allowed.output
    assert "objects.without" in (project / "library" / "views.py").read_text()


def test_dry_run_prints_a_diff_and_writes_nothing(runner, project: Path) -> None:
    before = _snapshot(project)
    result = runner.invoke(app, ["upgrade", "--dry-run"])  # no git needed: nothing is written
    assert result.exit_code == 0, result.output
    assert "--- a/library/views.py\n+++ b/library/views.py\n" in result.output
    assert "-    return Book.all_objects.filter(title__isnull=False)\n" in result.output
    assert "+class BookManager(ScopedManagerMixin, BaseManager):\n" in result.output
    assert "Would apply automatically:" in result.output
    assert "Dry run: 2 file(s) would change. Nothing was written." in result.output
    assert _snapshot(project) == before


def test_versions(runner, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe_calls: list[str] = []

    def probe(*args: Any) -> str:
        probe_calls.append("probed")
        return "0.1.0"

    monkeypatch.setattr(upgrade_mod, "_installed_version", probe)
    explicit = runner.invoke(app, ["upgrade", "--from", "1.0.0", "--to", "1.0.0"])
    assert explicit.exit_code == 0, explicit.output
    assert "no recorded breaking changes. Nothing to do." in explicit.output
    assert probe_calls == []  # --from skips the probe

    older = runner.invoke(app, ["upgrade", "--from", "0.2.0", "--to", "0.1.0"])
    assert "does not downgrade" in str(older.exception)
    bad = runner.invoke(app, ["upgrade", "--to", "latest"])
    assert "is not a version number" in str(bad.exception)
    beyond = runner.invoke(app, ["upgrade", "--to", "2.0", "--dry-run"])
    assert "records changes up to 1.0" in beyond.output


# the engine


class _Boom(Codemod):
    def apply(self, root: Path) -> Outcome:
        raise RuntimeError("kaboom")


def test_a_failing_codemod_writes_nothing(project: Path) -> None:
    changes = changelog.select(changelog.load(), "0.1.0", "0.2.0")
    before = _snapshot(project)

    def resolve(codemod_id: str) -> Codemod:
        return (
            _Boom()
            if codemod_id == "v1_0.deleted_only_to_without_dead"
            else load_codemod(codemod_id)
        )

    with pytest.raises(CliError, match="deleted_only_to_without_dead.*Nothing was written"):
        engine.run(
            project, changes, current="0.1.0", target="0.2.0", dry_run=False, resolve=resolve
        )
    assert _snapshot(project) == before


def test_new_and_removed_files_are_diffed_and_written(project: Path) -> None:
    class Move(Codemod):
        def apply(self, root: Path) -> Outcome:
            (root / "library" / "viewsets.py").unlink()
            (root / "library" / "api.py").write_text("moved = True\n")
            return Outcome(files={"library/api.py": 1})

    (change,) = [c for c in changelog.load() if c.id == "all-objects"]
    report = engine.run(
        project, [change], current="0.1.0", target="0.2.0", dry_run=True, resolve=lambda _: Move()
    )
    assert "--- /dev/null\n+++ b/library/api.py\n" in report.diff
    assert "--- a/library/viewsets.py\n+++ /dev/null\n" in report.diff
    assert (project / "library" / "viewsets.py").is_file()
    engine.run(
        project, [change], current="0.1.0", target="0.2.0", dry_run=False, resolve=lambda _: Move()
    )
    assert not (project / "library" / "viewsets.py").exists()
    assert (project / "library" / "api.py").read_text() == "moved = True\n"


def test_the_typescript_fixture_entry_end_to_end(
    runner, git_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A @karni/ui rename as pure data: one changelog entry, one RenameExport (FIXTURES)."""
    screen = git_project / "frontend" / "src" / "screen.tsx"
    screen.parent.mkdir(parents=True)
    screen.write_text('import { DataTable } from "@karni/ui";\nexport const s = <DataTable />;\n')
    _git(git_project, "add", "-A")
    _git(git_project, "commit", "-qm", "frontend")
    fixture_changes = changelog.load(FIXTURE_CHANGELOG)
    monkeypatch.setattr(upgrade_mod.changelog, "load", lambda directory=None: fixture_changes)
    monkeypatch.setattr(upgrade_mod, "load_codemod", lambda codemod_id: FIXTURE_TS)

    # Without Node.js: skipped with the reason, and nothing written.
    monkeypatch.delenv("KARNI_JSCODESHIFT", raising=False)
    monkeypatch.setattr("karni_cli.upgrades.typescript.shutil.which", lambda name: None)
    result = runner.invoke(app, ["upgrade", "--to", "0.9.0"])
    assert result.exit_code == 0, result.output
    assert "fixture-data-table: Node.js (npx) not found, and 1 TypeScript file(s)" in result.output
    assert "DataTable" in screen.read_text()

    # With a runner (a stand-in for jscodeshift that renames the identifier).
    stand_in = git_project.parent / "stand_in.py"
    stand_in.write_text(
        "import re, sys\n"
        "for name in [a for a in sys.argv[1:] if not a.startswith('--')]:\n"
        "    text = open(name).read()\n"
        "    open(name, 'w').write(re.sub(r'\\bDataTable\\b', 'ResourceTable', text))\n"
        "    print(f' REP {name} karni-count 2')\n"
    )
    monkeypatch.setenv("KARNI_JSCODESHIFT", f"{sys.executable} {stand_in}")
    result = runner.invoke(app, ["upgrade", "--to", "0.9.0", "--dry-run"])
    assert '+import { ResourceTable } from "@karni/ui";' in result.output
    assert "      frontend/src/screen.tsx: 2" in result.output
    assert "DataTable" in screen.read_text()
