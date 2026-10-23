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
_NAME = re.compile(r"""name\s*=\s*["']([^"']+)["']""")
_INCLUDE = re.compile(r"""include\(\s*["']([^"']+)["']""")


def marker_line(lines: list[str]) -> int | None:
    """The index of the marker line, or ``None``."""
    return next((i for i, line in enumerate(lines) if line.strip() == URLS_MARKER), None)


def has_marker(text: str) -> bool:
    return marker_line(text.splitlines()) is not None


def routes(text: str) -> list[tuple[str, str | None, str | None]]:
    """``(route, name, included module)`` for every ``path("...", ...)`` call in ``text``.

    Read line by line: a call's name and include are looked up between its
    ``path(`` and the next one on the same line.
    """
    found: list[tuple[str, str | None, str | None]] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        matches = list(_PATH_ROUTE.finditer(line))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            segment = line[match.end() : end]
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
    """``text`` with ``entry`` (one ``path(...)`` line, no indent) inserted before the marker.

    Returns ``None`` when the exact line is already present. ``manual`` is
    what to tell the user when the marker is missing.

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
    stripped = entry.strip()
    if any(line.strip() == stripped for line in lines):
        return None
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines.insert(index, indent + stripped)
    return "\n".join(lines) + "\n"
