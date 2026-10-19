"""Shared plumbing for the architecture rules.

Project-code discovery is PATH-based (never a label denylist): an app is
project code when its module file lives under ``settings.BASE_DIR`` and not
under site-packages. ``KARNI_ARCHITECTURE["skip_apps"]`` only narrows further.
Installed packages — Karni itself, third-party apps, Karni modules — are
never scanned; modules must pass these rules in their own CI.
"""

from __future__ import annotations

import fnmatch
import inspect
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.apps import AppConfig, apps
from django.conf import settings

#: Default configuration; projects override keys via settings.KARNI_ARCHITECTURE.
DEFAULTS: dict[str, Any] = {
    "skip_apps": [],
    "sql_allowed": ["*/sql/*", "*/migrations/*"],
    "http_allowed": ["*/services/*", "*/providers/*", "*/tests/*", "conftest.py"],
    "dup": {"min_statements": 8, "exclude": ["*/migrations/*"]},
}

_ALLOW_RE = re.compile(r"#\s*karni:\s*allow\(([^)]+)\)\s*:\s*(.*)$")


@dataclass(frozen=True)
class Violation:
    rule: str
    location: str  # "path/to/file.py:lineno" or a dotted name
    message: str
    hint: str = ""

    def render(self) -> str:
        hint = f" ({self.hint})" if self.hint else ""
        return f"[{self.rule}] {self.location}: {self.message}{hint}"


def config(key: str) -> Any:
    """KARNI_ARCHITECTURE[key] with DEFAULTS fallback (works without karni.conf)."""
    merged = dict(DEFAULTS)
    merged.update(getattr(settings, "KARNI_ARCHITECTURE", {}) or {})
    return merged[key]


def _site_packages_roots() -> tuple[str, ...]:
    roots = set()
    for path in sys.path:
        if "site-packages" in path or "dist-packages" in path:
            roots.add(str(Path(path).resolve()))
    return tuple(roots)


def project_root() -> Path:
    """``settings.BASE_DIR``, else the directory above the settings package, else the cwd.

    A Karni scaffold keeps its settings in ``<project>/config/settings.py``,
    so the fallback finds the project even when ``BASE_DIR`` is not defined.
    """
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir is not None:
        return Path(base_dir).resolve()
    module = sys.modules.get(getattr(settings, "SETTINGS_MODULE", "") or "")
    file = getattr(module, "__file__", None)
    if file:
        return Path(file).resolve().parent.parent
    return Path.cwd().resolve()


def project_app_configs(*, infer_root: bool = True) -> list[AppConfig]:
    """Installed apps whose code lives in the project tree (see module docstring).

    The tree is ``BASE_DIR`` when the settings define it, else
    :func:`project_root`'s fallback (the parent of the settings package — a
    Karni scaffold defines no ``BASE_DIR``), so every rule scans the project
    by default. ``infer_root=False`` keeps the strict ``BASE_DIR``-only
    behaviour and returns nothing without it.
    """
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir is None and infer_root:
        base_dir = project_root()
    if base_dir is None:
        return []
    base = str(Path(base_dir).resolve())
    site = _site_packages_roots()
    skip = set(config("skip_apps"))
    found: list[AppConfig] = []
    for cfg in apps.get_app_configs():
        if cfg.label in skip:
            continue
        # Framework apps are never project code, even in editable monorepo
        # installs where karni's own path sits under the repo root.
        if cfg.name == "karni" or cfg.name.startswith("karni."):
            continue
        path = str(Path(cfg.path).resolve())
        if path.startswith(base) and not any(path.startswith(root) for root in site):
            found.append(cfg)
    return found


def matches_any(path: Path, globs: list[str]) -> bool:
    """fnmatch (``*`` crosses ``/``) over the posix-relative path AND basename."""
    posix = path.as_posix()
    return any(fnmatch.fnmatch(posix, g) or fnmatch.fnmatch(path.name, g) for g in globs)


def project_sources(cfg: AppConfig) -> list[Path]:
    return sorted(Path(cfg.path).rglob("*.py"))


def relative(path: Path) -> str:
    base = getattr(settings, "BASE_DIR", None)
    try:
        return str(path.resolve().relative_to(Path(base).resolve())) if base else str(path)
    except ValueError:
        return str(path)


@lru_cache(maxsize=512)
def _file_lines(path: str) -> tuple[str, ...]:
    try:
        return tuple(Path(path).read_text().splitlines())
    except OSError:
        return ()


@dataclass(frozen=True)
class Allow:
    rules: tuple[str, ...]
    reason: str
    line: int


def allows_in(path: Path) -> dict[int, Allow]:
    """Every ``# karni: allow(...)`` marker in the file, keyed by 1-based line."""
    found: dict[int, Allow] = {}
    for i, text in enumerate(_file_lines(str(path)), start=1):
        m = _ALLOW_RE.search(text)
        if m:
            rules = tuple(r.strip() for r in m.group(1).split(",") if r.strip())
            found[i] = Allow(rules=rules, reason=m.group(2).strip(), line=i)
    return found


def find_allow(path: Path, rule: str, lines: list[int]) -> Allow | None:
    """A marker for ``rule`` on any of the candidate physical lines.

    Callers pass the offending line plus, for class rules, the line above the
    class-def and the line above the first decorator (amendment F5).
    """
    markers = allows_in(path)
    for line in lines:
        allow = markers.get(line)
        if allow and rule in allow.rules:
            return allow
    return None


def check_optout(path: Path, rule: str, lines: list[int], violation: Violation) -> list[Violation]:
    """Apply opt-out semantics: valid marker → []; reason-less marker → both
    the opt-out-reason violation AND the underlying one (F5)."""
    allow = find_allow(path, rule, lines)
    if allow is None:
        return [violation]
    if allow.reason:
        return []
    return [
        Violation(
            rule="opt-out-reason",
            location=f"{relative(path)}:{allow.line}",
            message=f"karni: allow({rule}) requires a non-empty reason",
        ),
        violation,
    ]


def class_marker_lines(cls: type) -> tuple[Path, list[int]] | None:
    """Candidate marker lines for a class: def line, line above it, line above
    the first decorator. None when source is unretrievable (generated classes
    are skipped, never crashed on)."""
    try:
        file = inspect.getsourcefile(cls)
        source, def_line = inspect.getsourcelines(cls)
    except (OSError, TypeError):
        return None
    if file is None:
        return None
    first = def_line
    for offset, text in enumerate(source):
        if text.lstrip().startswith("class "):
            first = def_line + offset
            break
    # def_line is the first decorator when decorated; cover all three spots.
    return Path(file), sorted({first, first - 1, def_line, def_line - 1})
