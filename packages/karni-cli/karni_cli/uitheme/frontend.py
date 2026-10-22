"""The frontend ``karni ui detect`` reads: where it is, its packages, its files and aliases."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from karni_cli.project import CliError, find_project

#: Directories never scanned for theme files.
SKIP_DIRS = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".output",
        ".turbo",
        ".vite",
        ".cache",
        "coverage",
        "storybook-static",
        "public",
        ".git",
    }
)
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
#: Files larger than this are not theme definitions (bundles, fixtures).
MAX_SCAN_BYTES = 512_000
ENTRY_NAMES = ("main", "index", "entry-client", "client")


def load_jsonc(text: str) -> Any:
    """JSON with comments and trailing commas (tsconfig.json)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i : end + 1])
            i = end + 1
            continue
        if text.startswith("//", i):
            newline = text.find("\n", i)
            i = len(text) if newline == -1 else newline
            continue
        if text.startswith("/*", i):
            close = text.find("*/", i + 2)
            i = len(text) if close == -1 else close + 2
            continue
        out.append(char)
        i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


@dataclass
class Frontend:
    root: Path
    package: dict[str, Any] = field(default_factory=dict)

    def rel(self, path: Path) -> str:
        """``path`` relative to the frontend root (POSIX), or absolute when outside it."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    @cached_property
    def dependencies(self) -> dict[str, str]:
        deps: dict[str, str] = {}
        for key in ("devDependencies", "peerDependencies", "dependencies"):
            section = self.package.get(key)
            if isinstance(section, dict):
                deps.update({str(k): str(v) for k, v in section.items()})
        return deps

    def has_dependency(self, name: str) -> bool:
        return name in self.dependencies or (self.root / "node_modules" / name).is_dir()

    def installed_version(self, name: str) -> str | None:
        manifest = self.root / "node_modules" / name / "package.json"
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            return None
        return str(version) if version else None

    def major_version(self, name: str) -> int | None:
        """The installed major version, else the one package.json asks for."""
        for version in (self.installed_version(name), self.dependencies.get(name)):
            if version:
                match = re.search(r"(\d+)", version)
                if match:
                    return int(match.group(1))
        return None

    def files(self, suffixes: tuple[str, ...]) -> Iterator[Path]:
        """Project files with these suffixes, skipping dependencies and build output."""
        yield from self._walk(self.root, suffixes)

    def _walk(self, directory: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                yield from self._walk(entry, suffixes)
            elif entry.suffix in suffixes and entry.is_file():
                try:
                    if entry.stat().st_size > MAX_SCAN_BYTES:
                        continue
                except OSError:
                    continue
                yield entry

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    @cached_property
    def stylesheets(self) -> list[Path]:
        return list(self.files((".css",)))

    def main_stylesheet(self) -> Path | None:
        """The stylesheet that loads Tailwind (``@import "tailwindcss"`` / ``@tailwind base``)."""
        candidates: list[Path] = []
        for sheet in self.stylesheets:
            text = self.read(sheet)
            if re.search(r"""@import\s+["']tailwindcss["']|@tailwind\s+base""", text):
                candidates.append(sheet)
        if not candidates:
            for name in ("index.css", "main.css", "app.css", "globals.css", "styles.css"):
                for base in (self.root / "src", self.root / "app", self.root):
                    if (base / name).is_file():
                        return base / name
            return None
        # Prefer src/, then the shortest path.
        return min(candidates, key=lambda p: (not self.rel(p).startswith("src/"), len(p.parts)))

    def entry_files(self) -> list[Path]:
        """The app's entry modules (src/main.tsx, ...), most likely first."""
        found: list[Path] = []
        for base in (self.root / "src", self.root):
            for name in ENTRY_NAMES:
                for suffix in (".tsx", ".ts", ".jsx", ".js"):
                    path = base / f"{name}{suffix}"
                    if path.is_file():
                        found.append(path)
        return found

    @cached_property
    def tsconfig_paths(self) -> list[tuple[str, list[str], Path]]:
        """``(pattern, targets, base dir)`` from every tsconfig*.json at the root."""
        found: list[tuple[str, list[str], Path]] = []
        for config in sorted(self.root.glob("tsconfig*.json")) + [self.root / "jsconfig.json"]:
            if not config.is_file():
                continue
            try:
                data = load_jsonc(config.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            options = data.get("compilerOptions") if isinstance(data, dict) else None
            if not isinstance(options, dict):
                continue
            base = self.root / str(options.get("baseUrl", "."))
            paths = options.get("paths")
            if isinstance(paths, dict):
                for pattern, targets in paths.items():
                    if isinstance(targets, list):
                        found.append((str(pattern), [str(t) for t in targets], base))
        return found

    def resolve_alias(self, specifier: str) -> Path | None:
        """The directory an import alias (``@/components/ui``) points at, if it can be told."""
        for pattern, targets, base in self.tsconfig_paths:
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if specifier.startswith(prefix) and targets:
                    rest = specifier[len(prefix) :]
                    return (base / targets[0].replace("*", rest)).resolve()
            elif specifier == pattern and targets:
                return (base / targets[0]).resolve()
        if specifier.startswith("@/"):
            base = self.root / "src" if (self.root / "src").is_dir() else self.root
            return (base / specifier[2:]).resolve()
        if specifier.startswith(("./", "../")):
            return (self.root / specifier).resolve()
        return None


def locate(explicit: Path | None) -> Frontend:
    """``--frontend``, else the current directory when it has package.json, else <project>/frontend."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    else:
        cwd = Path.cwd()
        candidates.append(cwd)
        candidates.append(cwd / "frontend")
        project = find_project()
        if project is not None:
            candidates.append(project / "frontend")
    for candidate in candidates:
        manifest = candidate / "package.json"
        if manifest.is_file():
            try:
                package = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise CliError(
                    f"{manifest} is not valid JSON ({exc}). karni ui detect reads the "
                    "frontend's dependencies from it. Fix the file, then re-run.",
                    code="C303",
                ) from None
            return Frontend(candidate.resolve(), package if isinstance(package, dict) else {})
    where = explicit if explicit is not None else Path.cwd()
    raise CliError(
        f"No frontend found at {where}: karni ui detect looks for a package.json in the "
        "current directory, in ./frontend, and in the Karni project's frontend/. "
        "Run it in the frontend directory, or pass --frontend <dir>.",
        code="C301",
    )
