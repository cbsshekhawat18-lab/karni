"""Codemod: Karni's hand-written agent files -> karni.rules.py + generated adapters.

Projects scaffolded before the retrofit carry AGENTS.md (canonical guidance),
CLAUDE.md (``@AGENTS.md``; older projects: the full guidance), .cursorrules
and .claude/commands/*.md. For each one that is recognisably Karni's:

1. module blocks (``<!-- karni:module:<x> -->``) move to ``.karni/modules/<x>.md``;
2. every line the project ADDED to Karni's text becomes an ``ADD`` entry in
   ``karni.rules.py`` (verbatim; grouped per bullet/paragraph; P### codes);
3. every line the project REMOVED from Karni's text is listed as a
   ``# REVIEW:`` comment in karni.rules.py and printed — the codemod cannot
   know whether that meant "disable this rule", so it asks a human;
4. the original is backed up under ``.karni/backup/`` and replaced by the
   generated adapter (``karni rules sync``).

Files that do not look like Karni's are left untouched and reported. Nothing
a user wrote is discarded silently.

Changelog entry ``agent-guidance-files`` (0.2.0); ``CODEMOD`` is what
``karni upgrade`` runs. :func:`migrate_agent_guidance` is the same migration
for direct callers, with its own dry run and printed notes.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import typer

from karni_cli import agent_data
from karni_cli.adapters import MODULES_DIR, backup, is_generated, sync
from karni_cli.upgrades.codemod import Codemod, Outcome, Site
from karni_cli.upgrades.legacy_agent_files import LEGACY_FILES, PROJECT_NAME

RULES_FILE = "karni.rules.py"
#: Line-similarity to a frozen baseline above which a file counts as Karni's.
SIMILARITY = 0.5
_MODULE_BLOCK = re.compile(
    r"<!-- karni:module:(?P<name>[\w-]+) -->\n(?P<body>.*?)\n?<!-- /karni:module:(?P=name) -->\n?",
    re.DOTALL,
)
_H1 = re.compile(r"^# (?P<name>.+?) — agent guidance\s*$")
_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_CODE = re.compile(r"""["']code["']\s*:\s*["']P(\d{3})["']""")
_SIGNATURES = ("This project is built on Karni.", "karni context")


@dataclass
class Migration:
    entries: list[dict[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    modules: dict[str, str] = field(default_factory=dict)
    migrated: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)


def _baselines(rel: str, text: str) -> list[str]:
    """Candidate Karni originals for ``rel`` with the project name filled in."""
    match = _H1.match(text.splitlines()[0]) if text.strip() else None
    name = match.group("name") if match else PROJECT_NAME
    candidates = [LEGACY_FILES[rel]]
    if rel == "CLAUDE.md":  # pre-AGENTS.md projects kept the full guidance in CLAUDE.md
        candidates.append(LEGACY_FILES["AGENTS.md"])
    return [c.replace(PROJECT_NAME, name) for c in candidates]


def _ratio(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def _is_karnis(rel: str, text: str, baseline: str) -> bool:
    if text == baseline:
        return True
    lines, base = text.splitlines(), baseline.splitlines()
    if _ratio(lines, base) >= SIMILARITY:
        return True
    return rel.endswith(".md") and all(sig in text for sig in _SIGNATURES)


def _category(heading: str | None) -> str:
    if not heading:
        return "project"
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return f"project-{slug}" if slug else "project"


def _group(added: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """Fold added lines into entries: one per bullet / numbered item / paragraph.

    A heading the project added becomes the category of what follows it; a
    heading added with nothing under it is kept as an entry of its own.
    """
    entries: list[tuple[str, str | None]] = []
    current: list[str] = []
    section: str | None = None
    headings: list[str] = []

    def flush() -> None:
        if current:
            entries.append((" ".join(current), section))
            current.clear()

    for line, line_section in added:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            flush()
            if stripped.startswith("#"):
                headings.append(stripped.lstrip("#").strip())
            continue
        if line_section != section:
            flush()
            section = line_section
        if _ITEM.match(stripped):
            flush()
            stripped = _ITEM.sub("", stripped, count=1)
        current.append(stripped)
    flush()
    used = {entry_section for _, entry_section in entries}
    entries += [(f"## {h}", h) for h in headings if h not in used]
    return entries


def _diff(text: str, baseline: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """(added lines with their section heading, removed non-blank lines)."""
    ours, base = text.splitlines(), baseline.splitlines()
    added: list[tuple[str, str | None]] = []
    removed: list[str] = []
    headings: list[str | None] = []
    heading: str | None = None
    for line in ours:
        if line.startswith("## "):
            heading = line[3:].strip()
        headings.append(heading)
    matcher = difflib.SequenceMatcher(a=base, b=ours, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += [line for line in base[i1:i2] if line.strip()]
        if tag in ("replace", "insert"):
            added += [(ours[j], headings[j]) for j in range(j1, j2)]
    return added, removed


def plan(project: Path) -> Migration:
    migration = Migration()
    for rel in LEGACY_FILES:
        path = project / rel
        if not path.is_file() or is_generated(path):
            continue
        text = path.read_text(encoding="utf-8")
        for block in _MODULE_BLOCK.finditer(text):
            migration.modules[block.group("name")] = block.group("body").strip() + "\n"
        text = _MODULE_BLOCK.sub("", text)
        baselines = _baselines(rel, text)
        baseline = max(baselines, key=lambda b: _ratio(text.splitlines(), b.splitlines()))
        if not _is_karnis(rel, text, baseline):
            migration.foreign.append(rel)
            continue
        migration.migrated.append(rel)
        added, removed = _diff(text.rstrip("\n") + "\n", baseline)
        prefix = "" if rel in ("AGENTS.md", "CLAUDE.md", ".cursorrules") else f"({rel}) "
        for statement, heading in _group(added):
            migration.entries.append(
                {"rule": prefix + statement, "category": _category(heading), "source": rel}
            )
        migration.removed += [(rel, line) for line in removed]
    return migration


def _next_code(existing: str) -> int:
    used = [int(m) for m in _CODE.findall(existing)]
    return max(used, default=0) + 1


def render_rules_block(migration: Migration, existing: str) -> str:
    start = _next_code(existing)
    lines = []
    if not existing:
        lines += [
            '"""Project agent rules for `karni rules` (read statically, literals only).',
            "",
            "Schema: ADD / OVERRIDE / DISABLE / ADAPTERS. See docs/agents.md.",
            '"""',
            "",
        ]
    lines.append("# Migrated by `karni upgrade` from Karni's old agent files (originals in")
    lines.append("# .karni/backup/). Each entry is text your project added, verbatim.")
    for rel, line in migration.removed:
        lines.append(f"# REVIEW: removed from Karni's guidance in {rel}: {line.strip()}")
    lines.append("ADD += [" if existing else "ADD = [")
    for offset, entry in enumerate(migration.entries):
        lines.append("    {")
        lines.append(f'        "code": "P{start + offset:03d}",')
        lines.append(f'        "category": {json.dumps(entry["category"], ensure_ascii=False)},')
        lines.append(f'        "rule": {json.dumps(entry["rule"], ensure_ascii=False)},')
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines) + "\n"


def _would_change(migration: Migration) -> list[str]:
    changed = list(migration.migrated)
    if migration.entries or migration.removed:
        changed.append(RULES_FILE)
    changed += [(MODULES_DIR / f"{name}.md").as_posix() for name in migration.modules]
    return sorted(set(changed))


def _apply(project: Path, migration: Migration) -> list[str]:
    """Write the migration; returns every file written, backed up or removed."""
    changed = _would_change(migration)
    rules_path = project / RULES_FILE
    existing = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
    if migration.entries or migration.removed:
        block = render_rules_block(migration, existing)
        rules_path.write_text(existing + ("\n" if existing else "") + block, encoding="utf-8")
    for name, body in migration.modules.items():
        target = project / MODULES_DIR / f"{name}.md"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
    for rel in migration.migrated:
        changed.append(backup(project, rel))
        (project / rel).unlink()
    result = sync(project, agent_data.load(project))
    changed += result.written + result.removed
    return sorted(set(changed))


def _notes(migration: Migration) -> list[tuple[str, str]]:
    """``(file, note)`` for everything a person has to look at."""
    notes = [
        (rel, "does not look like Karni's file, so it was left untouched. Review it")
        for rel in migration.foreign
    ]
    notes += [
        (rel, f"REVIEW: you removed {line.strip()!r} (noted in {RULES_FILE})")
        for rel, line in migration.removed
    ]
    return notes


def migrate_agent_guidance(project: Path, dry_run: bool) -> list[str]:
    """Migrate (or, with ``dry_run``, list) the agent files; prints what needs review."""
    migration = plan(project)
    for rel, note in _notes(migration):
        typer.echo(f"   {rel}: {note}")
    if not migration.migrated:
        return []
    if dry_run:
        return _would_change(migration)
    return _apply(project, migration)


class AgentGuidance(Codemod):
    """The ``karni upgrade`` codemod: same migration, notes reported as sites."""

    def apply(self, root: Path) -> Outcome:
        migration = plan(root)
        sites = [Site(rel, 0, note) for rel, note in _notes(migration)]
        if not migration.migrated:
            return Outcome(sites=sites)
        return Outcome(files=dict.fromkeys(_apply(root, migration), 1), sites=sites)


CODEMOD = AgentGuidance()
