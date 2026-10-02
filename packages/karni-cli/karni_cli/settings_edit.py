"""Marker-based edits to a project's config/settings.py for ``karni add`` (E5).

Two accepted shapes of the ``# karni:apps`` block:

    INSTALLED_APPS += [  # noqa: F821
        "existing_app",
    ]  # karni:apps

    INSTALLED_APPS += ["existing_app"]  # karni:apps

Anything else errors with the manual-edit escape hatch — this code never
guesses at unfamiliar layouts.
"""

from __future__ import annotations

import re
from pathlib import Path

from karni_cli.project import CliError

MARKER = "# karni:apps"
_SINGLE_LINE = re.compile(r"^(?P<head>\s*INSTALLED_APPS\s*\+=\s*)\[(?P<body>.*)\]\s*(?P<tail>#.*)$")


def _block_entries(lines: list[str], open_idx: int, close_idx: int) -> list[str]:
    """Quoted app names on non-comment lines inside the block."""
    entries: list[str] = []
    for line in lines[open_idx + 1 : close_idx]:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        entries.extend(re.findall(r"""["']([^"']+)["']""", stripped))
    return entries


def add_app(settings_path: Path, app: str) -> bool:
    """Insert ``app`` into the marked block. Returns False when already present."""
    if not settings_path.is_file():
        raise CliError(f"{settings_path} not found.")
    text = settings_path.read_text()
    lines = text.splitlines()

    marker_idx = next((i for i, line in enumerate(lines) if MARKER in line), None)
    if marker_idx is None:
        raise CliError(
            f"No `{MARKER}` marker in {settings_path.name} — add the app to "
            "INSTALLED_APPS manually."
        )

    marker_line = lines[marker_idx]
    single = _SINGLE_LINE.match(marker_line)
    if single and MARKER in (single.group("tail") or ""):
        entries = re.findall(r"""["']([^"']+)["']""", single.group("body"))
        if app in entries:
            return False
        rebuilt = [f"{single.group('head').rstrip()} [  # noqa: F821"]
        rebuilt += [f'    "{entry}",' for entry in entries]
        rebuilt.append(f'    "{app}",')
        rebuilt.append(f"]  {MARKER}")
        lines[marker_idx : marker_idx + 1] = rebuilt
    elif marker_line.strip().startswith("]"):
        open_idx = next(
            (
                i
                for i in range(marker_idx - 1, -1, -1)
                if "INSTALLED_APPS" in lines[i] and "[" in lines[i]
            ),
            None,
        )
        if open_idx is None:
            raise CliError(
                f"Malformed `{MARKER}` block in {settings_path.name} — add the app manually."
            )
        if app in _block_entries(lines, open_idx, marker_idx):
            return False
        lines.insert(marker_idx, f'    "{app}",')
    else:
        raise CliError(
            f"Unrecognized `{MARKER}` block shape in {settings_path.name} — add the app manually."
        )

    settings_path.write_text("\n".join(lines) + "\n")
    return True
