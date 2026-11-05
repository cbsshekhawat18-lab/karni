"""Each built-in recipe built from scratch (experimental): ``karni new --recipe``, every step real.

``pytest -m recipes`` runs these, one test per recipe, and CI's recipes job
runs each one on its own, so a recipe never rots. The test renders ``karni
new "<title>" --recipe <name>``, which runs ``karni build`` on SQLite with a
local-memory cache, as tests/test_build.py sets a project up: the module,
the models, the recipe's own files over build's stubs, the migrations, the
seed with the recipe's seeders, the project's own tests (the recipe's among
them) and ``karni check``. npm is stubbed, and so are the frontend tools.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli import recipes as recipes_mod
from karni_cli.builder import record
from karni_cli.main import app
from karni_cli.recipes import apply

from .conftest import TEMPLATE, require_modules
from .test_build import _frontend
from .test_new_recipe import RECIPES

pytestmark = pytest.mark.recipes


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_a_recipe_builds_from_scratch_with_its_tests_and_check_green(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_modules("karni-payments")
    recipe = recipes_mod.load(installed=False).get(name)
    assert recipe is not None
    root = tmp_path / f"demo_{name.replace('-', '_')}"  # the project folder is the slug
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{root / 'db.sqlite3'}")
    monkeypatch.setenv("KARNI_CACHE", "locmem")  # karni new's .env.example points at Redis
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    for variable in ("DJANGO_SETTINGS_MODULE", "KARNI_PAYMENTS_PROVIDER", "KARNI_2FA", "CI"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)
    _frontend(monkeypatch)

    started = time.monotonic()
    result = CliRunner().invoke(app, ["new", f"Demo {name}", "--recipe", name, "-o", "."])
    took = time.monotonic() - started
    assert result.exit_code == 0, result.output
    print(f"\nrecipe {name}: karni new --recipe {name} built in {took:.1f}s")

    lines = result.output.splitlines()
    steps = {line.split()[0]: line for line in lines if line[:1].isalpha() and "  " in line}
    assert "failed" not in steps["test"] and " passed in " in steps["test"]
    assert steps["check"].split() == ["check", "ok"]
    assert "Built: the project matches karni.yaml." in lines
    for rel, text in apply.contents(recipe).items():
        assert (root / rel).read_text() == text, rel  # the recipe's own files, as it ships them
    assert record.load(root).recipe == ""  # written: the next build leaves them to the project

    # A fresh recipe follows Karni's patterns, so karni suggest has nothing to say.
    monkeypatch.chdir(root)
    suggested = CliRunner().invoke(
        app, ["suggest", "--json", "--no-docker"], catch_exceptions=False
    )
    assert suggested.exit_code == 0, suggested.output
    assert json.loads(suggested.stdout)["suggestions"] == [], suggested.stdout
