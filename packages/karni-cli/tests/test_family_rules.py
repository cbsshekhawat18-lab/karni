"""The rules that keep parts independent (K315, K316), on the recipes and on built projects.

The first test reads every recipe's own files and asserts no part names another one.
``leaky`` (tests/recipes/leaky) is the deliberately bad part: it must be caught.
The ``recipes`` tests build booking and crm together and break one rule at a time in the
built project, as ``karni check`` is run by a person or by CI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml
from karni.testing import parts as part_rules
from typer.testing import CliRunner

from karni_cli import recipes as recipes_mod
from karni_cli.commands import check as check_mod
from karni_cli.main import app

from .test_family_build import TEST_RECIPES, _new, family  # noqa: F401

BUILTIN = Path(recipes_mod.__file__).parent


def _recipe_dirs() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (BUILTIN, TEST_RECIPES):
        for toml in sorted(base.glob("*/recipe.toml")):
            name = tomllib.loads(toml.read_text(encoding="utf-8"))["name"]
            found[str(name)] = toml.parent
    return found


def _labels(folder: Path) -> list[str]:
    data = yaml.safe_load((folder / "karni.yaml").read_text(encoding="utf-8"))
    return [str(label) for label in (data.get("apps") or {})]


def _leaks(name: str, folder: Path, labels: dict[str, list[str]]) -> list[str]:
    others = sorted({label for key, mine in labels.items() if key != name for label in mine})
    found: list[str] = []
    files = folder / "files"
    for path in sorted(files.rglob("*")) if files.is_dir() else []:
        if path.is_file():
            found += [f"{path.relative_to(files)}:{ref.line} {ref.what}"
                      for ref in part_rules.references_in(path, others)]
    return found


def test_no_recipe_names_another_recipe() -> None:
    folders = {name: folder for name, folder in _recipe_dirs().items() if name != "leaky"}
    labels = {name: _labels(folder) for name, folder in folders.items()}
    assert {"booking", "crm", "visits"} <= set(folders)
    leaks = {name: _leaks(name, folder, labels) for name, folder in folders.items()}
    assert {name: found for name, found in leaks.items() if found} == {}


def test_the_bad_test_part_is_caught() -> None:
    folders = _recipe_dirs()
    labels = {name: _labels(folder) for name, folder in folders.items()}
    found = _leaks("leaky", folders["leaky"], labels)
    assert any("services.py" in line and "imports from crm.models" in line for line in found)
    assert any("asks for the app 'crm'" in line for line in found)
    assert any("a model reference 'crm.Deal'" in line for line in found)
    assert any("frontend/src/leaks/index.ts" in line for line in found)


def _check(root: Path) -> tuple[int, str]:
    """``karni check``'s backend and frontend checks, as the build runs them: (code, output)."""
    passed, output = check_mod.run_checks(root)
    return (0 if passed else 1), output


@pytest.mark.recipes
def test_check_refuses_a_part_naming_another_and_a_stray_role_or_route(
    family: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    root = _new(family, monkeypatch, "family_rules", "booking", "crm")
    monkeypatch.chdir(root)
    assert _check(root)[0] == 0

    # a part that imports another part
    bridge = root / "bookings" / "bridge.py"
    bridge.write_text("from crm.models import Deal\n", encoding="utf-8")
    code, output = _check(root)
    assert code != 0
    assert "[part-imports-part] bookings/bridge.py:1" in output and "crm part" in output
    bridge.write_text(
        "from crm.models import Deal  # karni: allow(part-imports-part): a bridge for the test\n",
        encoding="utf-8",
    )
    assert _check(root)[0] == 0
    bridge.unlink()

    spec_file = root / "karni.yaml"
    original = spec_file.read_text(encoding="utf-8")
    # a role that lost its prefix
    spec_file.write_text(original.replace("  crm-rep:", "  rep:"), encoding="utf-8")
    code, output = _check(root)
    assert code != 0 and "[part-role-prefix]" in output and "crm-rep" in output
    # a base route that is a family page's
    text = original.replace("route: /crm", "route: /settings")
    assert text != original
    spec_file.write_text(text, encoding="utf-8")
    code, output = _check(root)
    assert code != 0 and "[part-route]" in output and "family page" in output
    spec_file.write_text(original, encoding="utf-8")
    assert _check(root)[0] == 0


@pytest.mark.recipes
def test_a_build_with_the_bad_test_part_fails_karni_check(
    family: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    root = family / "family_leaky"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{root / 'db.sqlite3'}")
    result = CliRunner().invoke(
        app, ["new", "Family Leaky", "--recipe", "crm", "--recipe", "leaky", "-o", "."]
    )
    assert result.exit_code != 0
    assert "[part-imports-part] leaks/services.py" in result.output
    assert "frontend/src/leaks/index.ts:2" in result.output
