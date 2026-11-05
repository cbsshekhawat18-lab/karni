"""``karni recipes`` (experimental): the recipe format, the loader, --match and the blank start.

The built-in recipes are package data of karni-cli. These tests also install
a recipe of their own through a temporary ``karni.recipes`` entry point (a
real ``.dist-info`` on ``sys.path``), and read folders of built-in recipes
from a temporary directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from karni_cli import recipes as recipes_mod
from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.recipes import output
from karni_cli.spec.validate import validate_text

from .conftest import REPO_ROOT

RECIPE_SCHEMA = REPO_ROOT / "docs" / "assets" / "karni-recipe.schema.json"
RECIPES_SCHEMA = REPO_ROOT / "docs" / "assets" / "karni-recipes.schema.json"

HELPDESK_TOML = """\
name = "helpdesk"
title = "Helpdesk"
purpose = "Tickets that customers open and staff answer and close."
use_when = ["helpdesk", "support tickets", "customer support", "ticketing"]
usually_changed = ["the ticket fields", "who may see which tickets"]
"""
HELPDESK_SPEC = """\
version: 1
app:
  name: Helpdesk
  recipe: helpdesk
apps:
  desk:
    entities:
      Ticket:
        fields: {subject: "str:200", requester: fk:User, status: "state:open>closed"}
        owner: requester
"""


def _recipe(folder: Path, name: str, use_when: list[str], purpose: str, spec: str = "") -> Path:
    """A recipe folder: recipe.toml and karni.yaml."""
    folder.mkdir(parents=True)
    (folder / "recipe.toml").write_text(
        f'name = "{name}"\ntitle = "{name.title()}"\npurpose = "{purpose}"\n'
        f"use_when = {json.dumps(use_when)}\n"
    )
    (folder / "karni.yaml").write_text(
        spec or f"version: 1\napp:\n  name: {name.title()}\n  recipe: {name}\n"
    )
    return folder


@pytest.fixture
def builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two built-in recipes, read from a temporary folder instead of karni-cli's."""
    root = tmp_path / "builtin"
    _recipe(
        root / "clinic",
        "clinic",
        ["appointments", "booking", "clinic"],
        "Appointments that patients book with a practitioner.",
    )
    _recipe(
        root / "studio",
        "studio",
        ["classes", "booking", "studio", "members"],
        "Classes that members book, with instructors and a capacity.",
    )
    monkeypatch.setattr(recipes_mod, "builtin_root", lambda: root)
    return root


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The helpdesk recipe, installed through a temporary karni.recipes entry point."""
    site = tmp_path / "site"
    package = site / "acme_recipes"
    folder = package / "helpdesk"
    (folder / "files" / "desk" / "tests").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (folder / "__init__.py").write_text("")
    (folder / "recipe.toml").write_text(HELPDESK_TOML)
    (folder / "karni.yaml").write_text(HELPDESK_SPEC)
    (folder / "files" / "desk" / "models.py").write_text("# the recipe's own methods\n")
    (folder / "files" / "desk" / "tests" / "test_desk.py").write_text("")
    info = site / "acme_recipes-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: acme-recipes\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text("[karni.recipes]\nhelpdesk = acme_recipes.helpdesk\n")
    monkeypatch.syspath_prepend(str(site))
    return folder


def _json(runner: Any, *args: str) -> dict[str, Any]:
    result = runner.invoke(app, ["recipes", *args, "--json"])
    assert result.exit_code == 0, result.output
    data: dict[str, Any] = json.loads(result.stdout)
    return data


# the format -------------------------------------------------------------------------


def test_the_published_recipe_schema_is_current_and_checks_recipe_toml() -> None:
    expected = json.dumps(recipes_mod.json_schema(), indent=2) + "\n"
    assert RECIPE_SCHEMA.read_text() == expected, (
        "docs/assets/karni-recipe.schema.json is stale. Regenerate it: "
        "python -m karni_cli.recipes > docs/assets/karni-recipe.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    published = json.loads(RECIPE_SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    validator = jsonschema.Draft202012Validator(published)
    import tomllib

    assert not list(validator.iter_errors(tomllib.loads(HELPDESK_TOML)))
    assert list(validator.iter_errors({**tomllib.loads(HELPDESK_TOML), "price": 3}))
    assert list(validator.iter_errors({"name": "Help Desk", "title": "x"}))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('name = "x"\n', "title: Field required"),
        (HELPDESK_TOML + 'colour = "red"\n', "colour: Extra inputs are not permitted"),
        (HELPDESK_TOML.replace('"helpdesk"', '"Help Desk"', 1), "name: String should match"),
        (HELPDESK_TOML.replace("Tickets that", "Tickets " + "x" * 80 + " that"), "purpose:"),
        (HELPDESK_TOML.replace('use_when = ["helpdesk",', "use_when = [3,"), "use_when.0:"),
        (HELPDESK_TOML.replace('"helpdesk"', '"blank"', 1), "'blank' is the blank start"),
        ("name = ", "is not TOML"),
    ],
)
def test_an_invalid_recipe_toml_names_its_problem(text: str, problem: str) -> None:
    with pytest.raises(recipes_mod.RecipeError, match="acme") as raised:
        recipes_mod.parse(text, "acme")
    assert problem in str(raised.value)


def test_every_built_in_recipe_is_valid() -> None:
    """Each built-in recipe's recipe.toml, karni.yaml and app.recipe (A6 adds them)."""
    loaded = recipes_mod.load(installed=False)
    assert loaded.problems == []
    for name, recipe in loaded.recipes.items():
        report = validate_text(recipe.spec())
        assert report.ok, (name, [issue.as_dict() for issue in report.issues])
        assert yaml.safe_load(recipe.spec())["app"].get("recipe") == name


def test_a_recipe_that_cannot_be_used_is_left_out_and_reported(builtin: Path, runner: Any) -> None:
    (builtin / "broken").mkdir()
    (builtin / "broken" / "recipe.toml").write_text('name = "broken"\n')
    _recipe(builtin / "renamed", "other", ["x"], "A recipe under another name.")
    nospec = _recipe(builtin / "nospec", "nospec", ["x"], "A recipe without its spec.")
    (nospec / "karni.yaml").unlink()
    (builtin / "notes").mkdir()  # no recipe.toml: not a recipe at all
    loaded = recipes_mod.load(installed=False)
    assert sorted(loaded.recipes) == ["clinic", "studio"]
    assert [problem.split(":")[0] for problem in loaded.problems] == [
        "built in (broken)",
        "built in (nospec)",
        "built in (renamed)",
    ]
    assert "no karni.yaml" in loaded.problems[1]
    assert "'other' is not 'renamed'" in loaded.problems[2]
    result = runner.invoke(app, ["recipes", "list"])
    assert result.exit_code == 0
    assert result.stderr.count("warning: C421: ") == 3
    shown = runner.invoke(app, ["recipes", "show", "nospec"])
    assert isinstance(shown.exception, CliError) and shown.exception.code == "C421"
    assert "The recipe 'nospec' cannot be used: built in (nospec): no karni.yaml." in str(
        shown.exception
    )


# where recipes come from --------------------------------------------------------------


def test_an_installed_recipe_comes_from_its_entry_point(installed: Path, runner: Any) -> None:
    loaded = recipes_mod.load(builtin=installed.parent / "nothing-here", installed=True)
    # (a missing folder of built-in recipes reads as none)
    recipe = loaded.recipes["helpdesk"]
    assert recipe.source == "entry point helpdesk (acme-recipes 1.0)"
    assert recipe.files == ("desk/models.py", "desk/tests/test_desk.py")
    assert recipe.spec() == HELPDESK_SPEC
    shown = runner.invoke(app, ["recipes", "show", "helpdesk"])
    assert shown.exit_code == 0, shown.output
    assert shown.output.startswith(
        "helpdesk: Helpdesk (entry point helpdesk (acme-recipes 1.0))\n"
        "Tickets that customers open and staff answer and close.\n"
        "Use when: helpdesk; support tickets; customer support; ticketing\n"
        "Usually changed: the ticket fields; who may see which tickets\n"
        "Files: desk/models.py, desk/tests/test_desk.py\n"
        "karni.yaml:\nversion: 1\n"
    )
    data = _json(runner, "show", "helpdesk")
    assert data["recipes"][0]["spec"] == HELPDESK_SPEC
    assert data["recipes"][0]["usually_changed"] == [
        "the ticket fields",
        "who may see which tickets",
    ]


def test_a_built_in_recipe_wins_over_an_installed_one_of_the_same_name(
    builtin: Path, installed: Path
) -> None:
    _recipe(builtin / "helpdesk", "helpdesk", ["helpdesk"], "The built-in helpdesk.")
    loaded = recipes_mod.load()
    assert loaded.recipes["helpdesk"].purpose == "The built-in helpdesk."
    assert loaded.problems == [
        (
            "entry point helpdesk (acme-recipes 1.0): a recipe named 'helpdesk' is there "
            "already (built in (helpdesk)), so this one is left out."
        )
    ]


# --match ----------------------------------------------------------------------------


def test_words_lowercase_drop_stopwords_and_make_plurals_singular() -> None:
    assert recipes_mod.words("A Booking app for my Classes, with quizzes & categories!") == [
        "booking",
        "class",
        "quiz",
        "category",
    ]
    assert recipes_mod.words("an app to build, please") == []
    assert recipes_mod.words("status campus business boxes") == [
        "status",
        "campus",
        "business",
        "box",
    ]


def test_match_ranks_by_word_overlap_best_first(builtin: Path) -> None:
    found = recipes_mod.load(installed=False).recipes.values()
    ranked = recipes_mod.match(found, "Booking classes at a yoga studio")
    assert [(m.recipe.name, m.score, m.matched) for m in ranked] == [
        ("studio", 6, ("booking", "class", "studio")),
        ("clinic", 2, ("booking",)),
    ]
    # a tie goes to the name, a purpose word scores 1, and below the threshold is nothing
    assert [m.recipe.name for m in recipes_mod.match(found, "booking")] == ["clinic", "studio"]
    assert [(m.recipe.name, m.score) for m in recipes_mod.match(found, "patients")] == []
    two = recipes_mod.match(found, "patients and practitioners")
    assert [(m.recipe.name, m.score, m.matched) for m in two] == [
        ("clinic", 2, ("patient", "practitioner"))
    ]
    assert recipes_mod.match(found, "a reading list") == []


def test_match_returns_at_most_the_best_few(builtin: Path) -> None:
    for name in ("a1", "b2", "c3"):
        _recipe(builtin / name, name, ["booking"], "Another booking app.")
    found = recipes_mod.load(installed=False).recipes.values()
    ranked = recipes_mod.match(found, "booking")
    assert len(ranked) == recipes_mod.MATCH_LIMIT == 3
    assert [m.recipe.name for m in ranked] == ["a1", "b2", "c3"]


def test_list_and_match_through_the_cli(builtin: Path, runner: Any) -> None:
    listed = runner.invoke(app, ["recipes", "list"])
    assert listed.exit_code == 0, listed.output
    assert listed.output.splitlines()[1:3] == [
        "clinic  Clinic: Appointments that patients book with a practitioner.",
        "studio  Studio: Classes that members book, with instructors and a capacity.",
    ]
    matched = runner.invoke(app, ["recipes", "list", "--match", "a studio for yoga classes"])
    assert matched.exit_code == 0, matched.output
    assert matched.output.splitlines()[:2] == [
        'Recipes for "a studio for yoga classes", best first (score, then name):',
        (
            "studio   4  Studio: Classes that members book, with instructors and a capacity. "
            "(matched: studio, class)"
        ),
    ]
    assert "karni recipes show studio prints its spec" in matched.output
    data = _json(runner, "list", "--match", "a studio for yoga classes")
    assert [(r["name"], r["score"], r["matched"]) for r in data["recipes"]] == [
        ("studio", 4, ["studio", "class"])
    ]
    assert data["request"] == "a studio for yoga classes" and data["threshold"] == 2


# the blank start --------------------------------------------------------------------


def test_no_match_names_the_blank_start(
    builtin: Path, runner: Any, generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["recipes", "list", "--match", "a reading list for books"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        'No recipe matches "a reading list for books": none scores 2 or more. The blank start '
        "fits.\nkarni.yaml of the blank start:\n# yaml-language-server: $schema="
    )
    blank = _json(runner, "show", "blank")
    assert blank["recipes"] == []
    spec = blank["blank"]["spec"]
    assert yaml.safe_load(spec) == {"version": 1, "app": {"name": "Acme Board"}}
    assert validate_text(spec).ok
    shown = runner.invoke(app, ["recipes", "show", "blank"])
    assert shown.output.splitlines()[-2:] == [
        "  name: Acme Board",
        "next: write it to karni.yaml, add what the request asks for, then karni plan --questions",
    ]


def test_without_any_recipe_the_list_is_the_blank_start(
    tmp_path: Path, runner: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recipes_mod, "builtin_root", lambda: tmp_path)
    monkeypatch.setattr(recipes_mod, "_entry_points", list)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["recipes", "list"])
    assert result.output == (
        "No recipe is installed.\n"
        "blank: the blank start, karni.yaml with the version and the app's name (karni "
        "recipes show blank).\n"
        "next: no recipe is installed: start karni.yaml from the blank start (karni recipes "
        "show blank) and write in it what the request asks for\n"
    )


def test_an_unknown_recipe_is_refused(builtin: Path, runner: Any) -> None:
    result = runner.invoke(app, ["recipes", "show", "shop"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C420"
    assert "There is no recipe 'shop' (there are: clinic, studio, blank)." in str(result.exception)


# --json -----------------------------------------------------------------------------


def test_the_published_recipes_schema_is_current_and_checks_the_output(
    builtin: Path, installed: Path, runner: Any
) -> None:
    expected = json.dumps(output.json_schema(), indent=2) + "\n"
    assert RECIPES_SCHEMA.read_text() == expected, (
        "docs/assets/karni-recipes.schema.json is stale. Regenerate it: "
        "python -m karni_cli.recipes.output > docs/assets/karni-recipes.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    published = json.loads(RECIPES_SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    validator = jsonschema.Draft202012Validator(published)
    for args in (
        ["list"],
        ["list", "--match", "customer support tickets"],
        ["list", "--match", "nothing fits this"],
        ["show", "helpdesk"],
        ["show", "blank"],
    ):
        data = _json(runner, *args)
        assert not list(validator.iter_errors(data)), args
    assert list(validator.iter_errors({**data, "version": 2}))


def test_the_built_in_recipes_are_the_folders_next_to_the_loader() -> None:
    """A6 adds a recipe as a folder: nothing else to register."""
    assert Path(str(recipes_mod.builtin_root())) == Path(recipes_mod.__file__).parent
