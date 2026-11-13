"""The matrix test: every connection a recipe declares has a test with it on and one with it off.

A connection is declared in a recipe's ``<app>/connections.py`` with
``preferences.connection("<name>", needs=[...])`` (docs/family.md). Each recipe's own tests
(``files/<app>/tests/``) must show both states:

- off: a test function that runs inside ``preferences.override(connections={"<name>": False})``
  and asserts afterwards,
- on: a test function that mentions the name and asserts before it (or without any
  override), outside an ``if`` guard such as the "alone" early return.

A connection's ``needs`` names contracts and modules, never another recipe. The checker is a
plain function over a recipe's folder, so the tests below run it on a recipe that breaks each
rule. A recipe that joins the family (the shop, later) is covered as soon as it has a
``connections.py``.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

from karni_cli import recipes as recipes_mod

from .test_family_build import TEST_RECIPES

BUILTIN = Path(recipes_mod.__file__).parent


@dataclass(frozen=True)
class Declared:
    name: str
    needs: tuple[str, ...]
    file: str


def _recipe_dirs() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (BUILTIN, TEST_RECIPES):
        for toml in sorted(base.glob("*/recipe.toml")):
            found[str(tomllib.loads(toml.read_text(encoding="utf-8"))["name"])] = toml.parent
    return found


def _strings(node: ast.AST) -> list[str]:
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def declared_connections(folder: Path) -> list[Declared]:
    """The connections a recipe's ``connections.py`` files declare."""
    found: list[Declared] = []
    files = folder / "files"
    for path in sorted(files.rglob("connections.py")) if files.is_dir() else []:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            first = node.args[0]
            if called != "connection" or not isinstance(first, ast.Constant):
                continue
            needs = next((kw.value for kw in node.keywords if kw.arg == "needs"), None)
            found.append(
                Declared(
                    str(first.value),
                    tuple(_strings(needs)) if needs is not None else (),
                    path.relative_to(files).as_posix(),
                )
            )
    return found


def _is_switched_off(node: ast.With, name: str) -> bool:
    """``with preferences.override(connections={"<name>": False})``."""
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            continue
        for keyword in call.keywords:
            if keyword.arg != "connections" or not isinstance(keyword.value, ast.Dict):
                continue
            for key, value in zip(keyword.value.keys, keyword.value.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == name
                    and isinstance(value, ast.Constant)
                    and value.value is False
                ):
                    return True
    return False


def _asserts(function: ast.FunctionDef) -> list[ast.Assert]:
    """The asserts of a test that are not inside an ``if`` (a guard is not a test of the state)."""
    found: list[ast.Assert] = []

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assert):
                found.append(statement)
            elif isinstance(statement, ast.If):
                continue
            elif isinstance(statement, ast.With | ast.For | ast.Try):
                for body in (statement.body, getattr(statement, "orelse", [])):
                    visit(body)
            # Everything else (a call, an assignment) holds no assert statement.

    visit(function.body)
    return found


def states_shown(connection: str, folder: Path) -> tuple[bool, bool]:
    """``(on, off)``: whether the recipe's tests show the connection on and off."""
    on = off = False
    tests = folder / "files"
    for path in sorted(tests.rglob("test_*.py")) if tests.is_dir() else []:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if not function.name.startswith("test_") or connection not in _strings(function):
                continue
            offs = [
                n
                for n in ast.walk(function)
                if isinstance(n, ast.With) and _is_switched_off(n, connection)
            ]
            asserts = _asserts(function)
            if not offs:
                on = on or bool(asserts)
                continue
            first = min(offs, key=lambda n: n.lineno)
            last = max(offs, key=lambda n: n.end_lineno or n.lineno)
            on = on or any(a.lineno < first.lineno for a in asserts)
            off = (
                off
                or any(a.lineno > (last.end_lineno or last.lineno) for a in asserts)
                or any(
                    first.lineno <= a.lineno <= (first.end_lineno or first.lineno) for a in asserts
                )
            )
    return on, off


def matrix_problems(folder: Path, recipe_names: set[str]) -> list[str]:
    """What is missing from one recipe's connections and tests, one line each."""
    problems: list[str] = []
    for connection in declared_connections(folder):
        on, off = states_shown(connection.name, folder)
        if not on:
            problems.append(f"{connection.name}: no test with the connection on")
        if not off:
            problems.append(f"{connection.name}: no test with the connection off")
        for need in connection.needs:
            if need in recipe_names:
                problems.append(
                    f"{connection.name}: needs {need!r}, a recipe. A connection needs "
                    "contracts and modules only"
                )
    return problems


def test_the_recipes_declare_connections() -> None:
    declared = {
        name: [c.name for c in declared_connections(folder)]
        for name, folder in _recipe_dirs().items()
    }
    assert declared["booking"] == ["bookings.family_events"]
    assert declared["crm"] == ["crm.deal_timeline"]
    assert declared["visits"] == ["visits.visit_events"]


def test_every_declared_connection_has_an_on_and_an_off_test() -> None:
    folders = _recipe_dirs()
    names = set(folders)
    problems = {name: matrix_problems(folder, names) for name, folder in folders.items()}
    assert {name: found for name, found in problems.items() if found} == {}


def _recipe(root: Path, connection: str, tests: str, needs: str = '["events"]') -> Path:
    (root / "files" / "demo" / "tests").mkdir(parents=True)
    (root / "files" / "demo" / "connections.py").write_text(
        f'from karni import preferences\n\npreferences.connection("{connection}", needs={needs})\n',
        encoding="utf-8",
    )
    (root / "files" / "demo" / "tests" / "test_family.py").write_text(tests, encoding="utf-8")
    return root


BOTH = """
def test_it(x):
    assert x.on("demo.link")
    with preferences.override(connections={"demo.link": False}):
        x.act()
    assert x.count() == 1
"""


OFF_ONLY = """
def test_off(x):
    with preferences.override(connections={"demo.link": False}):
        x.act()
    assert x.count() == 0
"""

ALONE_ONLY = """
def test_only_alone(x):
    if x.alone:
        assert not x.on("demo.link")
        return
    with preferences.override(connections={"demo.link": True}):
        x.act()
"""


def test_the_checker_accepts_one_test_that_shows_both_states(tmp_path: Path) -> None:
    folder = _recipe(tmp_path, "demo.link", BOTH)
    assert matrix_problems(folder, {"demo"}) == []


@pytest.mark.parametrize(
    ("tests", "needs", "expected"),
    [
        ("def test_nothing():\n    pass\n", '["events"]', ["on", "off"]),
        (
            'def test_on(x):\n    assert x.on("demo.link")\n',
            '["events"]',
            ["no test with the connection off"],
        ),
        (OFF_ONLY, '["events"]', ["no test with the connection on"]),
        (ALONE_ONLY, '["events"]', ["on", "off"]),
        (BOTH, '["crm"]', ["needs 'crm', a recipe"]),
    ],
)
def test_the_checker_names_what_is_missing(
    tmp_path: Path, tests: str, needs: str, expected: list[str]
) -> None:
    folder = _recipe(tmp_path, "demo.link", tests, needs)
    found = matrix_problems(folder, {"demo", "crm"})
    assert len(found) == len(expected)
    for line, part in zip(found, expected, strict=True):
        assert part in line
