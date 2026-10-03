"""The codemod contract, and which project files a codemod may touch.

A codemod is one breaking change made mechanical. It runs over a directory
tree (the engine hands it a scratch copy of the project), edits files in
place and returns an :class:`Outcome`: the files it changed with a count of
rewrites each, the :class:`Site` list it could not fix safely, or why it
did not run at all. A *detector* (``edits = False``) never edits: it finds
the code that a manual change has to touch.

Codemods are addressed by id, ``v<major>_<minor>.<name>``: the module
``karni_cli.upgrades.v1_0.all_objects_to_without`` exposes ``CODEMOD``.
The version is the release in which the old form breaks.
"""

from __future__ import annotations

import importlib
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

#: Directories never copied or scanned: VCS data, virtualenvs, installed
#: dependencies, caches, build output, uploaded and collected files.
PRUNE: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "dist-packages",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "dist",
        "build",
        "media",
        "staticfiles",
    }
)
#: Also skipped when looking for source to rewrite: migrations are history
#: (they must keep replaying as written) and .karni/ holds Karni's own files.
SOURCE_PRUNE: frozenset[str] = PRUNE | {"migrations", ".karni"}


def walk(root: Path, prune: frozenset[str] = PRUNE) -> Iterator[Path]:
    """Every regular file under ``root``, skipping ``prune`` and any virtualenv.

    Path-based, like Karni's project-code discovery: what lives under the
    project root is the project's, except dependencies and generated trees.
    Symbolic links are never followed or yielded.
    """
    for directory, dirnames, filenames in os.walk(root):
        here = Path(directory)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in prune
            and not (here / name).is_symlink()
            and not (here / name / "pyvenv.cfg").is_file()
        )
        for name in sorted(filenames):
            path = here / name
            if not path.is_symlink():
                yield path


def source_files(root: Path, suffixes: tuple[str, ...]) -> list[str]:
    """Project-relative POSIX paths of the project's own source files."""
    return [
        path.relative_to(root).as_posix()
        for path in walk(root, SOURCE_PRUNE)
        if path.name.endswith(suffixes)
    ]


@dataclass(frozen=True)
class Site:
    """A place in the project that needs a person."""

    path: str
    line: int
    note: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.note}"


@dataclass
class Outcome:
    #: project-relative path -> number of rewrites in it
    files: dict[str, int] = field(default_factory=dict)
    #: code the codemod found but could not (or must not) rewrite
    sites: list[Site] = field(default_factory=list)
    #: why the codemod did not run (empty when it did)
    skipped: str = ""


class Codemod(ABC):
    """One breaking change, made mechanical (or, with ``edits = False``, findable)."""

    #: False for a detector: it reports sites and never edits.
    edits: ClassVar[bool] = True

    @abstractmethod
    def apply(self, root: Path) -> Outcome:
        """Rewrite the tree under ``root`` in place and say what happened."""


def load_codemod(codemod_id: str) -> Codemod:
    """``"v1_0.all_objects_to_without"`` -> that module's ``CODEMOD``."""
    module = importlib.import_module(f"karni_cli.upgrades.{codemod_id}")
    codemod = getattr(module, "CODEMOD", None)
    if not isinstance(codemod, Codemod):
        raise TypeError(f"karni_cli.upgrades.{codemod_id} must define CODEMOD (a Codemod)")
    return codemod
