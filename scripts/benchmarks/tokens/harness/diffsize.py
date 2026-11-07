"""The size of what a run changed in its project, from git.

The start of a run is one commit, whose hash is recorded. Afterwards everything the agent
(and the tools it ran) left that differs from that commit is counted, whether the agent
committed it or left it in the working tree (git ignores aside): lines added plus lines deleted.
Two figures: ``all`` counts every file, ``code`` leaves out lockfiles, ``node_modules``,
migrations, build output and caches.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LOCKFILES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Pipfile.lock"}
)
SKIPPED_DIRS = frozenset(
    {"node_modules", "migrations", "dist", "build", "__pycache__", ".venv", ".git"}
)


@dataclass(frozen=True)
class DiffSize:
    lines_all: int
    lines_code: int
    files_all: int
    files_code: int


def is_code(path: str) -> bool:
    """False for lockfiles and for anything under node_modules, migrations, dist and the like."""
    parts = PurePosixPath(path).parts
    if parts[-1] in LOCKFILES:
        return False
    return not any(part in SKIPPED_DIRS for part in parts[:-1])


def parse_numstat(text: str) -> DiffSize:
    """Parse ``git diff --numstat`` (binary files, shown as ``-``, count as zero lines)."""
    lines_all = lines_code = files_all = files_code = 0
    for row in text.splitlines():
        fields = row.split("\t", 2)
        if len(fields) != 3:
            continue
        added, deleted, path = fields
        if " => " in path:  # a rename: the new name decides
            path = path.split(" => ")[-1].rstrip("}")
        size = (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
        lines_all += size
        files_all += 1
        if is_code(path):
            lines_code += size
            files_code += 1
    return DiffSize(lines_all, lines_code, files_all, files_code)


def _git(project: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def commit_start(project: Path) -> str:
    """Make ``project`` a new git repository with one commit. Returns the commit hash."""
    _git(project, "init", "-q", "-b", "main")
    _git(project, "add", "-A")
    _git(
        project,
        "-c", "user.name=bench",
        "-c", "user.email=bench@example.com",
        "commit", "-q", "--allow-empty", "-m", "start",
    )  # fmt: skip
    return _git(project, "rev-parse", "HEAD").strip()


def measure(project: Path, base: str) -> DiffSize:
    """Lines changed since ``base``, new files included, ignored files left out."""
    _git(project, "add", "-A")
    return parse_numstat(_git(project, "diff", "--cached", "--numstat", base))
