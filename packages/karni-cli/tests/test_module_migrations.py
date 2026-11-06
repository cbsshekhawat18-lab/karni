"""Every module's models and migrations agree, and each of its apps has one leaf migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT

MODULES = sorted(
    path
    for path in (REPO_ROOT / "modules").glob("karni-*")
    if (path / "tests" / "settings.py").is_file() and any(path.glob("*/migrations/0001_*.py"))
)

LEAVES = """
import django
django.setup()
from django.apps import apps
from django.db.migrations.loader import MigrationLoader

graph = MigrationLoader(None).graph
for config in apps.get_app_configs():
    if config.name.startswith("karni_"):
        leaves = sorted(name for app, name in graph.leaf_nodes() if app == config.label)
        print(config.label, len(leaves), *leaves)
"""


def _run(module: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings", "PYTHONPATH": str(module)}
    env.pop("VIRTUAL_ENV", None)
    return subprocess.run(
        [sys.executable, *args], cwd=module, env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_a_modules_migrations_match_its_models(module: Path) -> None:
    result = _run(module, "-m", "django", "makemigrations", "--check", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_a_modules_apps_have_one_leaf_migration(module: Path) -> None:
    result = _run(module, "-c", LEAVES)
    assert result.returncode == 0, result.stderr
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    assert rows, result.stdout
    for label, count, *leaves in rows:
        assert count == "1", f"{label} has {count} leaf migrations: {leaves}"
