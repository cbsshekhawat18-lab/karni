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


# -- the plural Django cannot guess (mirrors karni.admin.plurals, which the admin shows) --

_IRREGULAR: dict[str, str] = {
    "person": "people",
    "man": "men",
    "woman": "women",
    "child": "children",
    "foot": "feet",
    "tooth": "teeth",
    "mouse": "mice",
    "goose": "geese",
    "ox": "oxen",
    "datum": "data",
    "criterion": "criteria",
    "phenomenon": "phenomena",
    "analysis": "analyses",
    "basis": "bases",
    "crisis": "crises",
    "diagnosis": "diagnoses",
    "thesis": "theses",
    "axis": "axes",
    "leaf": "leaves",
    "life": "lives",
    "wife": "wives",
    "knife": "knives",
    "shelf": "shelves",
    "half": "halves",
    "wolf": "wolves",
    "thief": "thieves",
    "loaf": "loaves",
    "hero": "heroes",
    "potato": "potatoes",
    "tomato": "tomatoes",
    "echo": "echoes",
    "veto": "vetoes",
}
_UNCOUNTABLE = frozenset(
    {
        "series",
        "species",
        "sheep",
        "fish",
        "news",
        "equipment",
        "information",
        "data",
        "metadata",
        "staff",
        "feedback",
        "software",
        "hardware",
        "advice",
        "research",
        "traffic",
    }
)
_STAYS_SINGULAR = ("ss", "us", "is", "as")


def _plural_word(word: str) -> str:
    lower = word.lower()
    if lower in _UNCOUNTABLE:
        return word
    if lower in _IRREGULAR:
        found = _IRREGULAR[lower]
        return found.capitalize() if word[:1].isupper() else found
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in _VOWELS:
        return word[:-1] + "ies"
    if lower.endswith("s") and not lower.endswith(_STAYS_SINGULAR):
        return word
    if lower.endswith(_ES_ENDINGS):
        return word + "es"
    return word + "s"


def verbose_plural(model: str) -> str | None:
    """The ``verbose_name_plural`` a model needs, or ``None`` when Django's own is right.

    Django's default is the singular name plus an ``s`` (``Category`` becomes
    "categorys"). A model class name such as ``LogEntry`` has the singular
    "log entry", and the plural here is "log entries". The English rules are
    the ones the admin applies (``karni.admin.plurals``), so a written plural
    and the admin's own agree.
    """
    singular = " ".join(words(model))
    head, space, last = singular.rpartition(" ")
    plural = head + space + _plural_word(last) if last else singular
    return plural if plural != f"{singular}s" else None


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
