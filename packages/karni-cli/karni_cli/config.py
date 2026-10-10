"""Karni CLI settings: ``karni config get|set|list``.

Two TOML files, flat ``key = value``:

* project — ``<project>/.karni/config.toml``, committed: applies to the team;
* global  — ``$XDG_CONFIG_HOME/karni/config.toml`` (default ``~/.config``):
  applies to every project on this machine.

The project file wins over the global one, which wins over the default.
Keys are validated against :data:`KEYS`; adding a setting is one entry there.
Unknown keys in a file are ignored (a newer karni may have written them).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

from karni_cli.project import CliError

PROJECT_FILE = Path(".karni") / "config.toml"

_TRUE = frozenset({"true", "yes", "on", "1"})
_FALSE = frozenset({"false", "no", "off", "0"})


@dataclass(frozen=True)
class ConfigKey:
    name: str
    default: bool
    help: str


#: Every setting karni reads. Add a setting here; nothing else needs editing.
KEYS: dict[str, ConfigKey] = {
    key.name: key
    for key in (
        ConfigKey(
            "suggest_tools",
            True,
            "One-time tips about optional tools (karni doctor, karni check outside CI).",
        ),
    )
}


@dataclass(frozen=True)
class Value:
    key: str
    value: bool
    #: "project", "global" or "default".
    source: str
    path: Path | None = None


def global_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "karni" / "config.toml"


def project_path(project: Path) -> Path:
    return project / PROJECT_FILE


def key(name: str) -> ConfigKey:
    found = KEYS.get(name)
    if found is None:
        raise CliError(f"Unknown setting {name!r} (known: {', '.join(sorted(KEYS))}).", code="C007")
    return found


def parse(name: str, raw: str) -> bool:
    key(name)
    text = raw.strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise CliError(f"{name} is a boolean: use true or false, got {raw!r}.", code="C007")


def render(value: bool) -> str:
    return "true" if value else "false"


def read_file(path: Path) -> dict[str, bool]:
    """The known settings in ``path`` (missing file = none); bad values name the file."""
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CliError(f"{path}: not valid TOML ({exc}).", code="C007") from None
    found: dict[str, bool] = {}
    for name in KEYS:
        if name not in data:
            continue
        if not isinstance(data[name], bool):
            raise CliError(
                f"{path}: {name} must be true or false, got {data[name]!r}.", code="C007"
            )
        found[name] = data[name]
    return found


def resolve(name: str, project: Path | None, *, global_only: bool = False) -> Value:
    """The effective value of ``name``: project file, then global file, then default."""
    spec = key(name)
    scopes: list[tuple[str, Path]] = []
    if project is not None and not global_only:
        scopes.append(("project", project_path(project)))
    scopes.append(("global", global_path()))
    for source, path in scopes:
        values = read_file(path)
        if name in values:
            return Value(name, values[name], source, path)
    return Value(name, spec.default, "default")


def write(name: str, value: bool, path: Path) -> None:
    """Set ``name`` in ``path``, keeping the file's other content and comments."""
    key(name)
    try:
        document: Any = (
            tomlkit.parse(path.read_text(encoding="utf-8"))
            if path.is_file()
            else tomlkit.document()
        )
    except Exception as exc:  # noqa: BLE001 - tomlkit raises its own parse errors
        raise CliError(f"{path}: not valid TOML ({exc}).", code="C007") from None
    document[name] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(document), encoding="utf-8")
    except OSError as exc:
        raise CliError(f"Cannot write {path}: {exc}", code="C008") from None
