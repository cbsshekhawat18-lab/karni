"""Template, @karni/ui source resolution and slug rules for ``karni new``."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from karni_cli.project import CliError

SLUG_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

UI_PACKAGE = "@karni/ui"
#: The npm spec a project gets when no local @karni/ui is found.
UI_REGISTRY_SPEC = "^0.3.0"
#: What a ``file:`` consumer needs: package.json ``exports`` point into dist/.
UI_DIST_FILES = ("dist/index.js", "dist/styles.css", "dist/tailwind-preset.js")
#: Sources the dist is built from (staleness check).
UI_BUILD_INPUTS = ("src", "tailwind-preset.ts")
NPM_TIMEOUT = 900


def derive_slug(project_name: str) -> str:
    """Mirror cookiecutter.json's project_slug derivation exactly."""
    return project_name.lower().replace(" ", "_").replace("-", "_")


def validate_name(project_name: str) -> str:
    slug = derive_slug(project_name)
    if not SLUG_RE.match(slug):
        raise CliError(
            f'"{project_name}" derives the invalid slug "{slug}" '
            "(allowed: lowercase letters, digits, underscores; must not start with a digit).",
            code="C103",
        )
    return slug


def _is_karni_template(candidate: Path) -> bool:
    """The repo-walk must verify the directory is Karni's own template (E7)."""
    cc = candidate / "cookiecutter.json"
    if not cc.is_file():
        return False
    try:
        keys = json.loads(cc.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    repo_root = candidate.parent.parent
    return "project_slug" in keys and (repo_root / "packages" / "karni").is_dir()


def resolve_template() -> Path:
    """KARNI_TEMPLATES env > verified monorepo checkout > packaged copy."""
    env = os.environ.get("KARNI_TEMPLATES")
    if env:
        path = Path(env).expanduser()
        if not (path / "cookiecutter.json").is_file():
            raise CliError(
                f"KARNI_TEMPLATES={env} does not contain a cookiecutter template.", code="C007"
            )
        return path

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "templates" / "project"
        if candidate.is_dir() and _is_karni_template(candidate):
            return candidate

    packaged = resources.files("karni_cli") / "_templates" / "project"
    with resources.as_file(packaged) as path:
        if path.is_dir():
            return path
    raise CliError(
        "No project template found (no KARNI_TEMPLATES, no monorepo checkout, "
        "no packaged copy) — reinstall karni-cli.",
        code="C005",
    )


# @karni/ui source


def _is_karni_ui(candidate: Path) -> bool:
    """A directory is Karni's UI package when its package.json names @karni/ui."""
    try:
        meta = json.loads((candidate / "package.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(meta, dict) and meta.get("name") == UI_PACKAGE


def resolve_ui_source(start: Path | None = None) -> Path | None:
    """KARNI_UI_SRC env > verified monorepo checkout > ``None`` (the npm registry).

    Mirrors :func:`resolve_template`: the repo-walk only accepts
    ``packages/karni-ui`` when it really is @karni/ui AND sits next to
    ``packages/karni`` — never some unrelated directory of the same name.
    """
    env = os.environ.get("KARNI_UI_SRC")
    if env:
        path = Path(env).expanduser().resolve()
        if not _is_karni_ui(path):
            raise CliError(
                f"KARNI_UI_SRC={env} is not the {UI_PACKAGE} package "
                "(expected a directory whose package.json is named @karni/ui, "
                "e.g. /path/to/Karni/packages/karni-ui).",
                code="C007",
            )
        return path
    for parent in (start or Path(__file__).resolve()).parents:
        candidate = parent / "packages" / "karni-ui"
        if _is_karni_ui(candidate) and (parent / "packages" / "karni").is_dir():
            return candidate
    return None


def ui_spec(source: Path | None, project: Path | None = None) -> str:
    """The ``@karni/ui`` dependency spec written into frontend/package.json.

    A local checkout is a ``file:`` path. When the project lives inside that
    checkout (``examples/``), the path is relative to ``frontend/`` so the
    project installs on any machine; elsewhere it is absolute.
    """
    if source is None:
        return UI_REGISTRY_SPEC
    root = source.parent.parent
    if project is not None and project.resolve().is_relative_to(root):
        return f"file:{os.path.relpath(source, project.resolve() / 'frontend')}"
    return f"file:{source}"


def ui_mount_target(spec: str, container_dir: str = "/app") -> str:
    """Where a ``file:`` spec resolves inside the frontend container (compose bind target)."""
    if not spec.startswith("file:"):
        return spec
    path = spec.removeprefix("file:")
    if posixpath.isabs(path):
        return path
    return posixpath.normpath(posixpath.join(container_dir, path))


def ui_dist_missing(source: Path) -> list[str]:
    return [rel for rel in UI_DIST_FILES if not (source / rel).is_file()]


def ui_dist_stale(source: Path) -> bool:
    """True when a dist input (src/, the preset) changed after dist/index.js was built."""
    built = source / UI_DIST_FILES[0]
    if not built.is_file():
        return False
    stamp = built.stat().st_mtime
    for name in UI_BUILD_INPUTS:
        root = source / name
        files = [root] if root.is_file() else (p for p in root.rglob("*") if p.is_file())
        if any(path.stat().st_mtime > stamp for path in files):
            return True
    return False


def ui_install_command(source: Path) -> list[str]:
    """How ``source`` gets its node_modules without rewriting files git tracks.

    ``npm ci`` installs exactly what package-lock.json pins and never writes it;
    ``npm install`` may rewrite it, which dirties a Karni checkout. Without a
    lockfile, ``--no-package-lock`` keeps npm from creating one.
    """
    if (source / "package-lock.json").is_file():
        return ["npm", "ci", "--no-audit"]
    return ["npm", "install", "--no-audit", "--no-package-lock"]


def ui_build_commands(source: Path) -> list[list[str]]:
    """The install (only without node_modules) then ``npm run build``."""
    commands = [] if (source / "node_modules").is_dir() else [ui_install_command(source)]
    return [*commands, ["npm", "run", "build"]]


def run_npm(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one npm command (the seam tests replace)."""
    npm = shutil.which(argv[0])
    if npm is None:
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr="npm is not on PATH")
    try:
        return subprocess.run(
            [npm, *argv[1:]],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=NPM_TIMEOUT,
            env={**os.environ, "CI": "1"},
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, stdout="", stderr="timed out")


def build_ui_dist(source: Path) -> str | None:
    """Build @karni/ui's dist/ in ``source``; ``None`` on success, else the failure."""
    for argv in ui_build_commands(source):
        proc = run_npm(argv, source)
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
            return f"`{' '.join(argv)}` failed ({proc.returncode}):\n{tail}"
    missing = ui_dist_missing(source)
    return f"the build did not produce {', '.join(missing)}" if missing else None
