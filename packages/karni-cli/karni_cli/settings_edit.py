"""Marker-based edits to a project's config/settings.py.

``karni add`` and ``karni make app`` manage the ``# karni:apps`` block,
``karni make middleware`` the ``# karni:middleware`` block. Two accepted
shapes of a marked block (``SETTING`` is ``INSTALLED_APPS`` / ``MIDDLEWARE``):

    SETTING += [  # noqa: F821
        "existing.entry",
    ]  # karni:<name>

    SETTING += ["existing.entry"]  # karni:<name>

Anything else errors with the manual-edit escape hatch — this code never
guesses at unfamiliar layouts.
"""

from __future__ import annotations

import re
from pathlib import Path

from karni_cli.project import CliError

MARKER = "# karni:apps"
MIDDLEWARE_MARKER = "# karni:middleware"

_QUOTED = re.compile(r"""["']([^"']+)["']""")


def _single_line(setting: str) -> re.Pattern[str]:
    return re.compile(
        rf"^(?P<head>\s*{re.escape(setting)}\s*\+=\s*)\[(?P<body>.*)\]\s*(?P<tail>#.*)$"
    )


def _block_entries(lines: list[str], open_idx: int, close_idx: int) -> list[str]:
    """Quoted entries on non-comment lines inside the block."""
    entries: list[str] = []
    for line in lines[open_idx + 1 : close_idx]:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        entries.extend(_QUOTED.findall(stripped))
    return entries


def _locate(lines: list[str], setting: str, marker: str) -> tuple[int, int] | None:
    """``(open line, marker line)`` of the block (equal for the single-line shape)."""
    marker_idx = next((i for i, line in enumerate(lines) if marker in line), None)
    if marker_idx is None:
        return None
    if _single_line(setting).match(lines[marker_idx]):
        return marker_idx, marker_idx
    if lines[marker_idx].strip().startswith("]"):
        open_idx = next(
            (i for i in range(marker_idx - 1, -1, -1) if setting in lines[i] and "[" in lines[i]),
            None,
        )
        if open_idx is not None:
            return open_idx, marker_idx
    return -1, marker_idx


def block_entries(text: str, setting: str = "INSTALLED_APPS", marker: str = MARKER) -> list[str]:
    """The entries of the marked block in settings ``text`` (``[]`` when absent)."""
    lines = text.splitlines()
    found = _locate(lines, setting, marker)
    if found is None or found[0] < 0:
        return []
    open_idx, marker_idx = found
    if open_idx == marker_idx:
        single = _single_line(setting).match(lines[marker_idx])
        return _QUOTED.findall(single.group("body")) if single else []
    return _block_entries(lines, open_idx, marker_idx)


def add_entry(text: str, entry: str, *, setting: str, marker: str, filename: str) -> str | None:
    """``text`` with ``entry`` inserted into the marked block; ``None`` when already present.

    :raises CliError: when the marker is missing or the block has another shape.
    """
    lines = text.splitlines()
    found = _locate(lines, setting, marker)
    if found is None:
        raise CliError(f"No `{marker}` marker in {filename} — add {entry!r} to {setting} manually.")
    open_idx, marker_idx = found
    if open_idx < 0:
        raise CliError(
            f"Unrecognized `{marker}` block shape in {filename} — add {entry!r} to {setting} "
            "manually."
        )
    if open_idx == marker_idx:
        single = _single_line(setting).match(lines[marker_idx])
        assert single is not None  # _locate matched it
        entries = _QUOTED.findall(single.group("body"))
        if entry in entries:
            return None
        rebuilt = [f"{single.group('head').rstrip()} [  # noqa: F821"]
        rebuilt += [f'    "{existing}",' for existing in entries]
        rebuilt.append(f'    "{entry}",')
        rebuilt.append(f"]  {marker}")
        lines[marker_idx : marker_idx + 1] = rebuilt
    else:
        if entry in _block_entries(lines, open_idx, marker_idx):
            return None
        lines.insert(marker_idx, f'    "{entry}",')
    return "\n".join(lines) + "\n"


def add_app(settings_path: Path, app: str) -> bool:
    """Insert ``app`` into the ``# karni:apps`` block. Returns False when already present."""
    if not settings_path.is_file():
        raise CliError(f"{settings_path} not found.")
    updated = add_entry(
        settings_path.read_text(),
        app,
        setting="INSTALLED_APPS",
        marker=MARKER,
        filename=settings_path.name,
    )
    if updated is None:
        return False
    settings_path.write_text(updated)
    return True
