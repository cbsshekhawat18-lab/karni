"""OpenAPI contract testing: a committed schema snapshot, and responses checked against the schema.

**Snapshot.** One call in the project's suite makes an accidental API break
fail CI::

    # tests/test_api_schema.py (a Karni scaffold ships it)
    from karni.testing import assert_schema_snapshot

    def test_the_api_contract_is_unchanged(db):
        assert_schema_snapshot()

The generated schema (drf-spectacular, exactly what ``/api/schema/`` serves)
is compared with ``tests/openapi.snapshot.json``. A difference fails with the
changes listed — removed and changed paths first (they break clients), then
additions — and how to accept them. A missing snapshot is written and the
test passes, except under CI (``CI`` set), where it fails: a snapshot that
was never committed protects nothing.

Accept an intended change by regenerating, then commit the file::

    KARNI_UPDATE_SNAPSHOTS=1 karni test        # or: pytest --karni-update-snapshots

**Response contract.** :func:`validate` checks a decoded JSON response
against an operation's response schema (``$ref``, ``allOf``/``oneOf``,
``nullable``, ``enum``, types, ``required``, and no undeclared properties);
:func:`karni.testing.assert_crud` uses it for every response it receives.

Override / escape hatches: ``assert_schema_snapshot(path=...)`` for another
file; :func:`generate_schema` takes ``urlconf``; :func:`schema_changes` and
:func:`render_changes` are public for custom reporting.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "SNAPSHOT_ENV",
    "Change",
    "assert_schema_snapshot",
    "default_snapshot_path",
    "find_operation",
    "generate_schema",
    "render_changes",
    "schema_changes",
    "validate",
]

SNAPSHOT_ENV: Final = "KARNI_UPDATE_SNAPSHOTS"
"""Set to ``1`` to rewrite snapshots instead of comparing them."""

#: Set by ``pytest --karni-update-snapshots`` (the ``karni`` plugin).
UPDATE_SNAPSHOTS = False

_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def generate_schema(urlconf: str | None = None, *, cached: bool = False) -> dict[str, Any]:
    """The project's OpenAPI document as plain JSON data (what ``/api/schema/`` serves).

    ``cached=True`` reuses the document within the process for the same
    URLconf and router (the API test helpers validate many responses).
    """
    from django.conf import settings
    from drf_spectacular.generators import SchemaGenerator

    from karni.api.routers import resolve_router

    key = (urlconf or settings.ROOT_URLCONF, id(resolve_router()))
    if cached and key in _CACHE:
        return _CACHE[key]
    schema = SchemaGenerator(urlconf=urlconf).get_schema(request=None, public=True)
    data: dict[str, Any] = json.loads(json.dumps(schema, default=str))
    _CACHE[key] = data
    return data


def _setting_changed(sender: object, setting: str, **kwargs: Any) -> None:
    if setting in {"ROOT_URLCONF", "KARNI_API_ROUTER", "SPECTACULAR_SETTINGS", "REST_FRAMEWORK"}:
        _CACHE.clear()


def _connect() -> None:
    from django.test.signals import setting_changed

    setting_changed.connect(_setting_changed, dispatch_uid="karni.testing.schema.cache")


_connect()


# --- snapshot ---------------------------------------------------------------------------


def default_snapshot_path() -> Path:
    """``<project>/tests/openapi.snapshot.json``."""
    from karni.testing._source import project_root

    return project_root() / "tests" / "openapi.snapshot.json"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in {"", "0", "false", "no", "off"}


def _write(path: Path, schema: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_schema_snapshot(
    path: str | Path | None = None,
    *,
    update: bool | None = None,
    urlconf: str | None = None,
    hint: str = "",
) -> None:
    """Fail when the generated OpenAPI schema differs from the committed snapshot.

    :param path: the snapshot file (default :func:`default_snapshot_path`).
    :param update: rewrite the snapshot instead of comparing; default: the
        ``KARNI_UPDATE_SNAPSHOTS`` env var or ``pytest --karni-update-snapshots``.
    :param hint: an extra line for the failure message (e.g. a copy step).
    :raises AssertionError: listing every change, breaking ones first.
    """
    target = Path(path) if path is not None else default_snapshot_path()
    generated = generate_schema(urlconf)
    if update is None:
        update = UPDATE_SNAPSHOTS or _truthy(os.environ.get(SNAPSHOT_ENV))
    accept = f"{SNAPSHOT_ENV}=1 karni test (or pytest --karni-update-snapshots)"
    if update:
        _write(target, generated)
        return
    if not target.exists():
        if _truthy(os.environ.get("CI")):
            raise AssertionError(
                f"No OpenAPI snapshot at {target}. Generate it locally ({accept}) and commit "
                "it — CI never writes snapshots." + (f"\n{hint}" if hint else "")
            )
        _write(target, generated)
        warnings.warn(
            f"Wrote the OpenAPI snapshot {target} — commit it.", UserWarning, stacklevel=2
        )
        return
    committed = json.loads(target.read_text(encoding="utf-8"))
    if generated == committed:
        return
    changes = schema_changes(committed, generated)
    raise AssertionError(
        f"The OpenAPI schema differs from {target}:\n{render_changes(changes)}\n"
        f"If the change is intended, accept it with {accept} and commit the file."
        + (f"\n{hint}" if hint else "")
    )


@dataclass(frozen=True)
class Change:
    """One difference between two schema documents."""

    kind: str  # "removed" | "changed" | "added"
    path: tuple[str | int, ...]
    old: Any = None
    new: Any = None

    @property
    def breaking(self) -> bool:
        """Removals and changes break clients; additions do not."""
        return self.kind != "added"

    def render(self) -> str:
        where = _pointer(self.path)
        if self.kind == "changed":
            return f"  ~ changed  {where}: {_short(self.old)} -> {_short(self.new)}"
        sign = "-" if self.kind == "removed" else "+"
        return f"  {sign} {self.kind:<8} {where}"


def _pointer(path: tuple[str | int, ...]) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        elif _IDENTIFIER.match(part):
            out += f".{part}" if out else part
        else:
            out += f"[{json.dumps(part)}]"
    return out or "(root)"


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "..."


def schema_changes(old: Any, new: Any, path: tuple[str | int, ...] = ()) -> list[Change]:
    """Every difference between ``old`` and ``new``, breaking ones first."""
    found = list(_walk(old, new, path))
    return sorted(found, key=lambda change: (not change.breaking, _pointer(change.path)))


def _walk(old: Any, new: Any, path: tuple[str | int, ...]) -> Iterator[Change]:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() - new.keys():
            yield Change("removed", (*path, key), old=old[key])
        for key in new.keys() - old.keys():
            yield Change("added", (*path, key), new=new[key])
        for key in old.keys() & new.keys():
            yield from _walk(old[key], new[key], (*path, key))
    elif isinstance(old, list) and isinstance(new, list) and _scalars(old) and _scalars(new):
        for item in old:
            if item not in new:
                yield Change("removed", (*path, json.dumps(item)), old=item)
        for item in new:
            if item not in old:
                yield Change("added", (*path, json.dumps(item)), new=item)
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (left, right) in enumerate(zip(old, new, strict=True)):
            yield from _walk(left, right, (*path, index))
    elif old != new:
        yield Change("changed", path, old=old, new=new)


def _scalars(items: list[Any]) -> bool:
    return all(not isinstance(item, dict | list) for item in items)


def render_changes(changes: list[Change], *, limit: int = 40) -> str:
    """The changes as lines (at most ``limit``), with a breaking/additive count."""
    breaking = sum(change.breaking for change in changes)
    lines = [f"{breaking} breaking, {len(changes) - breaking} additive"]
    lines += [change.render() for change in changes[:limit]]
    if len(changes) > limit:
        lines.append(f"  ... and {len(changes) - limit} more")
    return "\n".join(lines)


# --- response contract ------------------------------------------------------------------


def find_operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any] | None:
    """The operation serving ``method path`` (``/api/events/<id>/`` matches ``{id}``)."""
    for template, item in schema.get("paths", {}).items():
        pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template))
        if re.fullmatch(pattern, path):
            operation = item.get(method.lower())
            if operation is not None:
                return dict(operation)
    return None


def response_schema(operation: dict[str, Any], status: int) -> dict[str, Any] | None:
    """The JSON schema documented for ``status`` (``None`` when undocumented or bodiless)."""
    response = operation.get("responses", {}).get(str(status))
    if not isinstance(response, dict):
        return None
    content = response.get("content", {})
    media = content.get("application/json") or next(iter(content.values()), None)
    if not isinstance(media, dict):
        return None
    found = media.get("schema")
    return found if isinstance(found, dict) else None


def _resolve(schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    seen = 0
    while "$ref" in schema and seen < 32:
        ref = str(schema["$ref"])
        node: Any = document
        for part in ref.removeprefix("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        merged = dict(node)
        merged.update({k: v for k, v in schema.items() if k != "$ref"})
        schema = merged
        seen += 1
    return schema


_TYPES: Final = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate(
    instance: Any, schema: dict[str, Any], document: dict[str, Any], path: str = "$"
) -> list[str]:
    """Problems with ``instance`` against ``schema`` (``$ref`` resolved in ``document``).

    Strict about the contract: an object whose schema lists ``properties``
    may not carry an undeclared key (unless ``additionalProperties`` allows
    it) — a field the schema does not document is drift.
    """
    schema = _resolve(schema, document)
    if instance is None and (schema.get("nullable") or None in schema.get("enum", ())):
        return []
    for keyword in ("oneOf", "anyOf"):
        options = schema.get(keyword)
        if options:
            failures = [validate(instance, option, document, path) for option in options]
            if all(failures):
                return [f"{path}: matches none of the {keyword} options ({failures[0][0]})"]
    errors: list[str] = []
    for part in schema.get("allOf", ()):
        errors += validate(instance, part, document, path)
    if errors:
        return errors
    if instance is None:
        if schema.get("type") or schema.get("properties") or schema.get("enum"):
            return [f"{path}: null, but the schema is not nullable"]
        return []
    if "enum" in schema and instance not in schema["enum"]:
        return [f"{path}: {instance!r} is not one of {schema['enum']!r}"]
    kind = schema.get("type")
    expected = _TYPES.get(str(kind)) if kind else None
    if expected is not None:
        wrong_bool = isinstance(instance, bool) and kind in {"integer", "number"}
        if wrong_bool or not isinstance(instance, expected):
            return [f"{path}: expected {kind}, got {type(instance).__name__} {_short(instance)}"]
    if isinstance(instance, dict) and (kind == "object" or "properties" in schema):
        properties = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in instance:
                errors.append(f"{path}.{name}: required by the schema but missing")
        extra = schema.get("additionalProperties")
        for name, value in instance.items():
            if name in properties:
                errors += validate(value, properties[name], document, f"{path}.{name}")
            elif isinstance(extra, dict):
                errors += validate(value, extra, document, f"{path}.{name}")
            elif properties and extra is not True:
                errors.append(f"{path}.{name}: not declared in the schema")
    if isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(instance):
            errors += validate(item, schema["items"], document, f"{path}[{index}]")
    return errors
