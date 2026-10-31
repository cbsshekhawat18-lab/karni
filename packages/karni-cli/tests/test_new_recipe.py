"""The built-in recipes and ``karni new --recipe`` (experimental), without a full build.

Every recipe's ``recipe.toml`` and ``karni.yaml`` are valid, its spec has no
open question, ``karni plan`` on an empty project lists what it builds, and
``karni recipes list --match`` picks it for a one-line request. The stub
rule is checked on its own and through ``karni build``: a recipe never
writes over a file of the project's. The full builds, one per recipe, are
in tests/test_recipe_builds.py, behind the ``recipes`` marker.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli import recipes as recipes_mod
from karni_cli.builder import record, render
from karni_cli.generators.core import Workspace
from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.recipes import apply
from karni_cli.spec.export import read_facts
from karni_cli.spec.plan import plan_project
from karni_cli.spec.validate import validate_text

from .conftest import TEMPLATE

#: The built-in recipes, and the app label each one builds.
RECIPES = {
    "booking": "bookings",
    "crm": "crm",
    "lms": "courses",
    "marketplace": "market",
    "shop": "shop",
}
#: A one-line request per recipe, as a person asks for the app.
REQUESTS = {
    "an online shop": "shop",
    "book a class": "booking",
    "track sales deals": "crm",
    "online courses": "lms",
    "a marketplace for sellers": "marketplace",
}

STUB_MODELS = '''"""shop models. Each class extends the one karni build writes in shop/karni/models.py
from karni.yaml: add your methods here.
"""

from shop.karni import models as karni


class Order(karni.Order):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
'''
RECIPE_MODELS = '''"""shop models."""

from shop.karni import models as karni


class Order(karni.Order):
    def total(self) -> int:
        return 0
'''


def _recipe(tmp_path: Path, files: dict[str, str]) -> recipes_mod.Recipe:
    """A recipe of the test's own, with ``files`` under files/."""
    folder = tmp_path / "recipe"
    (folder / "files").mkdir(parents=True)
    (folder / "recipe.toml").write_text(
        'name = "shop"\ntitle = "Shop"\npurpose = "A shop."\nuse_when = ["shop"]\n'
    )
    (folder / "karni.yaml").write_text("version: 1\napp: {name: Shop, recipe: shop}\n")
    for rel, text in files.items():
        (folder / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / "files" / rel).write_text(text)
    return recipes_mod.read_folder(folder, name="shop", source="test")


@pytest.fixture(autouse=True)
def _project_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))


# the built-in recipes -----------------------------------------------------------------


def test_the_built_in_recipes_are_the_five() -> None:
    loaded = recipes_mod.load(installed=False)
    assert loaded.problems == []
    assert sorted(loaded.recipes) == sorted(RECIPES)


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_a_recipe_validates_and_leaves_no_question_open(name: str, runner: CliRunner) -> None:
    recipe = recipes_mod.load(installed=False).get(name)
    assert recipe is not None
    report = validate_text(recipe.spec())
    assert report.ok, [issue.as_dict() for issue in report.issues]
    data = yaml.safe_load(recipe.spec())
    assert data["app"]["recipe"] == name and data["app"]["kind"] == "app"
    assert data["seed"], "a recipe gives its demo volumes"
    spec = Path(str(recipe.folder.joinpath(recipes_mod.SPEC_FILE)))
    result = runner.invoke(app, ["plan", "--questions", "--json", "--spec", str(spec)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["total"] == 0
    # its own files go where the project owns the code, under the app it builds
    assert recipe.files
    assert all(rel.split("/")[0] == RECIPES[name] for rel in recipe.files)
    assert not [rel for rel in recipe.files if recipes_mod.karni_owned(rel)]


@pytest.mark.parametrize(("request_line", "name"), sorted(REQUESTS.items()))
def test_match_picks_the_recipe_for_a_one_line_request(
    request_line: str, name: str, runner: CliRunner
) -> None:
    result = runner.invoke(app, ["recipes", "list", "--match", request_line, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["recipes"][0]["name"] == name


@dataclass
class Empty:
    root: Path
    facts: dict[str, Any]


@pytest.fixture(scope="module")
def empty(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Empty]:
    """An empty ``karni new`` project and its facts, read once."""
    from cookiecutter.main import cookiecutter

    parent = tmp_path_factory.mktemp("recipe-plan")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
        mp.setenv("DATABASE_URL", f"sqlite:///{parent / 'db.sqlite3'}")
        mp.setenv("PYTHONDONTWRITEBYTECODE", "1")
        mp.delenv("DJANGO_SETTINGS_MODULE", raising=False)
        cookiecutter(
            str(TEMPLATE),
            no_input=True,
            extra_context={"project_name": "Empty"},
            output_dir=str(parent),
        )
        root = parent / "empty"
        mp.chdir(root)
        yield Empty(root, read_facts(root, docker=False))


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_karni_plan_on_an_empty_project_lists_what_the_recipe_builds(
    name: str, empty: Empty
) -> None:
    recipe = recipes_mod.load(installed=False).get(name)
    assert recipe is not None
    report = validate_text(recipe.spec(), databases=empty.facts["databases"])
    assert report.ok and report.spec is not None
    plan = plan_project(report.spec, empty.facts, empty.root, file="karni.yaml")
    text = plan.text()
    label = RECIPES[name]
    assert f"  + {label}\n" in text
    for entity in report.spec.apps[label].entities:
        assert f"  + {label}.{entity}: (" in text
    for module in report.spec.modules:
        assert f"  + {module}: " in text
    assert not plan.risky and not plan.not_managed
    assert f"{len(plan.changes)} changes, 0 risky." in text


# the stub rule --------------------------------------------------------------------------


def test_is_stub_file_knows_what_build_writes_in_a_project_file() -> None:
    assert render.is_stub_file("shop/models.py", STUB_MODELS)
    access_code = (
        '"""shop API. Each viewset extends the one karni build writes in shop/karni/api.py from\n'
        'karni.yaml: add your actions here.\n"""\n\n'
        "from karni.api import Granted\n\nfrom shop.karni import api as karni\n\n\n"
        "class OrderViewSet(karni.OrderViewSet):\n"
        '    """The base class comes from karni.yaml (karni build). Add your own code here."""\n\n'
        "    access = Granted()\n"
    )
    assert render.is_stub_file("shop/viewsets.py", access_code)
    assert not render.is_stub_file("shop/models.py", RECIPE_MODELS)
    assert not render.is_stub_file("shop/models.py", STUB_MODELS + "\nLIMIT = 3\n")
    assert not render.is_stub_file("shop/models.py", "def broken(:\n")
    assert not render.is_stub_file("shop/tests/test_shop.py", "# only a comment\n")
    assert not render.is_stub_file("shop/models.py", STUB_MODELS.split("\n", 3)[3])


def test_a_recipe_replaces_build_stubs_and_writes_its_own_tests(tmp_path: Path) -> None:
    recipe = _recipe(
        tmp_path,
        {"shop/models.py": RECIPE_MODELS, "shop/tests/test_shop.py": "def test_x():\n    pass\n"},
    )
    root = tmp_path / "project"
    (root / "shop").mkdir(parents=True)
    (root / "shop" / "models.py").write_text(STUB_MODELS)
    ws = Workspace(root)
    assert apply.stage(ws, recipe) == ["shop/models.py", "shop/tests/test_shop.py"]
    assert ws.read("shop/models.py") == RECIPE_MODELS
    ws.commit(dry_run=False)
    assert apply.stage(Workspace(root), recipe) == []  # the recipe's already: nothing to do


def test_a_class_build_writes_for_an_entity_the_recipe_lacks_is_kept(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path, {"shop/models.py": RECIPE_MODELS})
    ws = Workspace(tmp_path / "project")
    extra = (
        "\n\nclass Refund(karni.Refund):\n"
        '    """The base class comes from karni.yaml (karni build). Add your own code here."""\n'
    )
    ws.write("shop/models.py", STUB_MODELS + extra)  # what build stages for the spec
    apply.stage(ws, recipe)
    text = ws.read("shop/models.py") or ""
    assert text.startswith(RECIPE_MODELS.rstrip("\n"))
    assert "class Refund(karni.Refund):" in text and text.count("class Order(") == 1


def test_a_recipe_never_writes_over_code_of_the_projects(tmp_path: Path) -> None:
    recipe = _recipe(
        tmp_path, {"shop/models.py": RECIPE_MODELS, "shop/tests/test_shop.py": "# the recipe's\n"}
    )
    root = tmp_path / "project"
    (root / "shop" / "tests").mkdir(parents=True)
    edited = STUB_MODELS.replace(
        '    """The base class comes from karni.yaml (karni build). Add your own code here."""',
        "    def is_big(self) -> bool:\n        return True",
    )
    (root / "shop" / "models.py").write_text(edited)
    (root / "shop" / "tests" / "test_shop.py").write_text("# mine\n")
    ws = Workspace(root)
    assert apply.refused(ws, recipe) == ["shop/models.py", "shop/tests/test_shop.py"]
    with pytest.raises(CliError) as raised:
        apply.stage(ws, recipe)
    assert raised.value.code == "C441"
    assert "shop/models.py, shop/tests/test_shop.py hold code of the project's" in str(
        raised.value
    )
    assert ws.changes() == []


def test_a_recipe_file_where_karni_build_writes_is_refused(tmp_path: Path) -> None:
    with pytest.raises(recipes_mod.RecipeError, match="karni build writes shop/karni/models.py"):
        _recipe(tmp_path, {"shop/karni/models.py": "# Karni's\n"})
    for rel in ("shop/tests/karni/test_x.py", "config/settings.py", "karni.yaml", ".karni/x"):
        assert recipes_mod.karni_owned(rel), rel
    for rel in ("shop/models.py", "shop/tests/test_x.py", "shop/karni.py", "frontend/src/x.tsx"):
        assert not recipes_mod.karni_owned(rel), rel


def _pending(root: Path, name: str) -> None:
    """What karni new --recipe leaves: the recipe's spec, and the recipe named in the record."""
    found = recipes_mod.load(installed=False).get(name)
    assert found is not None
    (root / "karni.yaml").write_text(found.spec())
    (root / ".karni").mkdir(exist_ok=True)
    (root / ".karni" / "build.json").write_text(record.Record(recipe=name).text())


def _build(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["build", *args])
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.output


def test_karni_build_after_new_recipe_plans_the_recipe_files(
    empty: Empty, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pending(empty.root, "shop")
    monkeypatch.chdir(empty.root)
    code, out = _build("--dry-run")
    assert code == 0, out
    assert "would create shop/models.py (project)" in out
    assert "would create shop/tests/test_checkout.py (project)" in out
    assert record.load(empty.root).recipe == "shop"  # a dry run writes nothing


def test_karni_build_stops_when_a_recipe_file_holds_the_projects_code(
    empty: Empty, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pending(empty.root, "shop")
    monkeypatch.chdir(empty.root)
    (empty.root / "shop").mkdir(exist_ok=True)
    mine = '"""My own shop code."""\n\n\ndef discount() -> int:\n    return 5\n'
    (empty.root / "shop" / "models.py").write_text(mine)
    try:
        code, out = _build()
        assert code == 1
        assert "error C441: shop/models.py holds code of the project's" in out
        assert (empty.root / "shop" / "models.py").read_text() == mine
        assert not (empty.root / "shop" / "karni").exists()
        assert record.load(empty.root).recipe == "shop"  # still to write
    finally:
        (empty.root / "shop" / "models.py").unlink()
        (empty.root / "shop").rmdir()


# karni new --recipe --------------------------------------------------------------------


def _new(runner: CliRunner, tmp_path: Path, *args: str) -> Any:
    return runner.invoke(app, ["new", "Corner Shop", "-o", str(tmp_path), *args])


def test_an_unknown_recipe_is_refused_with_the_closest_names(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = _new(runner, tmp_path, "--recipe", "shops")
    assert isinstance(result.exception, CliError) and result.exception.code == "C420"
    assert (
        "There is no recipe 'shops': the closest is shop (there are: booking, crm, lms, "
        "marketplace, shop, blank)." in str(result.exception)
    )
    assert not (tmp_path / "corner_shop").exists()


@pytest.mark.parametrize(
    "option", [["--design", "."], ["--kind", "site"], ["--kind", "app", "--no-staff-app"]]
)
def test_a_recipe_with_an_option_it_cannot_go_with_is_refused(
    option: list[str], runner: CliRunner, tmp_path: Path
) -> None:
    result = _new(runner, tmp_path, "--recipe", "shop", *option)
    assert isinstance(result.exception, CliError) and result.exception.code == "C440"
    assert not (tmp_path / "corner_shop").exists()


def test_without_an_interpreter_it_stops_after_the_spec(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(project_mod, "venv_python", lambda project: None)
    result = _new(runner, tmp_path, "--recipe", "booking", "--kind", "site+app")
    assert result.exit_code == 0, result.output
    root = tmp_path / "corner_shop"
    spec = yaml.safe_load((root / "karni.yaml").read_text())
    assert spec["app"] == {"name": "Corner Shop", "kind": "site+app", "recipe": "booking"}
    assert validate_text((root / "karni.yaml").read_text()).ok
    assert record.load(root).recipe == "booking"
    assert "$ karni build" not in result.output
    lines = result.output.splitlines()
    assert "Recipe booking (Booking): wrote karni.yaml (app.recipe: booking)" in result.output
    assert any(line.startswith("karni build did not run here: no interpreter") for line in lines)
    assert lines[-1] == "next: karni build"


def test_the_blank_start_writes_only_the_name(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = _new(runner, tmp_path, "--recipe", "blank")
    assert result.exit_code == 0, result.output
    root = tmp_path / "corner_shop"
    assert yaml.safe_load((root / "karni.yaml").read_text()) == {
        "version": 1,
        "app": {"name": "Corner Shop"},
    }
    assert not (root / ".karni" / "build.json").exists()
    assert "Blank start: wrote karni.yaml" in result.output
