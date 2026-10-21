"""Where things are defined, and how values read: ``karni why``'s ``file:line`` and display.

Every location comes from :mod:`inspect` on the live object (the viewset
class, the predicate class, a ``Where`` function, a veto), so it points at the
code that runs. Paths are shown relative to the project root when the file
lives there, else relative to the installed package (``karni/api/access.py``).
Row values are rendered the way the audit log stores them, with the audit
log's redaction (:func:`karni.audit.capture.sensitive_fields`).
"""

from __future__ import annotations

import inspect
import re
import sys
from collections.abc import Callable, Iterator
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q
from django.db.models.constants import LOOKUP_SEP

__all__ = [
    "Location",
    "attribute_location",
    "callable_location",
    "class_location",
    "display_user",
    "display_value",
    "q_paths",
    "q_text",
    "row_value",
    "settings_location",
]

#: Lookups a ``Q`` key may end with; the rest of the key is the field path.
_LOOKUPS = frozenset(
    {
        "exact",
        "iexact",
        "in",
        "isnull",
        "gt",
        "gte",
        "lt",
        "lte",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "range",
        "regex",
        "iregex",
        "date",
        "year",
        "month",
        "day",
    }
)
_LOOKUP_TEXT = {
    "exact": "=",
    "iexact": "= (any case)",
    "in": "in",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "contains": "contains",
    "icontains": "contains (any case)",
}


class Location:
    """``path:line`` of a definition, with the absolute file kept for tools."""

    __slots__ = ("file", "line")

    def __init__(self, file: str, line: int) -> None:
        self.file = file
        self.line = line

    def __str__(self) -> str:
        return f"{_short(self.file)}:{self.line}"

    def as_dict(self) -> dict[str, Any]:
        return {"file": _short(self.file), "line": self.line, "path": self.file}


@lru_cache(maxsize=1)
def _roots() -> tuple[Path, ...]:
    """Project root first, then the directories packages are installed in."""
    from karni.testing._source import project_root

    found: list[Path] = [project_root()]
    for entry in sys.path:
        if entry and Path(entry).is_dir():
            found.append(Path(entry).resolve())
    return tuple(found)


def _short(file: str) -> str:
    path = Path(file).resolve()
    for root in _roots():
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if ".venv" in relative.parts or "site-packages" in relative.parts:
            continue  # an installed package under the project: shorten by sys.path
        return relative.as_posix()
    return path.as_posix()


#: inspect parses a whole module to find a class: once per class is plenty.
_CLASS_LOCATIONS: dict[type[Any], Location | None] = {}
_ATTRIBUTE_LOCATIONS: dict[tuple[type[Any], str], Location | None] = {}


def class_location(cls: type[Any]) -> Location | None:
    """Where ``cls`` is defined, or ``None`` (built in a shell, generated)."""
    if cls not in _CLASS_LOCATIONS:
        _CLASS_LOCATIONS[cls] = _class_location(cls)
    return _CLASS_LOCATIONS[cls]


def _class_location(cls: type[Any]) -> Location | None:
    try:
        file = inspect.getsourcefile(cls)
        _lines, line = inspect.getsourcelines(cls)
    except (OSError, TypeError):
        return None
    return Location(file, line) if file else None


def callable_location(fn: Callable[..., Any]) -> Location | None:
    """Where a function (a ``Where`` lambda, a veto) is defined."""
    target = inspect.unwrap(fn)
    code = getattr(target, "__code__", None)
    if code is None:
        call = vars(type(target)).get("__call__")
        code = getattr(call, "__code__", None)
    if code is None:
        return None
    return Location(code.co_filename, code.co_firstlineno)


def attribute_location(cls: type[Any], name: str) -> Location | None:
    """The line assigning ``name`` in the class body that defines it (``access = ...``).

    Walks the MRO to the class whose ``__dict__`` holds ``name`` and scans
    its source for ``name =`` (or ``name:``) at the body's indentation.
    """
    key = (cls, name)
    if key not in _ATTRIBUTE_LOCATIONS:
        _ATTRIBUTE_LOCATIONS[key] = _attribute_location(cls, name)
    return _ATTRIBUTE_LOCATIONS[key]


def _attribute_location(cls: type[Any], name: str) -> Location | None:
    owner = next((klass for klass in cls.__mro__ if name in vars(klass)), None)
    if owner is None:
        return None
    try:
        file = inspect.getsourcefile(owner)
        lines, start = inspect.getsourcelines(owner)
    except (OSError, TypeError):
        return None
    if not file:
        return None
    pattern = re.compile(rf"^\s+{re.escape(name)}\s*(?::[^=]*)?=")
    for offset, text in enumerate(lines):
        if pattern.match(text):
            return Location(file, start + offset)
    return Location(file, start)


def settings_location(name: str, needle: str | None = None) -> Location | None:
    """The line of the settings module that assigns ``name`` (or mentions ``needle`` within it).

    ``settings_location("KARNI_ROLES", '"organizer"')`` finds the role's
    entry. ``None`` when the setting is not assigned in the settings file
    (Karni's default applies).
    """
    module = sys.modules.get(getattr(settings, "SETTINGS_MODULE", "") or "")
    file = getattr(module, "__file__", None)
    if not file:
        return None
    try:
        lines = Path(file).read_text().splitlines()
    except OSError:
        return None
    start = next(
        (i for i, text in enumerate(lines) if re.match(rf"^{re.escape(name)}\b.*=", text)), None
    )
    if start is None:
        return None
    if needle:
        for offset, text in enumerate(lines[start:], start=start):
            if offset > start and re.match(r"^\S", text):
                break  # left the assignment
            if needle in text:
                return Location(file, offset + 1)
    return Location(file, start + 1)


# values


def display_user(user: Any) -> str:
    """``organizer@example.com`` (the username field), else ``str(user)``; ``anonymous``."""
    if user is None or not getattr(user, "is_authenticated", False):
        return "anonymous"
    field = getattr(type(user), "USERNAME_FIELD", None) or "pk"
    value = getattr(user, field, None)
    return str(value) if value not in (None, "") else str(user)


def _is_user(value: Any) -> bool:
    from django.contrib.auth import get_user_model

    return isinstance(value, get_user_model())


def display_value(value: Any, *, you: Any = None) -> str:
    """A value as ``karni why`` prints it: users by login, rows by ``str()``, the rest repr."""
    if isinstance(value, Model):
        if you is not None and _is_user(value) and value.pk == getattr(you, "pk", object()):
            return f"{display_user(value)} (you)"
        if _is_user(value):
            return display_user(value)
        return f"{value} ({type(value).__name__} {value.pk})"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(display_value(item, you=you) for item in value) + "]"
    if value is None:
        return "None"
    if isinstance(value, bool | int | float):
        return repr(value)
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, str):
        return repr(str(value))
    return str(value)


def split_lookup(key: str) -> tuple[str, str]:
    """``("event__organizer", "exact")`` from ``"event__organizer"`` (default lookup: exact)."""
    parts = key.split(LOOKUP_SEP)
    if len(parts) > 1 and parts[-1] in _LOOKUPS:
        return LOOKUP_SEP.join(parts[:-1]), parts[-1]
    return key, "exact"


def q_paths(rows: Any) -> list[str]:
    """Every field path a row filter reads, in order (``[]`` for ``True``/``False``)."""
    if not isinstance(rows, Q):
        return []
    found: list[str] = []
    for key in _q_keys(rows):
        path = split_lookup(key)[0]
        if path not in found:
            found.append(path)
    return found


def _q_keys(node: Q) -> Iterator[str]:
    for child in node.children:
        if isinstance(child, Q):
            yield from _q_keys(child)
        elif isinstance(child, tuple):
            yield str(child[0])


def q_text(rows: Any, *, you: Any = None) -> str:
    """A row filter in words: ``organizer = you``, ``status = 'published'``, ``every row``."""
    if rows is True:
        return "every row"
    if rows is False:
        return "no row"
    if not isinstance(rows, Q):
        return str(rows)
    parts: list[str] = []
    for child in rows.children:
        if isinstance(child, Q):
            text = q_text(child, you=you)
            parts.append(f"({text})" if len(child.children) > 1 else text)
        elif isinstance(child, tuple):
            path, lookup = split_lookup(str(child[0]))
            value = child[1]
            if lookup == "isnull":
                parts.append(f"{path} is {'null' if value else 'set'}")
                continue
            shown = "you" if _is_you(value, you) else display_value(value, you=you)
            parts.append(f"{path} {_LOOKUP_TEXT.get(lookup, lookup)} {shown}")
        else:
            parts.append(str(child))
    joined = f" {rows.connector} ".join(parts) if parts else "every row"
    return f"NOT ({joined})" if rows.negated else joined


def _is_you(value: Any, you: Any) -> bool:
    if you is None or not getattr(you, "is_authenticated", False):
        return False
    if isinstance(value, Model):
        return _is_user(value) and value.pk == you.pk
    return False


def row_value(row: Model, path: str, *, you: Any = None) -> str:
    """``row.<path>`` through relations, redacted like the audit log (``Karni.sensitive``)."""
    from karni.audit import REDACTED
    from karni.audit.capture import sensitive_fields

    current: list[Any] = [row]
    model: type[Model] = type(row)
    segments = path.split(LOOKUP_SEP)
    for index, segment in enumerate(segments):
        name = model._meta.pk.name if segment == "pk" else segment
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            return f"<no field {segment!r} on {model.__name__}>"
        if name in sensitive_fields(model):
            return str(REDACTED)
        last = index == len(segments) - 1
        values: list[Any] = []
        for item in current:
            if item is None:
                values.append(None)
                continue
            if field.many_to_many or field.one_to_many:
                manager = getattr(item, field.get_accessor_name() if field.auto_created else name)
                values.extend(manager.all())
            else:
                values.append(getattr(item, name, None))
        current = values
        target = getattr(field, "related_model", None)
        if target is not None and not last:
            model = target
    if len(current) == 1 and not _to_many(type(row), path):
        return display_value(current[0], you=you)
    return display_value(current, you=you)


def _to_many(model: type[Model], path: str) -> bool:
    for segment in path.split(LOOKUP_SEP):
        try:
            field = model._meta.get_field(model._meta.pk.name if segment == "pk" else segment)
        except FieldDoesNotExist:
            return False
        if field.many_to_many or field.one_to_many:
            return True
        target = getattr(field, "related_model", None)
        if target is None:
            return False
        model = target
    return False
