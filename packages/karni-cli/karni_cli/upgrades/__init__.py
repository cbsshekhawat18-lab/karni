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


#: Registered mechanical migrations, appended below (never edited in place).
UPGRADES: list[Upgrade] = []


def applicable(installed: str) -> list[Upgrade]:
    version = Version(installed)
    matches = [u for u in UPGRADES if version in u.from_spec]
    return sorted(matches, key=lambda u: Version(u.to_version))


def _register() -> None:
    from karni_cli.upgrades.agent_guidance import migrate_agent_guidance

    # Detection-based and idempotent, so it applies to every 0.x project: it
    # only touches agent files that are recognisably Karni's old hand-written ones.
    UPGRADES.append(
        Upgrade(
            from_spec=SpecifierSet(">=0.1.0"),
            to_version="0.1.0",
            description=(
                "agent guidance: AGENTS.md/CLAUDE.md/.cursorrules/.claude/commands -> "
                "karni.rules.py + generated adapters"
            ),
            apply=migrate_agent_guidance,
        )
    )


_register()
