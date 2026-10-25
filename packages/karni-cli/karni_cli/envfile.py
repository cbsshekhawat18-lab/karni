"""A project's ``.env`` as the project reads it, for commands that never import it.

The project loads ``.env`` with ``karni.dotenv.load_dotenv`` (django-environ's
``read_env``), so this module follows the same rules: ``KEY=VALUE`` lines with
an optional ``export``, one pair of single or double quotes stripped, the last
line for a key wins, and a variable already set in the environment wins over
the file. ``KARNI_DOTENV=false`` (or 0, no, off) skips the file, as it does
for the project.

``karni serve`` reads ``KARNI_DEV_PORT`` and ``KARNI_API_PROXY`` here, and
``karni doctor`` reads ``DATABASE_URL``, ``REDIS_URL`` and ``PROJECT_NAME``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Value", "lookup", "read"]

_LINE = re.compile(r"\A(?:export )?([A-Za-z_0-9]+)=(.*)\Z")
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class Value:
    """A variable's value and where it came from: ``"environment"`` or ``".env"``."""

    text: str
    origin: str


def read(project: Path) -> dict[str, str]:
    """The variables ``<project>/.env`` sets (``{}`` without one or with KARNI_DOTENV=false)."""
    if os.environ.get("KARNI_DOTENV", "").strip().lower() in _FALSE:
        return {}
    try:
        content = (project / ".env").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    found: dict[str, str] = {}
    for line in content.splitlines():
        match = _LINE.match(line)
        if match is None:
            continue
        key, value = match.groups()
        single = re.match(r"\A'(.*)'\Z", value)
        if single:
            value = single.group(1)
        double = re.match(r'\A"(.*)"\Z', value)
        if double:
            value = re.sub(r"\\(.)", r"\1", double.group(1))
        found[key] = value
    return found


def lookup(project: Path, name: str, file: dict[str, str] | None = None) -> Value | None:
    """``name`` from the environment, else from the project's ``.env``; ``None`` when unset.

    Pass ``file`` (from :func:`read`) to look up several names with one read.
    """
    if name in os.environ:
        return Value(os.environ[name], "environment")
    values = read(project) if file is None else file
    if name in values:
        return Value(values[name], ".env")
    return None
