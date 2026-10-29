"""Marker-based edits to a project's URLconfs.

``karni make site`` inserts ``path("", include("<app>.urls"))`` at the
``# karni:urls`` marker of config/urls.py, and ``karni make view`` inserts a
route at the same marker inside the site app's urls.py. The marker is a
comment line of its own inside ``urlpatterns``. New entries go right before
it, so the scaffold's ``*welcome_urls()`` stays last:

    urlpatterns = [
        ...,
        # karni:urls
        *welcome_urls(),
    ]

A file without the marker is never guessed at: the caller gets a
:class:`~karni_cli.project.CliError` that names the manual step. ``karni
upgrade`` adds the marker to projects scaffolded before it.
"""

from __future__ import annotations

import re

from karni_cli.project import CliError

URLS_MARKER = "# karni:urls"

_PATH_ROUTE = re.compile(r"""(?<![\w.])path\(\s*(?P<quote>["'])(?P<route>[^"']*)(?P=quote)""")
# `name=`, not `pattern_name=` (a RedirectView's target).
_NAME = re.compile(r"""(?<![\w.])name\s*=\s*["']([^"']+)["']""")
_INCLUDE = re.compile(r"""include\(\s*["']([^"']+)["']""")


def marker_line(lines: list[str], marker: str = URLS_MARKER) -> int | None:
    """The index of the ``marker`` line (``# karni:urls`` by default), or ``None``."""
    return next((i for i, line in enumerate(lines) if line.strip() == marker), None)


def has_marker(text: str) -> bool:
    return marker_line(text.splitlines()) is not None


def _call_end(text: str, start: int) -> int:
    """The offset just past the parenthesis that closes the one open at ``start - 1``."""
    depth, quote, index = 1, "", start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def routes(text: str) -> list[tuple[str, str | None, str | None]]:
    """``(route, name, included module)`` for every ``path("...", ...)`` call in ``text``.

    A call may span lines (``ruff format`` splits a long one): its name and
    include are looked up inside its own parentheses. Comment lines are left out.
    """
    code = "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())
    found: list[tuple[str, str | None, str | None]] = []
    for match in _PATH_ROUTE.finditer(code):
        segment = code[match.end() : _call_end(code, match.start() + match.group(0).index("(") + 1)]
        name = _NAME.search(segment)
        include = _INCLUDE.search(segment)
        found.append(
            (
                match.group("route"),
                name.group(1) if name else None,
                include.group(1) if include else None,
            )
        )
    return found


def add_route(text: str, entry: str, *, filename: str, manual: str) -> str | None:
    """``text`` with ``entry`` (a ``path(...)`` call, no indent) inserted before the marker.

    An entry of several lines (split as ``ruff format`` splits it) keeps its
    own indentation under the marker's. Returns ``None`` when the exact entry
    is already present. ``manual`` is what to tell the user when the marker
    is missing.

    :raises CliError: when the marker is missing.
    """
    lines = text.splitlines()
    index = marker_line(lines)
    if index is None:
        raise CliError(
            f"No `{URLS_MARKER}` marker in {filename} (projects scaffolded before it, or the "
            f"line was removed). {manual}",
            code="C108",
        )
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    if "\n" in entry.strip():
        block = [indent + line if line else line for line in entry.strip("\n").splitlines()]
        if "\n".join(block) in text:
            return None
        lines[index:index] = block
        return "\n".join(lines) + "\n"
    stripped = entry.strip()
    if any(line.strip() == stripped for line in lines):
        return None
    lines.insert(index, indent + stripped)
    return "\n".join(lines) + "\n"
