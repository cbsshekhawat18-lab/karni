"""Karni's machine-readable changelog: every breaking change and deprecation, per release.

``karni upgrade`` (karni-cli) reads it to find every change between a
project's Karni version and the target, runs their codemods in order and
reports what it could not fix. ``docs/migrations/<version>.md`` explains each
entry for humans. This package is stdlib only: karni-cli loads it by path
(bundled as ``karni_cli/_changelog``) without importing Django or Karni.

One TOML file per release, named by its version (``0.2.0.toml``). A release
only ever adds its own file; entries are never edited after they ship. Schema::

    version = "0.2.0"                 # must match the file name

    [[change]]
    id = "all-objects"                # unique across every release, kebab-case
    kind = "api-change"               # one of KINDS
    symbol = "Model.all_objects"      # what changed: dotted path, setting, method, file
    replacement = 'Model.objects.without("soft_delete", reason=...)'  # required for renames
    summary = "One or two sentences: what changed and what breaks."
    removed_in = "1.0"                # deprecations only: the release that removes `symbol`
    mechanical = true                 # a codemod rewrites every use safely
    codemod = "v1_0.all_objects_to_without"   # module under karni_cli.upgrades
    migration = "migrations/0.2.md#all_objects"  # migration note, relative to docs/

A change *breaks* at ``removed_in`` when set (a deprecation: the old name
keeps working, with a :class:`karni.deprecation.KarniDeprecationWarning`,
from ``version`` until then), else at ``version`` itself. ``mechanical = true``
requires ``codemod``. A manual change (``mechanical = false``) may still name
one: a detector that reports the code to change without editing it.

Override / escape hatch: :func:`load` takes any directory, so tools and tests
can read another changelog with the same schema and validation.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DOCS_BASE_URL",
    "KINDS",
    "Change",
    "ChangelogError",
    "Release",
    "changes",
    "docs_url",
    "load",
    "version_key",
]

#: Where ``docs/`` is published: ``migration`` values here and ``doc_anchor``
#: values in :func:`karni.deprecation.warn_deprecated` are relative to it.
#: A placeholder until the docs site exists; the one place to change it.
DOCS_BASE_URL: Final[str] = "https://github.com/karni/karni/blob/main/docs/"

#: What a change can be. ``project-files``: files the scaffold generated changed shape.
KINDS: Final = (
    "setting-rename",
    "import-move",
    "base-rename",
    "api-change",
    "behaviour",
    "project-files",
)
#: Kinds whose ``replacement`` is a name a codemod renames ``symbol`` to.
RENAME_KINDS: Final = frozenset({"setting-rename", "import-move", "base-rename"})

DIRECTORY: Final = Path(__file__).resolve().parent

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^\d+(?:\.\d+){0,2}$")
_CODEMOD = re.compile(r"^v\d+_\d+\.[a-z_][a-z0-9_]*$")
_MIGRATION = re.compile(r"^migrations/[\w.-]+\.md#[\w-]+$")
_REQUIRED: Final = ("id", "kind", "symbol", "summary", "mechanical", "migration")
_OPTIONAL: Final = ("replacement", "removed_in", "codemod")


def docs_url(doc_anchor: str) -> str:
    """Absolute docs link for ``doc_anchor`` (``"migrations/0.2.md#section"``)."""
    return DOCS_BASE_URL + doc_anchor.lstrip("/")


class ChangelogError(ValueError):
    """The changelog does not match the schema (the message lists every problem).

    Code ``E704``; a ``ValueError`` so callers that predate the code keep working.
    """

    code = "E704"

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()} See {DOCS_BASE_URL}errors.md#e704"


def version_key(text: str) -> tuple[int, int, int]:
    """``"1.0"`` -> ``(1, 0, 0)``: release versions only (``MAJOR[.MINOR[.PATCH]]``)."""
    if not _VERSION.match(text):
        raise ChangelogError(f"{text!r} is not a release version (MAJOR[.MINOR[.PATCH]])")
    major, minor, patch = ([int(part) for part in text.split(".")] + [0, 0])[:3]
    return major, minor, patch


@dataclass(frozen=True)
class Change:
    """One breaking change or deprecation."""

    id: str
    release: str
    kind: str
    symbol: str
    summary: str
    mechanical: bool
    migration: str
    replacement: str = ""
    removed_in: str = ""
    codemod: str = ""

    @property
    def breaks_in(self) -> str:
        """The release whose code no longer accepts the old form."""
        return self.removed_in or self.release

    @property
    def is_deprecation(self) -> bool:
        return bool(self.removed_in)


@dataclass(frozen=True)
class Release:
    version: str
    changes: tuple[Change, ...]


def _change(raw: Any, release: str, where: str, problems: list[str]) -> Change | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: a [[change]] must be a table")
        return None
    label = f"{where} ({raw.get('id', '?')})"
    missing = [key for key in _REQUIRED if key not in raw]
    unknown = sorted(set(raw) - set(_REQUIRED) - set(_OPTIONAL))
    if missing:
        problems.append(f"{label}: missing {', '.join(missing)}")
    if unknown:
        problems.append(f"{label}: unknown key(s) {', '.join(unknown)}")
    if missing or unknown:
        return None
    for key in (*_REQUIRED, *_OPTIONAL):
        if key in raw and key != "mechanical" and not isinstance(raw[key], str):
            problems.append(f"{label}: {key} must be a string")
            return None
    if not isinstance(raw["mechanical"], bool):
        problems.append(f"{label}: mechanical must be true or false")
        return None
    change = Change(release=release, **raw)
    if not _ID.match(change.id):
        problems.append(f"{label}: id must be kebab-case")
    if change.kind not in KINDS:
        problems.append(f"{label}: kind {change.kind!r} is not one of {', '.join(KINDS)}")
    if not change.summary.strip() or not change.symbol.strip():
        problems.append(f"{label}: symbol and summary must not be empty")
    if change.kind in RENAME_KINDS and not change.replacement:
        problems.append(f"{label}: a {change.kind} needs a replacement")
    if change.removed_in:
        try:
            if version_key(change.removed_in) <= version_key(release):
                problems.append(f"{label}: removed_in must be later than {release}")
        except ChangelogError as exc:
            problems.append(f"{label}: removed_in: {exc}")
    if change.mechanical and not change.codemod:
        problems.append(f"{label}: a mechanical change needs a codemod")
    if change.codemod and not _CODEMOD.match(change.codemod):
        problems.append(f"{label}: codemod must look like 'v1_0.module_name'")
    if not _MIGRATION.match(change.migration):
        problems.append(f"{label}: migration must look like 'migrations/<file>.md#<anchor>'")
    return change


def _release(path: Path, problems: list[str]) -> Release | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"{path.name}: invalid TOML: {exc}")
        return None
    version = data.get("version")
    if version != path.stem:
        problems.append(f"{path.name}: version = {version!r} must match the file name")
        return None
    try:
        version_key(version)
    except ChangelogError as exc:
        problems.append(f"{path.name}: {exc}")
        return None
    unknown = sorted(set(data) - {"version", "change"})
    if unknown:
        problems.append(f"{path.name}: unknown key(s) {', '.join(unknown)}")
    raw_changes = data.get("change", [])
    if not isinstance(raw_changes, list):
        problems.append(f"{path.name}: change must be an array of tables ([[change]])")
        return None
    parsed = [
        _change(raw, version, f"{path.name}[{index}]", problems)
        for index, raw in enumerate(raw_changes)
    ]
    return Release(version, tuple(change for change in parsed if change is not None))


def load(directory: Path | None = None) -> tuple[Release, ...]:
    """Every release in ``directory`` (default: Karni's own), oldest first.

    :raises ChangelogError: listing every schema problem found.
    """
    root = DIRECTORY if directory is None else directory
    problems: list[str] = []
    releases = [
        release
        for path in sorted(root.glob("*.toml"))
        if (release := _release(path, problems)) is not None
    ]
    seen: dict[str, str] = {}
    for release in releases:
        for change in release.changes:
            if change.id in seen:
                problems.append(
                    f"duplicate id {change.id!r} in {seen[change.id]} and {release.version}"
                )
            seen[change.id] = release.version
    if problems:
        raise ChangelogError("invalid changelog:\n  " + "\n  ".join(problems))
    return tuple(sorted(releases, key=lambda release: version_key(release.version)))


def changes(directory: Path | None = None) -> list[Change]:
    """Every change, oldest release first, in file order within a release."""
    return [change for release in load(directory) for change in release.changes]
