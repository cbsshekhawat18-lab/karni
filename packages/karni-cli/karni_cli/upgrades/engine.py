"""Run the selected changes' codemods: all or nothing, with a diff and a report.

Every codemod runs, in order, over a scratch copy of the project (the
project's own files, without .git, virtualenvs, node_modules, caches or
build output; ``.venv`` is linked in so project-interpreter lookups still
work). Then the copy is compared with the project:

* ``dry_run``: the unified diff is returned and the project is untouched;
* otherwise every changed, added or removed file is written back, and only
  after every codemod succeeded. A failing codemod leaves the project as it
  was.

Each change lands in the report as *applied* (files and rewrite counts),
*manual* (sites a person must change, plus every manual change, with its
migration note) and/or *skipped* (nothing to change, or could not run).
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from karni_cli.project import CliError
from karni_cli.upgrades import changelog as changelog_mod
from karni_cli.upgrades.codemod import Codemod, Outcome, Site, load_codemod, walk

if TYPE_CHECKING:
    from karni.changelog import Change

#: Files larger than this are not copied: no codemod rewrites them.
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class FileChange:
    path: str
    before: bytes | None  # None: the codemods created it
    after: bytes | None  # None: the codemods removed it


@dataclass
class Report:
    current: str
    target: str
    dry_run: bool
    applied: list[tuple[Change, Outcome]] = field(default_factory=list)
    manual: list[tuple[Change, list[Site]]] = field(default_factory=list)
    skipped: list[tuple[Change, str]] = field(default_factory=list)
    changes: list[FileChange] = field(default_factory=list)

    @property
    def diff(self) -> str:
        return unified_diff(self.changes)


# the scratch copy


def _copy(project: Path, scratch: Path) -> set[str]:
    """Copy the project's files into ``scratch``; returns their relative paths."""
    copied: set[str] = set()
    for path in walk(project):
        if path.stat().st_size > MAX_BYTES:
            continue
        rel = path.relative_to(project).as_posix()
        target = scratch / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.add(rel)
    venv = project / ".venv"
    if venv.is_dir():
        os.symlink(venv, scratch / ".venv", target_is_directory=True)
    return copied


def _compare(project: Path, scratch: Path, copied: set[str]) -> list[FileChange]:
    found: list[FileChange] = []
    for rel in sorted(copied):
        before = (project / rel).read_bytes()
        result = scratch / rel
        after = result.read_bytes() if result.is_file() else None
        if after != before:
            found.append(FileChange(rel, before, after))
    for path in walk(scratch):
        rel = path.relative_to(scratch).as_posix()
        if rel not in copied:
            found.append(FileChange(rel, None, path.read_bytes()))
    return sorted(found, key=lambda change: change.path)


def _write_back(project: Path, scratch: Path, changes: Sequence[FileChange]) -> None:
    for change in changes:
        target = project / change.path
        if change.after is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scratch / change.path, target)


def unified_diff(changes: Sequence[FileChange]) -> str:
    """``git diff``-style text for ``changes`` (new files from /dev/null, removals to it)."""
    chunks: list[str] = []
    for change in changes:
        old_name = f"a/{change.path}" if change.before is not None else "/dev/null"
        new_name = f"b/{change.path}" if change.after is not None else "/dev/null"
        try:
            old = (change.before or b"").decode("utf-8")
            new = (change.after or b"").decode("utf-8")
        except UnicodeDecodeError:
            chunks.append(f"Binary files {old_name} and {new_name} differ\n")
            continue
        lines = list(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=old_name,
                tofile=new_name,
            )
        )
        chunks.append(
            "".join(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                for line in lines
            )
        )
    return "".join(chunks)


# running


def _record(report: Report, change: Change, codemod: Codemod, outcome: Outcome) -> None:
    if outcome.skipped:
        report.skipped.append((change, outcome.skipped))
    if outcome.files:
        report.applied.append((change, outcome))
    if outcome.sites:
        report.manual.append((change, outcome.sites))
    elif not outcome.files and not outcome.skipped:
        report.skipped.append((change, "nothing to change" if codemod.edits else "no uses found"))


def run(
    project: Path,
    changes: Sequence[Change],
    *,
    current: str,
    target: str,
    dry_run: bool,
    resolve: Callable[[str], Codemod] = load_codemod,
) -> Report:
    """Apply ``changes`` (already selected and ordered) to ``project``."""
    report = Report(current=current, target=target, dry_run=dry_run)
    with tempfile.TemporaryDirectory(prefix="karni-upgrade-") as tmp:
        scratch = Path(tmp) / project.name
        scratch.mkdir()
        copied = _copy(project, scratch)
        for change in changes:
            if not change.codemod:
                report.manual.append((change, []))
                continue
            codemod = resolve(change.codemod)
            try:
                outcome = codemod.apply(scratch)
            except Exception as exc:
                raise CliError(
                    f"codemod {change.codemod} ({change.id}) failed: {exc!r}. "
                    "Nothing was written; please report this with the file it stopped on.",
                    code="C199",
                ) from exc
            _record(report, change, codemod, outcome)
        report.changes = _compare(project, scratch, copied)
        if not dry_run:
            _write_back(project, scratch, report.changes)
    return report


# the report


def _title(change: Change) -> str:
    arrow = f" -> {change.replacement}" if change.replacement else ""
    return f"{change.id}: {change.symbol}{arrow}"


def render(report: Report) -> str:
    """The human report: applied, could not fix automatically, skipped, next steps."""
    verb = "Would apply" if report.dry_run else "Applied"
    lines: list[str] = []
    if report.applied:
        lines.append(f"{verb} automatically:")
        for change, outcome in report.applied:
            lines.append(f"  {_title(change)}  [{change.codemod}]")
            lines += [f"      {path}: {count}" for path, count in sorted(outcome.files.items())]
    if report.manual:
        lines.append("Could not fix automatically (needs you):")
        for change, sites in report.manual:
            lines.append(f"  {_title(change)}")
            if not sites:
                lines.append(f"      {change.summary}")
            lines += [f"      {site.render()}" for site in sites]
            lines.append(f"      see {changelog_mod.docs_url(change.migration)}")
    if report.skipped:
        lines.append("Skipped:")
        lines += [f"  {change.id}: {reason}" for change, reason in report.skipped]
    files = len(report.changes)
    if report.dry_run:
        lines.append(f"Dry run: {files} file(s) would change; nothing was written.")
    else:
        lines.append(f"{files} file(s) changed.")
        lines.append(
            f"Next: review `git diff`, pin karni to {report.target} and reinstall, make the "
            "changes listed above, run your formatter (rewrites keep your style but do not "
            "re-wrap long lines), then `karni check` and your tests with "
            "-W error::karni.deprecation.KarniDeprecationWarning."
        )
    return "\n".join(lines)
