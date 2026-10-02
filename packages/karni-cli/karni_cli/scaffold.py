"""Template resolution and slug rules for ``karni new``."""

from __future__ import annotations

import json
import os
import re
from importlib import resources
from pathlib import Path

from karni_cli.project import CliError

SLUG_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def derive_slug(project_name: str) -> str:
    """Mirror cookiecutter.json's project_slug derivation exactly."""
    return project_name.lower().replace(" ", "_").replace("-", "_")


def validate_name(project_name: str) -> str:
    slug = derive_slug(project_name)
    if not SLUG_RE.match(slug):
        raise CliError(
            f'"{project_name}" derives the invalid slug "{slug}" '
            "(allowed: lowercase letters, digits, underscores; must not start with a digit)."
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
            raise CliError(f"KARNI_TEMPLATES={env} does not contain a cookiecutter template.")
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
        "no packaged copy) — reinstall karni-cli."
    )
