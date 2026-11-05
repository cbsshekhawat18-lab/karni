"""The /new-app flow (experimental), end to end, with a scripted fake agent and no language model.

From a one-line request in a fresh ``karni new`` project, the fake agent
calls the MCP tool functions in the flow's order: ``recipes`` (match, or the
blank start), the spec written with what the request asks for,
``spec_validate``, ``questions`` and ``answer`` (each with its default, as a
user who leaves them to the agent), ``plan`` and ``build``. Then it writes
one domain method in a project-owned file and a test of its own, and the
flow is done when ``karni check`` and the project's tests pass.

The project runs on SQLite and a local-memory cache, with no Redis and no
npm, as ``karni build``'s from-empty test sets it up (tests/test_build.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import agent_tools, mcp_server
from karni_cli import project as project_mod
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE
from .test_build import _env, _files, _frontend

ASSETS = REPO_ROOT / "docs" / "assets"
MCP_SCHEMA = ASSETS / "karni-mcp.schema.json"

REQUEST = "a reading log where each reader tracks the novels they finished"
#: What the fake agent understands from the request: the part of karni.yaml it writes.
UNDERSTOOD = """\
apps:
  books:
    entities:
      Book:
        fields: {title: "str:200", author: "str:120", reader: fk:User, finished_on: "date?"}
"""
#: The one piece of domain logic karni.yaml cannot express, in the project's own file.
METHOD = '''
    def is_finished(self) -> bool:
        """A novel counts as read once it has a finish date."""
        return self.finished_on is not None
'''
OWN_TEST = '''"""The reading log's own rule, beside the tests karni build writes."""

import datetime

from books.models import Book


def test_a_novel_is_finished_once_it_has_a_finish_date() -> None:
    book = Book(title="Dune", author="Frank Herbert")
    assert not book.is_finished()
    book.finished_on = datetime.date(2026, 10, 1)
    assert book.is_finished()
'''


@dataclass
class Flow:
    root: Path
    #: Every result each tool returned, in order.
    results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Each step of the flow and the seconds it took.
    steps: list[tuple[str, float]] = field(default_factory=list)
    #: The output of karni test and karni check at the end.
    test: str = ""
    check: str = ""

    def call(self, tool: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        result = call()
        self.results.setdefault(tool, []).append(result)
        return result


def _as_text(question: dict[str, Any]) -> str:
    """The question's default as karni spec answer takes it (its first option when none)."""
    default = question["default"]
    if default is None and question["options"]:
        default = question["options"][0]["value"]
    if isinstance(default, list):
        return ",".join(str(item) for item in default)
    if isinstance(default, bool):
        return "true" if default else "false"
    return str(default)


def _agent(flow: Flow, request: str) -> None:
    """The fake agent: the new-app procedure, step by step, through the MCP tool functions."""
    root = flow.root
    started = time.perf_counter()

    def step(name: str) -> None:
        nonlocal started
        now = time.perf_counter()
        flow.steps.append((name, now - started))
        started = now

    # 1. the closest recipe, or the blank start, and what the request asks for
    found = flow.call("recipes", lambda: mcp_server.recipes_tool(match=request))
    assert found["recipes"] == [], "pick a request no recipe covers: this agent starts blank"
    (root / "karni.yaml").write_text(found["blank"]["spec"] + UNDERSTOOD)
    assert flow.call("spec_validate", mcp_server.spec_validate_tool)["valid"]
    step("recipes and the spec written")
    # 2 and 3. only the questions karni plan --questions asks, each with its default
    while True:
        asked = flow.call("questions", mcp_server.questions_tool)
        if not asked["questions"]:
            break
        for question in asked["questions"]:
            value = _as_text(question)
            flow.call("answer", partial(mcp_server.answer_tool, question["id"], value))
    step("questions and answers")
    # 4. the plan
    planned = flow.call("plan", mcp_server.plan_tool)
    assert planned["valid"] and planned["summary"]["risky"] == 0, planned
    step("plan")
    # 5. the build
    built = flow.call("build", mcp_server.build_tool)
    assert built["status"] == "built", json.dumps(built, indent=2)
    step("build")
    # 6. the domain logic left, where the project owns the code
    models = root / "books" / "models.py"
    models.write_text(models.read_text().rstrip("\n") + "\n" + METHOD)
    (root / "books" / "tests" / "test_reading.py").write_text(OWN_TEST)
    step("domain method")
    # 7. done when karni check and the tests are green
    # (karni test runs the same pytest, streamed: captured here to read its summary)
    tested = project_mod.run_python(root, ["-m", "pytest", "-q", "-p", "no:cacheprovider"])
    assert tested.returncode == 0, tested.stdout + tested.stderr
    flow.test = tested.stdout
    checked = CliRunner().invoke(app, ["check"])
    assert checked.exit_code == 0, checked.output
    flow.check = checked.output
    step("karni test and karni check")


@pytest.fixture(scope="module")
def flow(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Flow]:
    """A fresh ``karni new`` project, then the fake agent's whole flow."""
    from karni_cli import scaffold

    parent = tmp_path_factory.mktemp("new-app")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KARNI_TEMPLATES", str(TEMPLATE))
        mp.setattr(
            scaffold,
            "run_npm",
            lambda argv, cwd: subprocess.CompletedProcess(argv, 127, "", "npm disabled"),
        )
        started = time.perf_counter()
        created = CliRunner().invoke(app, ["new", "Reading Log", "-o", str(parent)])
        assert created.exit_code == 0, created.output
        assert "/new-app <the app in one line>" in created.output
        root = parent / "reading_log"
        _env(mp, root)
        _frontend(mp)
        mp.setattr(mcp_server, "_project_override", root)
        result = Flow(root)
        result.steps.append(("karni new", time.perf_counter() - started))
        _agent(result, REQUEST)
        yield result


@pytest.fixture(autouse=True)
def _project_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The project runs on the suite's interpreter (the conftest turns that off per test)."""
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))


def test_one_line_to_a_green_build(flow: Flow) -> None:
    root = flow.root
    spec = (root / "karni.yaml").read_text()
    # the blank start, what the request asks for, and the answers, nothing else
    assert spec.startswith("# yaml-language-server: $schema=")
    assert "  name: Reading Log\n  kind: app\n" in spec
    assert "        owner: reader\n        access: {read: granted, write: granted}\n" in spec
    answered = [result["id"] for result in flow.results["answer"]]
    assert answered == ["books.Book.owner", "books.Book.access", "app.kind"]
    assert flow.results["answer"][-1]["next"] == "plan, then build: no question is open"
    assert flow.results["questions"][-1]["total"] == 0
    changes = {(c["area"], c["target"]) for c in flow.results["plan"][0]["changes"]}
    assert ("entities", "books.Book") in changes
    built = flow.results["build"][0]
    assert [(s["name"], s["status"]) for s in built["steps"]] == [
        ("modules", "skipped"),
        ("files", "done"),
        ("migrations", "done"),
        ("migrate", "done"),
        ("seed", "done"),
        ("types", "done"),
        ("test", "done"),
        ("check", "done"),
    ]
    assert (root / "books" / "karni" / "models.py").is_file()
    assert "def is_finished(self) -> bool:" in (root / "books" / "models.py").read_text()
    summary = flow.test.strip().splitlines()[-1]
    assert summary.startswith("5 passed"), flow.test  # karni build's 4 and the agent's own
    assert "failed" not in flow.test
    assert [name for name, _seconds in flow.steps] == [
        "karni new",
        "recipes and the spec written",
        "questions and answers",
        "plan",
        "build",
        "domain method",
        "karni test and karni check",
    ]
    print("\nthe /new-app flow, step by step:")  # shown with pytest -s
    for name, seconds in flow.steps:
        print(f"  {name:<30} {seconds:6.1f}s")
    print(f"  {'total':<30} {sum(seconds for _, seconds in flow.steps):6.1f}s")


def _validator(tool: str) -> Any:
    """A validator for ``$defs/<tool>`` of the MCP schema, the other published schemas resolved."""
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    schemas = [json.loads(path.read_text()) for path in sorted(ASSETS.glob("karni-*.schema.json"))]
    registry = referencing.Registry().with_resources(
        (schema["$id"], referencing.Resource.from_contents(schema)) for schema in schemas
    )
    return jsonschema.Draft202012Validator(
        {"$ref": f"{agent_tools.MCP_SCHEMA_URL}#/$defs/{tool}"}, registry=registry
    )


def test_the_published_mcp_schema_is_current() -> None:
    expected = json.dumps(agent_tools.json_schema(), indent=2) + "\n"
    assert MCP_SCHEMA.read_text() == expected, (
        "docs/assets/karni-mcp.schema.json is stale. Regenerate it: "
        "python -m karni_cli.agent_tools > docs/assets/karni-mcp.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(json.loads(MCP_SCHEMA.read_text()))
    assert set(agent_tools.TOOLS) <= set(mcp_server.TOOLS)


def test_every_tool_result_follows_its_schema(flow: Flow, tmp_path: Path) -> None:
    results = {tool: list(found) for tool, found in flow.results.items()}
    (tmp_path / "bad.yaml").write_text("version: 1\napp: {name: X, colour: red}\n")
    bad = str(tmp_path / "bad.yaml")
    extra: dict[str, list[dict[str, Any]]] = {
        "recipes": [
            mcp_server.recipes_tool(),
            mcp_server.recipes_tool(name="blank"),
            mcp_server.recipes_tool(name="nope"),
        ],
        "spec_validate": [mcp_server.spec_validate_tool(bad)],
        "questions": [mcp_server.questions_tool(bad), mcp_server.questions_tool(max=0)],
        "answer": [mcp_server.answer_tool("nope", "x"), mcp_server.answer_tool("x", "y", bad)],
        "plan": [mcp_server.plan_tool("missing.yaml"), mcp_server.plan_tool(bad)],
        "build": [mcp_server.build_tool(dry_run=True)],
        "modules": [
            mcp_server.modules_tool(),
            mcp_server.modules_tool("payments"),
            mcp_server.modules_tool("two_factor"),
            mcp_server.modules_tool("nope"),
        ],
    }
    for tool, found in extra.items():
        results.setdefault(tool, []).extend(found)
    assert set(results) == set(agent_tools.TOOLS)
    for tool, found in results.items():
        validator = _validator(tool)
        for result in found:
            errors = [error.message for error in validator.iter_errors(result)]
            assert not errors, (tool, result, errors)
    assert extra["recipes"][2]["error"]["code"] == "C420"
    assert extra["answer"][0]["error"]["code"] == "C400"
    assert extra["answer"][1]["valid"] is False and extra["answer"][1]["keys"] == []
    assert extra["plan"][0]["error"]["code"] == "C210"
    assert extra["plan"][1]["valid"] is False
    assert extra["build"][0].get("status") in ("nothing to build", "dry run"), extra["build"]
    assert extra["modules"][3]["error"]["code"] == "C313"
    assert "wiring" not in extra["modules"][2]["module"]  # a feature has none
    line = next(m for m in extra["modules"][0]["modules"] if m["name"] == "payments")
    assert set(line) == {"name", "kind", "status", "state", "purpose", "use_when"}


def test_build_through_mcp_refuses_a_hand_edit_and_asks_the_user(
    flow: Flow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "reading_log"
    shutil.copytree(flow.root, root, ignore=shutil.ignore_patterns("__pycache__"))
    _env(monkeypatch, root)
    monkeypatch.setattr(mcp_server, "_project_override", root)
    api = root / "books" / "karni" / "api.py"
    api.write_text(api.read_text() + "    search_fields = ('title',)\n")
    before = _files(root)
    refused = mcp_server.build_tool()
    assert refused["status"] == "refused" and refused["code"] == "C273"
    assert refused["hand_edits"][0]["path"] == "books/karni/api.py"
    next_ = refused["next"]
    assert next_.startswith("ask the user which of the three ways on to take.")
    assert "1. move the change into books/viewsets.py" in next_
    assert "2. karni build --force replaces it" in next_
    assert "3. karni build --adopt books/karni/api.py" in next_
    assert _files(root) == before  # nothing written
    assert not _validator("build").is_valid({**refused, "status": "forced"})
    assert _validator("build").is_valid(refused)
    # MCP's build takes no --force and no --adopt at all
    import inspect

    params = set(inspect.signature(mcp_server.build_tool).parameters)
    assert params == {"spec", "dry_run", "allow_destructive"}
