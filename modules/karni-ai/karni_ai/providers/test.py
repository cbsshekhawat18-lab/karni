"""A deterministic provider for tests, CI and local work: no network, no key, no model.

Without a queued answer it reads the source the way a person would read a
form: ``field: value`` lines, one record per paragraph (records are separated
by a blank line), where ``field`` is a property of the schema's rows (by name,
or by its title or description, case and spaces aside). A value for an array
property is split on commas, a value for an integer, number or boolean
property is converted, and anything else stays text. Lines that name no
property are ignored, so a source with none gives no rows.

Tests steer it with class-level state, reset by :meth:`TestProvider.reset`:

* :meth:`TestProvider.answer_with` queues the next answers verbatim (any JSON,
  to test what the extraction does with a wrong one);
* :meth:`TestProvider.fail_with` queues a :class:`ProviderError` instead;
* :attr:`TestProvider.calls` records every :class:`StructuredRequest`.

Tokens are counted as one per four characters, rounded up: the instructions,
the source and the schema as input, the answer's JSON as output.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, ClassVar

from karni_ai.exceptions import ProviderError
from karni_ai.providers.base import Provider, StructuredAnswer, StructuredRequest, Usage

__all__ = ["TestProvider"]

_LINE = re.compile(r"^\s*(?P<key>[^:\n]{1,80}?)\s*:\s*(?P<value>.*?)\s*$")


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", text).lower()


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def _row_schema(schema: dict[str, Any]) -> dict[str, Any]:
    rows = schema.get("properties", {}).get("rows", {})
    items = rows.get("items") if isinstance(rows, dict) else None
    return items if isinstance(items, dict) else {}


def _types(part: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    kind = part.get("type")
    if isinstance(kind, str):
        found.add(kind)
    for option in part.get("anyOf") or ():
        if isinstance(option, dict):
            found |= _types(option)
    return found


def _convert(value: str, part: dict[str, Any]) -> Any:
    types = _types(part)
    if "array" in types:
        return [item.strip() for item in value.split(",") if item.strip()]
    if "boolean" in types and value.lower() in {"yes", "no", "true", "false"}:
        return value.lower() in {"yes", "true"}
    if "integer" in types and re.fullmatch(r"-?\d+", value):
        return int(value)
    if "number" in types and re.fullmatch(r"-?\d+(\.\d+)?", value):
        return float(value)
    return value


class TestProvider(Provider):
    """Experimental. Answers from the source's ``field: value`` lines, or from a queue."""

    __test__ = False  # not a pytest test class

    name: ClassVar[str] = "test"

    #: Every request this provider answered, in order.
    calls: ClassVar[list[StructuredRequest]] = []
    _queue: ClassVar[list[Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls._queue = []

    @classmethod
    def answer_with(cls, *answers: Any) -> None:
        """Queue answers returned verbatim by the next calls, one per call."""
        cls._queue.extend(answers)

    @classmethod
    def fail_with(cls, error: ProviderError) -> None:
        """Queue an error the next call raises."""
        cls._queue.append(error)

    def model(self) -> str:
        return "test"

    def structured(self, request: StructuredRequest) -> StructuredAnswer:
        type(self).calls.append(request)
        input_tokens = _tokens(
            request.instructions + request.source + json.dumps(request.schema, sort_keys=True)
        )
        if type(self)._queue:
            queued = type(self)._queue.pop(0)
            if isinstance(queued, ProviderError):
                raise queued
            data = queued
        else:
            data = {"rows": self.read(request.source, _row_schema(request.schema))}
        raw = json.dumps(data, sort_keys=True)
        return StructuredAnswer(
            data=data, usage=Usage(input_tokens, _tokens(raw)), model="test", raw=raw
        )

    def read(self, source: str, row: dict[str, Any]) -> list[dict[str, Any]]:
        """The records of ``source``: one per paragraph of ``field: value`` lines."""
        properties = row.get("properties") or {}
        names: dict[str, str] = {}
        for name, part in properties.items():
            names.setdefault(_norm(name), name)
            for label in (part.get("title"), part.get("description")):
                if isinstance(label, str) and label:
                    names.setdefault(_norm(label), name)
        records: list[dict[str, Any]] = []
        for paragraph in re.split(r"\n\s*\n", source):
            record: dict[str, Any] = {}
            for line in paragraph.splitlines():
                match = _LINE.match(line)
                if match is None:
                    continue
                name = names.get(_norm(match.group("key")))
                if name is None or name in record or not match.group("value"):
                    continue
                record[name] = _convert(match.group("value"), properties[name])
            if record:
                records.append(record)
        return records
