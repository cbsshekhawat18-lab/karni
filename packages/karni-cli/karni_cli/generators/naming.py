"""Name conversions shared by the generators (no Django import).

``kebab`` and ``pluralize`` mirror :func:`karni.api.routers.kebab` /
:func:`karni.api.routers.pluralize` exactly, so a generated page targets the
route the auto-router actually registers for a model.
"""

from __future__ import annotations

import keyword
import re

from karni_cli.project import CliError

_VOWELS = frozenset("aeiou")
_ES_ENDINGS = ("s", "x", "z", "ch", "sh")
_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b|_|-)|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SNAKE = re.compile(r"^[a-z_][a-z0-9_]*$")
_KEBAB = re.compile(r"^[a-z][a-z0-9-]*$")


def words(name: str) -> list[str]:
    """``"EventType"``, ``"event_type"``, ``"event-type"`` → ``["event", "type"]``."""
    return [w.lower() for w in _WORDS.findall(name)]


def pascal(name: str) -> str:
    """``event_type`` / ``event-type`` / ``eventType`` → ``EventType`` (PascalCase kept)."""
    if re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
        return name
    return "".join(w[:1].upper() + w[1:] for w in words(name))


def snake(name: str) -> str:
    """``EventType`` / ``event-type`` → ``event_type``."""
    if _SNAKE.match(name):
        return name
    return "_".join(words(name))


def kebab(name: str) -> str:
    """``CamelCase`` → ``kebab-case`` (``APIKey`` → ``api-key``) — as karni.api.routers."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", name).lower()


def pluralize(word: str) -> str:
    """Naive English plural used for route prefixes — as karni.api.routers."""
    if word.endswith("y") and len(word) > 1 and word[-2].lower() not in _VOWELS:
        return word[:-1] + "ies"
    if word.endswith(_ES_ENDINGS):
        return word + "es"
    return word + "s"


def default_route(model: str) -> str:
    """The auto-router prefix for a model class name: ``EventType`` → ``event-types``."""
    return pluralize(kebab(model))


def humanize(name: str) -> str:
    """``event_type`` / ``EventType`` → ``Event type``."""
    text = " ".join(words(name))
    return text[:1].upper() + text[1:]


def require_identifier(name: str, what: str) -> str:
    """``name`` when it is a usable Python identifier, else a CliError naming the fix."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise CliError(f"{what} {name!r} is not a valid Python identifier.", code="C103")
    return name


def require_snake(name: str, what: str) -> str:
    if not _SNAKE.match(name) or keyword.iskeyword(name):
        raise CliError(
            f"{what} {name!r} must be snake_case (lowercase letters, digits, underscores), "
            f"e.g. {snake(name) or 'my_name'!r}.",
            code="C103",
        )
    return name


def require_pascal(name: str, what: str) -> str:
    converted = pascal(name)
    if not converted or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", converted):
        raise CliError(
            f"{what} {name!r} must be a class name such as 'Event' or 'EventType'.", code="C103"
        )
    return converted


def require_kebab(name: str, what: str) -> str:
    if not _KEBAB.match(name):
        suggestion = "-".join(words(name)) or "my-page"
        raise CliError(
            f"{what} {name!r} must be kebab-case (lowercase letters, digits, dashes), "
            f"e.g. {suggestion!r}.",
            code="C103",
        )
    return name
