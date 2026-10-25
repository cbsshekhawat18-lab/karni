"""Text edits to a project's pyproject.toml: one requirement string, never a rewrite.

Like :mod:`karni_cli.settings_edit` for settings.py, an edit changes only the
characters it must. :func:`add_extra` finds the one requirement string of a
distribution in ``[project].dependencies``, adds an extra to it in place
(keeping its quotes, version spec, markers and other extras) and leaves every
other byte of the file alone. The file is parsed before and after, and an
edit that would change anything else is refused with :class:`CannotEdit`,
whose message the caller shows next to the manual step.
"""

from __future__ import annotations

import copy
import re
import tomllib
from dataclasses import dataclass
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

__all__ = ["CannotEdit", "ExtraEdit", "add_extra"]

_HEAD = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<space>\s*)(?:\[(?P<extras>[^\]]*)\])?"
)
_PROJECT = re.compile(r"^\[project\][ \t]*(?:#.*)?$", re.MULTILINE)
_NEXT_TABLE = re.compile(r"^[ \t]*\[", re.MULTILINE)


class CannotEdit(Exception):
    """pyproject.toml has no single, plainly written requirement to edit (the message says why)."""


@dataclass(frozen=True)
class ExtraEdit:
    """The edited file and the requirement before and after."""

    text: str
    before: str
    after: str


def _with_extra(requirement: str, extra: str) -> str:
    match = _HEAD.match(requirement)
    if match is None:  # pragma: no cover - Requirement() parsed it, so it has a name
        raise CannotEdit(f"cannot find the name in {requirement!r}")
    end = match.end()
    if match["extras"] is None:
        name_end = match.end("name")
        return f"{requirement[:name_end]}[{extra}]{requirement[name_end:]}"
    inner = match["extras"]
    separator = ", " if ", " in inner else ","
    listed = [item.strip() for item in inner.split(",") if item.strip()]
    head = f"{match['name']}{match['space']}[{separator.join([*listed, extra])}]"
    return head + requirement[end:]


def add_extra(text: str, distribution: str, extra: str) -> ExtraEdit | None:
    """``text`` with ``distribution``'s requirement listing ``extra``; ``None`` when it does.

    :raises CannotEdit: when the file does not parse, ``[project].dependencies``
        is not a plain list, the distribution is listed zero or several times,
        or its string is not written plainly inside the ``[project]`` table.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CannotEdit(f"pyproject.toml does not parse ({exc})") from None
    dependencies = data.get("project", {}).get("dependencies")
    if not isinstance(dependencies, list):
        raise CannotEdit("pyproject.toml has no [project].dependencies list")
    target = canonicalize_name(distribution)
    found: list[tuple[int, Requirement]] = []
    for index, entry in enumerate(dependencies):
        try:
            parsed = Requirement(str(entry))
        except InvalidRequirement:
            continue
        if canonicalize_name(parsed.name) == target:
            found.append((index, parsed))
    if len(found) != 1:
        where = "is not in" if not found else "is listed more than once in"
        raise CannotEdit(f"{distribution} {where} [project].dependencies of pyproject.toml")
    index, parsed = found[0]
    before = str(dependencies[index])
    if canonicalize_name(extra) in {canonicalize_name(name) for name in parsed.extras}:
        return None
    after = _with_extra(before, extra)
    edited = Requirement(after)
    if (
        canonicalize_name(edited.name) != target
        or edited.specifier != parsed.specifier
        or edited.marker != parsed.marker
        or edited.url != parsed.url
        or edited.extras != parsed.extras | {extra}
    ):  # pragma: no cover - _with_extra only inserts the extra
        raise CannotEdit(f"adding [{extra}] to {before!r} would change more than the extras")

    header = _PROJECT.search(text)
    if header is None:
        raise CannotEdit("pyproject.toml has no [project] table header")
    table_end = _NEXT_TABLE.search(text, header.end())
    start, stop = header.end(), table_end.start() if table_end else len(text)
    spots = [
        (match.start(), quote)
        for quote in ('"', "'")
        for match in re.finditer(re.escape(f"{quote}{before}{quote}"), text[start:stop])
    ]
    if len(spots) != 1:
        raise CannotEdit(f"the string {before!r} is not written once, plainly, in [project]")
    offset, quote = spots[0]
    at = start + offset
    result = f"{text[:at]}{quote}{after}{quote}{text[at + len(before) + 2 :]}"

    expected: dict[str, Any] = copy.deepcopy(data)
    expected["project"]["dependencies"][index] = after
    if tomllib.loads(result) != expected:  # pragma: no cover - guards the text splice
        raise CannotEdit("the edit would change more of pyproject.toml than the requirement")
    return ExtraEdit(text=result, before=before, after=after)
