"""TypeScript codemods: jscodeshift, run through the machine's own Node.js.

The CLI ships the transforms (``karni_cli/upgrades/transforms/``) and runs
them with a pinned jscodeshift through ``npx``, so a project needs nothing
installed beyond Node.js itself. Without Node.js, a TypeScript codemod
reports itself skipped (naming how many files need it) instead of failing
the upgrade. Files are pre-filtered in Python, so a project with nothing to
change never needs Node.js at all.

A breaking ``@karni/ui`` change is one line of data in its version module::

    CODEMOD = RenameExport(module="@karni/ui", old="DataTable", new="ResourceTable")

Override / escape hatch: ``KARNI_JSCODESHIFT`` replaces the whole runner
command (e.g. ``"node /path/to/jscodeshift/bin/jscodeshift.js"`` for an
offline machine); subclass :class:`JscodeshiftCodemod` with a new transform
for a change that is not a rename.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from karni_cli.upgrades.codemod import Codemod, Outcome, source_files

__all__ = [
    "JSCODESHIFT_VERSION",
    "JscodeshiftCodemod",
    "RenameExport",
    "jscodeshift_command",
]

#: Pinned so a codemod behaves the same on every machine, every run.
JSCODESHIFT_VERSION: Final = "17.4.0"
TRANSFORMS: Final = Path(__file__).resolve().parent / "transforms"
#: Seconds one jscodeshift run may take (the first npx run also downloads it).
TIMEOUT: Final = 600
SUFFIXES: Final = (".ts", ".tsx", ".mts", ".cts")
_REPORT = re.compile(r"^\s*REP (?P<path>.+) karni-count (?P<count>\d+)\s*$", re.MULTILINE)


def jscodeshift_command() -> list[str] | None:
    """``KARNI_JSCODESHIFT``, else ``npx --yes jscodeshift@<pin>``; None without Node.js."""
    override = os.environ.get("KARNI_JSCODESHIFT", "").strip()
    if override:
        return shlex.split(override)
    npx = shutil.which("npx")
    return [npx, "--yes", f"jscodeshift@{JSCODESHIFT_VERSION}"] if npx else None


class JscodeshiftCodemod(Codemod):
    """A codemod that runs one transform from ``transforms/`` over the TypeScript files."""

    #: File name of the transform under ``karni_cli/upgrades/transforms/``.
    transform: ClassVar[str]

    @abstractmethod
    def needles(self) -> tuple[str, ...]:
        """A file is handed to jscodeshift only when it contains every one of these."""

    @abstractmethod
    def options(self) -> list[str]:
        """Options passed through to the transform (``--name=value``)."""

    def apply(self, root: Path) -> Outcome:
        needles = [needle.encode() for needle in self.needles()]
        candidates = [
            rel
            for rel in source_files(root, SUFFIXES)
            if not rel.endswith(".d.ts") and all(n in (root / rel).read_bytes() for n in needles)
        ]
        if not candidates:
            return Outcome()
        command = jscodeshift_command()
        if command is None:
            return Outcome(
                skipped=f"Node.js (npx) not found, and {len(candidates)} TypeScript file(s) "
                "need this change: install Node.js 18+ and run karni upgrade again, "
                "or make it by hand"
            )
        before = {rel: (root / rel).read_bytes() for rel in candidates}
        counts: dict[str, int] = {}
        groups = (
            ("tsx", [rel for rel in candidates if rel.endswith(".tsx")]),
            ("ts", [rel for rel in candidates if not rel.endswith(".tsx")]),
        )
        for parser, files in groups:
            if not files:
                continue
            argv = [
                *command,
                f"--transform={TRANSFORMS / self.transform}",
                f"--parser={parser}",
                "--extensions=ts,tsx,mts,cts",
                "--no-babel",
                "--run-in-band",
                "--fail-on-error",
                *self.options(),
                *files,
            ]
            try:
                proc = subprocess.run(
                    argv,
                    cwd=root,
                    text=True,
                    capture_output=True,
                    stdin=subprocess.DEVNULL,  # never wait on a prompt
                    timeout=TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                proc = subprocess.CompletedProcess(argv, 124, "", f"timed out after {TIMEOUT}s")
            except OSError as exc:
                proc = subprocess.CompletedProcess(argv, 127, "", str(exc))
            if proc.returncode != 0:
                for rel, content in before.items():  # never leave a half-run behind
                    (root / rel).write_bytes(content)
                detail = (proc.stderr or proc.stdout).strip().splitlines()
                return Outcome(
                    skipped=f"jscodeshift failed (exit {proc.returncode}): "
                    f"{detail[-1] if detail else 'no output'}. Make this change by hand"
                )
            for match in _REPORT.finditer(proc.stdout):
                path = match.group("path").strip()
                counts[path] = counts.get(path, 0) + int(match.group("count"))
        files_changed = {
            rel: counts.get(rel, 1)
            for rel in candidates
            if (root / rel).read_bytes() != before[rel]
        }
        return Outcome(files=files_changed)


@dataclass(frozen=True)
class RenameExport(JscodeshiftCodemod):
    """``import { old } from "module"`` -> ``import { new } from "module"``, plus every use."""

    transform: ClassVar[str] = "rename-export.cjs"

    module: str
    old: str
    new: str

    def needles(self) -> tuple[str, ...]:
        return (self.module, self.old)

    def options(self) -> list[str]:
        return [
            f"--karni-module={self.module}",
            f"--karni-from={self.old}",
            f"--karni-to={self.new}",
        ]
