"""Experimental. ``.karni/build.json``: what ``karni build`` owns, and how a hand edit is found.

The record is committed with the project. It holds a sha256 of every
Karni-owned file and block as ``karni build`` last wrote it, the entities
and pages Karni manages, and the files the project adopted::

    {
      "version": 1,
      "spec": "<sha256 of the spec's normal form>",
      "entities": ["classes.Session", "classes.Studio"],
      "pages": ["classes.Session:detail", "classes.Session:list"],
      "files": {"classes/karni/models.py": "<sha256>", ...},
      "blocks": {"config/settings.py": "<sha256>", ...},
      "adopted": ["classes/karni/api.py"]
    }

Before it writes anything, ``karni build`` compares every recorded hash
with the file on disk. A Karni-owned file whose content differs was edited
by hand (:func:`hand_edits`), and the build stops with ``C273``. Nothing in
the record depends on the time or the machine, so a build that changes
nothing writes nothing.

What a build still has to run when it stopped early (migrate, seed, tests)
is machine-local, like the database it concerns: it lives in
``.karni/local/state.json`` (:mod:`karni_cli.local_state`) under ``build``.

Override / escape hatch: ``karni build --adopt <file>`` hands a Karni-owned
file (or block) to the project, and the record says so from then on.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli import local_state
from karni_cli.builder import layout
from karni_cli.project import CliError
from karni_cli.spec.plan import Managed

__all__ = [
    "RECORD_VERSION",
    "HandEdit",
    "Record",
    "digest",
    "hand_edit",
    "load",
    "pending",
    "save_pending",
]

#: Experimental. The version of ``.karni/build.json``. It moves only for a breaking change.
RECORD_VERSION: Final = 1
#: The most diff lines a hand edit shows.
_DIFF_LINES: Final = 12


def digest(text: str) -> str:
    """Experimental. The sha256 ``karni build`` records for a file or a block."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Record:
    """Experimental. ``.karni/build.json`` (see the module docstring)."""

    spec: str = ""
    entities: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    blocks: dict[str, str] = field(default_factory=dict)
    adopted: list[str] = field(default_factory=list)

    @property
    def owned(self) -> dict[str, str]:
        """Every recorded file and block, by its name in the record."""
        return {**self.files, **self.blocks}

    def managed(self) -> Managed:
        """What the plan needs to mark each change managed or not."""
        return Managed(frozenset(self.entities), frozenset(self.pages), frozenset(self.adopted))

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": RECORD_VERSION,
            "spec": self.spec,
            "entities": sorted(self.entities),
            "pages": sorted(self.pages),
            "files": dict(sorted(self.files.items())),
            "blocks": dict(sorted(self.blocks.items())),
            "adopted": sorted(self.adopted),
        }

    def text(self) -> str:
        return json.dumps(self.as_dict(), indent=2) + "\n"


def load(root: Path) -> Record:
    """Experimental. The project's record, or an empty one when there is none."""
    path = root / layout.RECORD
    if not path.is_file():
        return Record()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(
            f"{layout.RECORD} cannot be read ({exc}). Restore it from version control, or "
            "delete it: karni build then treats every Karni-owned file as new and stops on "
            "each one that exists (C273).",
            code="C285",
        ) from None
    version = data.get("version") if isinstance(data, dict) else None
    if version != RECORD_VERSION:
        raise CliError(
            f"{layout.RECORD} has version {version!r}, and this karni-cli reads version "
            f"{RECORD_VERSION}. Upgrade karni-cli (pip install -U karni-cli).",
            code="C285",
        )

    def strings(key: str) -> list[str]:
        value = data.get(key) or []
        return [str(item) for item in value] if isinstance(value, list) else []

    def hashes(key: str) -> dict[str, str]:
        value = data.get(key) or {}
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    return Record(
        spec=str(data.get("spec") or ""),
        entities=strings("entities"),
        pages=strings("pages"),
        files=hashes("files"),
        blocks=hashes("blocks"),
        adopted=strings("adopted"),
    )


@dataclass(frozen=True)
class HandEdit:
    """Experimental. A Karni-owned file or block whose content is not what karni build wrote."""

    #: The file (or block, ``config/settings.py``) as the record names it.
    name: str
    #: The 1-based lines of the file on disk that differ (empty: the file is new to the record).
    lines: tuple[int, ...]
    #: A short unified diff: what karni build writes (-) against the file (+).
    diff: tuple[str, ...]
    #: Whether the file was never written by karni build (it exists, but the record lacks it).
    unrecorded: bool = False

    def shown_lines(self) -> str:
        if not self.lines:
            return "the whole file"
        spans: list[str] = []
        start = previous = self.lines[0]
        for number in [*self.lines[1:], 0]:
            if number == previous + 1:
                previous = number
                continue
            spans.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = number
        return f"line{'s' if len(self.lines) > 1 else ''} {', '.join(spans)}"


def hand_edit(name: str, on_disk: str, expected: str, *, unrecorded: bool = False) -> HandEdit:
    """Experimental. The :class:`HandEdit` of ``on_disk``, against what karni build writes now."""
    a, b = expected.splitlines(), on_disk.splitlines()
    lines: list[int] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            lines += range(j1 + 1, j2 + 1)
        elif tag == "delete" and j1 + 1 not in lines:
            lines.append(min(j1 + 1, max(len(b), 1)))
    diff = [
        line.rstrip("\n")
        for line in difflib.unified_diff(a, b, lineterm="", n=0)
        if not line.startswith(("---", "+++", "@@"))
    ]
    if len(diff) > _DIFF_LINES:
        diff = [*diff[:_DIFF_LINES], f"... {len(diff) - _DIFF_LINES} more"]
    return HandEdit(name, tuple(sorted(set(lines))), tuple(diff), unrecorded)


# the machine-local part: what a build that stopped early still has to run


def pending(root: Path) -> dict[str, Any]:
    """Experimental. The steps a build that stopped early still has to run (empty: none)."""
    found = local_state.read_state(root).get("build")
    return dict(found) if isinstance(found, dict) else {}


def save_pending(root: Path, state: dict[str, Any] | None) -> None:
    """Experimental. Remember (or, with ``None``, forget) the steps still to run."""
    data = local_state.read_state(root)
    if state:
        data["build"] = state
    elif "build" in data:
        data.pop("build")
    else:
        return
    local_state.write_state(root, data)
