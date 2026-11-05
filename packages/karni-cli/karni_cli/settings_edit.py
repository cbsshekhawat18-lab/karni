"""Marker-based edits to a project's config/settings.py.

``karni add`` and ``karni make app`` manage the ``# karni:apps`` block,
``karni make middleware`` the ``# karni:middleware`` block, ``karni add``
the ``# karni:context_processors`` block a module's manifest asks for
(:func:`wire_entries`), and ``karni remove`` takes entries out again
(:func:`remove_entry`, :func:`remove_block`). Two accepted
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
#: The setting and marker of the context processors block a module appends (karni-site's).
PROCESSORS_SETTING = 'TEMPLATES[0]["OPTIONS"]["context_processors"]'
PROCESSORS_MARKER = "# karni:context_processors"

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
        raise CliError(
            f"No `{marker}` marker in {filename}. Add {entry!r} to {setting} manually.",
            code="C108",
        )
    open_idx, marker_idx = found
    if open_idx < 0:
        raise CliError(
            f"Unrecognized `{marker}` block shape in {filename}. Add {entry!r} to {setting} "
            "manually.",
            code="C108",
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
        raise CliError(f"{settings_path} not found.", code="C001")
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


def remove_entry(text: str, entry: str, *, setting: str, marker: str) -> str | None:
    """``text`` without ``entry`` in the marked block; ``None`` when the block does not hold it.

    The reverse of :func:`add_entry`: the entry's own line goes (an entry that
    shares a line keeps the line and loses the entry), and a single-line block
    keeps its shape.
    """
    lines = text.splitlines()
    found = _locate(lines, setting, marker)
    if found is None or found[0] < 0:
        return None
    open_idx, marker_idx = found
    quoted = re.compile(rf"""\s*["']{re.escape(entry)}["']\s*,?""")
    if open_idx == marker_idx:
        single = _single_line(setting).match(lines[marker_idx])
        if single is None:
            return None
        entries = _QUOTED.findall(single.group("body"))
        if entry not in entries:
            return None
        kept = ", ".join(f'"{name}"' for name in entries if name != entry)
        lines[marker_idx] = f"{single.group('head')}[{kept}]  {single.group('tail')}"
        return "\n".join(lines) + "\n"
    for index in range(open_idx + 1, marker_idx):
        line = lines[index]
        if line.strip().startswith("#") or entry not in _QUOTED.findall(line):
            continue
        if _QUOTED.findall(line) == [entry]:
            del lines[index]
        else:
            lines[index] = quoted.sub("", line, count=1)
        return "\n".join(lines) + "\n"
    return None


def remove_block(text: str, setting: str, marker: str) -> str | None:
    """``text`` without the marked block and the ``# ---`` heading above it, once it is empty.

    ``None`` when there is no such block or it still holds an entry. A block
    at the end of the file leaves the file ending where it ended before the
    block was appended.
    """
    lines = text.splitlines()
    found = _locate(lines, setting, marker)
    if found is None or found[0] < 0 or block_entries(text, setting, marker):
        return None
    start, end = found
    if start > 0 and lines[start - 1].startswith("# ---"):
        start -= 1
    before, after = lines[:start], lines[end + 1 :]
    if not "".join(after).strip():
        return "\n".join(before).rstrip("\n") + "\n"
    if before and not before[-1].strip() and after and not after[0].strip():
        after = after[1:]
    return "\n".join(before + after) + "\n"


def processors_block(entry: str, heading: str) -> str:
    """The ``# karni:context_processors`` block, under its ``# ---`` heading, with one entry."""
    return (
        f"{heading}\n"
        f"{PROCESSORS_SETTING} += [  # noqa: F821\n"
        f'    "{entry}",\n'
        f"]  {PROCESSORS_MARKER}\n"
    )


def wire_entries(
    text: str,
    filename: str,
    *,
    middleware: list[tuple[str, str]] | tuple[()] = (),
    processors: list[tuple[str, str]] | tuple[()] = (),
    heading: str = "",
) -> tuple[str, list[str]]:
    """Settings ``text`` with each ``(path, why)`` middleware and context processor wired.

    A middleware goes into the ``# karni:middleware`` block, a context
    processor into the ``# karni:context_processors`` block, which is
    appended once under ``heading`` with ``why`` after it. Each is added only
    when the text does not name it yet. Returns the text and what changed (or
    what to add by hand).
    """
    notes: list[str] = []
    for path, why in middleware:
        if path in text:
            continue
        try:
            updated = add_entry(
                text, path, setting="MIDDLEWARE", marker=MIDDLEWARE_MARKER, filename=filename
            )
        except CliError:
            notes.append(
                f"add {path!r} to MIDDLEWARE in {filename} yourself (no `{MIDDLEWARE_MARKER}` "
                f"block): {why} need it."
            )
            continue
        if updated is not None:
            text = updated
            notes.append(f"{path}: added to MIDDLEWARE ({why})")
    for path, why in processors:
        if path in text:
            continue
        if PROCESSORS_MARKER in text:
            updated = add_entry(
                text, path, setting=PROCESSORS_SETTING, marker=PROCESSORS_MARKER, filename=filename
            )
            text = updated if updated is not None else text
        else:
            text = text.rstrip("\n") + "\n\n" + processors_block(path, f"{heading}: {why} ----")
        notes.append(f"{path}: added to the context processors ({why})")
    return text, notes
