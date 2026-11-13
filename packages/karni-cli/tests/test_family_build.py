"""The family test project (experimental): parts built alone and together, every step real.

``pytest -m recipes tests/test_family_build.py`` runs these, and CI's family job
runs them on every push. One part alone: ``karni new --recipe visits`` (a tiny
test recipe in tests/recipes/ that requires the people, events and timeline
contracts).
Two parts together: ``karni new --recipe booking --recipe crm``, then ``karni
recipes add visits`` on the built project and ``karni recipes remove visits``.
Each build runs the migrations, the seed, the project's tests (every part's
among them) and ``karni check`` on SQLite with a local-memory cache, as
tests/test_recipe_builds.py does. npm is stubbed, and so are the frontend tools.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli import recipes as recipes_mod
from karni_cli.builder import record
from karni_cli.main import app
from karni_cli.recipes import parts
from karni_cli.spec.source import load

from .conftest import TEMPLATE, require_modules
from .test_build import _frontend

pytestmark = pytest.mark.recipes

#: Recipes only these tests use.
TEST_RECIPES = Path(__file__).parent / "recipes"


@pytest.fixture
def family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder to make projects in, with this checkout's packages and the test recipes."""
    require_modules("karni-payments")
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_CACHE", "locmem")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    for variable in ("DJANGO_SETTINGS_MODULE", "KARNI_PAYMENTS_PROVIDER", "KARNI_2FA", "CI"):
        monkeypatch.delenv(variable, raising=False)
    original = recipes_mod.load

    def with_test_recipes(builtin: Any = None, *, installed: bool = True) -> recipes_mod.Loaded:
        loaded = original(builtin, installed=installed)
        for name, recipe in original(TEST_RECIPES, installed=False).recipes.items():
            loaded.recipes.setdefault(name, recipe)
        return loaded

    monkeypatch.setattr(recipes_mod, "load", with_test_recipes)
    monkeypatch.chdir(tmp_path)
    _frontend(monkeypatch)
    return tmp_path


def _run(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def _green(output: str) -> None:
    lines = output.splitlines()
    steps = {line.split()[0]: line for line in lines if line[:1].isalpha() and "  " in line}
    assert re.search(r"\d+ passed", steps["test"]), output
    assert not re.search(r"\d+ (failed|errors?)\b", steps["test"]), output
    assert steps["check"].split() == ["check", "ok"], output


def _spec(root: Path) -> dict[str, Any]:
    data = load((root / "karni.yaml").read_text(encoding="utf-8")).data
    assert isinstance(data, dict)
    return data


def _new(folder: Path, monkeypatch: pytest.MonkeyPatch, slug: str, *recipes: str) -> Path:
    root = folder / slug
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{root / 'db.sqlite3'}")
    picked = [arg for name in recipes for arg in ("--recipe", name)]
    _green(_run("new", slug.replace("_", " ").title(), *picked, "-o", "."))
    return root


def test_one_part_alone_gets_the_contracts_it_requires(
    family: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _new(family, monkeypatch, "family_one", "visits")
    spec = _spec(root)
    assert spec["app"]["recipes"] == ["visits"]
    assert spec["features"]["people"] is True and spec["features"]["events"] is True
    assert spec["features"]["timeline"] is True
    settings = (root / "config" / "settings.py").read_text(encoding="utf-8")
    assert "KARNI_PEOPLE = True" in settings
    assert '"karni.outbox"' in settings and '"karni.timeline"' in settings
    parts_ts = (root / "frontend" / "src" / "karni" / "parts.ts").read_text(encoding="utf-8")
    assert 'import { register as registerVisits } from "../visits";' in parts_ts
    assert 'import "./karni/parts";' in (root / "frontend/src/routes.tsx").read_text()
    kept = parts.load_record(root, "visits")
    assert kept is not None and kept.recipe_version == "1.0.0"
    assert set(kept.files) == {
        "frontend/src/visits/index.ts",
        "visits/events.py",
        "visits/tests/test_family.py",
    }
    assert (root / ".karni/recipes/visits/karni.yaml").is_file()
    assert record.load(root).recipes == []


def test_two_parts_together_then_a_third_added_and_removed(
    family: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _new(family, monkeypatch, "family_two", "booking", "crm")
    spec = _spec(root)
    assert spec["app"]["recipes"] == ["booking", "crm"]
    assert spec["apps"]["bookings"]["route"] == "/bookings"
    assert spec["apps"]["crm"]["route"] == "/crm"
    assert {"admin", "customer", "bookings-staff", "crm-manager", "crm-rep"} <= set(spec["roles"])
    routes = (root / "frontend/src/routes.tsx").read_text(encoding="utf-8")
    assert 'path: "/bookings/resources"' in routes and 'path: "/crm/deals"' in routes

    monkeypatch.chdir(root)
    _green(_run("recipes", "add", "visits"))
    spec = _spec(root)
    assert spec["app"]["recipes"] == ["booking", "crm", "visits"]
    assert spec["roles"]["admin"]["grants"]["people.person:erase"] == "all"
    assert (root / "visits" / "events.py").is_file()

    output = _run("recipes", "remove", "visits", "--allow-destructive")
    _green(output)  # the other parts' tests and karni check, with the part's tables dropped
    # the part's files the project never changed are deleted, each one listed
    assert "visits/events.py" in output and not (root / "visits/events.py").exists()
    spec = _spec(root)
    assert spec["app"]["recipes"] == ["booking", "crm"]
    assert "visits" not in spec["apps"] and "visits-staff" not in spec["roles"]
    assert not (root / ".karni/recipes/visits").exists()
