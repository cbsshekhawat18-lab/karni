"""Mechanical migration registry for ``karni upgrade`` (E6).

Version N+1 only appends :class:`Upgrade` entries — the machinery never
changes. An entry applies when the installed karni version matches
``from_spec``; entries run in ascending ``to_version`` order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version


@dataclass(frozen=True)
class Upgrade:
    from_spec: SpecifierSet
    to_version: str
    description: str
    #: apply(project_root, dry_run) -> list of changed (or would-change) file paths
    apply: Callable[[Path, bool], list[str]]


#: Registered mechanical migrations. Empty in v0.1 — machinery + tests only.
UPGRADES: list[Upgrade] = []


def applicable(installed: str) -> list[Upgrade]:
    version = Version(installed)
    matches = [u for u in UPGRADES if version in u.from_spec]
    return sorted(matches, key=lambda u: Version(u.to_version))
