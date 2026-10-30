"""Experimental. The module catalog as the CLI sees it: every module and built-in feature.

Where the manifests come from (see :mod:`karni.catalog` for the format):

1. **Karni's features**: ``karni/catalog/features/*.toml``, read from the
   monorepo source or from the copy bundled into this wheel
   (``karni_cli/_catalog``). The parser itself, ``karni.catalog``, is loaded
   by path the same way (stdlib only, no Django).
2. **Karni's modules**: each ``modules/karni-<x>/karni_<x>/karni.module.toml``
   of the monorepo, or the copies bundled under ``karni_cli/_catalog/modules``.
   This is how ``karni modules list`` shows a module that is not installed.
3. **Installed modules**: the ``karni.modules`` entry points of the project's
   interpreter (``python -m karni.catalog``), which win over a bundled copy
   because they are what the project runs, then those of the CLI's own
   environment for names nothing else knows.

A module is **added** when its app is in the ``# karni:apps`` block of
config/settings.py (read statically), and **installed** when the project's
interpreter has its entry point.

Override / escape hatch: a third-party module joins the catalog by shipping a
manifest and a ``karni.modules`` entry point. A module without one is still
added with ``karni add <name>`` by convention.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from karni_cli.project import CliError, compose_service_running, venv_python
from karni_cli.settings_edit import block_entries

if TYPE_CHECKING:
    from karni.catalog import Manifest

__all__ = ["Catalog", "added_apps", "core", "load", "parse_text"]

_MODULE_NAME = "karni_cli._bundled_karni_catalog"
_QUERY = ["-m", "karni.catalog"]


def _source_root() -> Path | None:
    """The monorepo checkout this CLI runs from, if any."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "karni" / "karni" / "catalog" / "__init__.py").is_file():
            return parent
    return None


def _core_dir() -> Path | None:
    root = _source_root()
    if root is not None:
        return root / "packages" / "karni" / "karni" / "catalog"
    packaged = resources.files("karni_cli") / "_catalog"
    with resources.as_file(packaged) as path:
        if (path / "__init__.py").is_file():
            return path
    return None


def core() -> ModuleType:
    """``karni.catalog`` loaded by path under a private name (no Django, no project)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    directory = _core_dir()
    if directory is None:
        raise CliError(
            "This karni-cli has no module catalog: neither the monorepo source nor a bundled "
            "karni_cli/_catalog. Reinstall karni-cli.",
            code="C314",
        )
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, directory / "__init__.py")
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        raise CliError("The module catalog cannot be loaded.", code="C314")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[_MODULE_NAME]
        raise
    return module


def parse_text(text: str, source: str) -> Manifest:
    """A manifest's TOML text as a :class:`~karni.catalog.Manifest`, or ``C314``."""
    catalog = core()
    try:
        manifest: Manifest = catalog.parse_text(text, source)
    except catalog.ManifestError as exc:
        raise CliError(f"The manifest {exc}", code="C314") from None
    return manifest


def _bundled_module_files() -> list[Path]:
    root = _source_root()
    if root is not None:
        return sorted(root.glob("modules/*/karni_*/karni.module.toml"))
    directory = _core_dir()
    return sorted((directory / "modules").glob("*.toml")) if directory else []


@lru_cache(maxsize=1)
def _bundled() -> tuple[tuple[Manifest, ...], tuple[str, ...]]:
    """Karni's features and modules, and the problems of any manifest that does not parse."""
    catalog = core()
    found: list[Manifest] = []
    problems: list[str] = []
    try:
        found += catalog.features()
    except catalog.ManifestError as exc:
        problems.append(str(exc))
    for path in _bundled_module_files():
        try:
            found.append(catalog.parse_text(path.read_text(encoding="utf-8"), str(path)))
        except catalog.ManifestError as exc:
            problems.append(str(exc))
    return tuple(found), tuple(problems)


def _here() -> tuple[list[Manifest], list[str]]:
    """The modules installed in the CLI's own environment."""
    catalog = core()
    try:
        texts = catalog.installed_texts()
    except catalog.ManifestError as exc:
        return [], [str(exc)]
    return _parsed(texts.items())


def _parsed(items: Iterable[tuple[str, tuple[str, str]]]) -> tuple[list[Manifest], list[str]]:
    catalog = core()
    found: list[Manifest] = []
    problems: list[str] = []
    for name, (source, text) in items:
        try:
            manifest = catalog.parse_text(text, source)
        except catalog.ManifestError as exc:
            problems.append(str(exc))
            continue
        if manifest.kind != "module" or manifest.name != name:
            problems.append(f"{source}: the entry point {name!r} names {manifest.name!r}")
            continue
        found.append(manifest)
    return found, problems


def project_installed(project: Path) -> tuple[list[Manifest], list[str]] | None:
    """The modules installed in the project's interpreter (``None``: no interpreter, or a
    karni without the catalog)."""
    python = venv_python(project)
    if python is not None:
        command = [str(python), *_QUERY]
    elif compose_service_running(project, "django"):
        command = ["docker", "compose", "exec", "-T", "django", "python", *_QUERY]
    else:
        return None
    try:
        proc = subprocess.run(
            command,
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 2:
        return [], [proc.stderr.strip()]
    if proc.returncode != 0:
        return None
    try:
        data: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    items = [
        (str(name), (str(entry["source"]), str(entry["text"])))
        for name, entry in data.items()
        if isinstance(entry, dict) and "text" in entry
    ]
    return _parsed(items)


def added_apps(project: Path) -> list[str]:
    """The entries of the project's ``# karni:apps`` block (``[]`` without one)."""
    settings = project / "config" / "settings.py"
    try:
        return block_entries(settings.read_text(encoding="utf-8"))
    except (OSError, CliError):
        return []


@dataclass
class Catalog:
    """Experimental. Every module and feature the CLI knows, with each module's state."""

    entries: dict[str, Manifest]
    #: Names of the modules whose app is in the ``# karni:apps`` block.
    added: set[str] = field(default_factory=set)
    #: Names of the modules the project's interpreter has (``None``: not asked).
    installed: set[str] | None = None
    #: Manifests that could not be read, each with its source.
    problems: list[str] = field(default_factory=list)

    def get(self, name: str) -> Manifest | None:
        return self.entries.get(name) or self.entries.get(name.replace("-", "_"))

    @property
    def modules(self) -> list[Manifest]:
        return [m for m in self.entries.values() if m.kind == "module"]

    @property
    def features(self) -> list[Manifest]:
        return [m for m in self.entries.values() if m.kind == "feature"]

    def state(self, manifest: Manifest) -> str:
        """``added``, ``installed`` or ``available`` for a module, ``built in`` for a feature."""
        if manifest.kind == "feature":
            return "built in"
        if manifest.name in self.added:
            return "added"
        if self.installed is not None and manifest.name in self.installed:
            return "installed"
        return "available"

    def requiring(self, name: str, among: Iterable[str]) -> list[str]:
        """The names in ``among`` whose manifest requires ``name``."""
        return sorted(
            other
            for other in among
            if (found := self.entries.get(other)) is not None and name in found.requires
        )


def load(project: Path | None = None, *, ask_project: bool = True) -> Catalog:
    """Experimental. The catalog, with the project's state when ``project`` is given.

    ``ask_project`` runs ``python -m karni.catalog`` in the project's
    interpreter for the modules installed there. Without it, only the
    bundled manifests and the CLI's own environment count.
    """
    bundled, bundled_problems = _bundled()
    entries: dict[str, Manifest] = {m.name: m for m in bundled}
    problems = list(bundled_problems)
    installed: set[str] | None = None
    if project is not None and ask_project:
        answer = project_installed(project)
        if answer is not None:
            found, more = answer
            problems += more
            installed = {m.name for m in found}
            entries |= {m.name: m for m in found if entries.get(m.name, m).kind == "module"}
    here, more = _here()
    problems += more
    for manifest in here:
        entries.setdefault(manifest.name, manifest)
    problems += core().check_catalog(list(entries.values()))
    catalog = Catalog(dict(sorted(entries.items())), installed=installed, problems=problems)
    if project is not None:
        apps = set(added_apps(project))
        catalog.added = {m.name for m in catalog.modules if m.app in apps}
    return catalog
