"""From a design to loaded rows in a scaffolded project, for real.

``karni new``, the models ``karni design analyze`` proposes (its commands as
printed, every decision kept), ``karni migrate``, ``karni design extract``,
then ``karni load`` through the project's interpreter on SQLite: the content
loads with its images and children, a second load and a fresh extract plus
load change nothing, a dry run lists what would change row by row, an invalid
row rolls everything back, and ``karni seed`` refuses the tables that now
hold real content.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli.main import app

from .conftest import TEMPLATE
from .test_make import ok
from .test_make_gate import _karni_importable, _project_interpreter

DESIGNS = Path(__file__).parent / "fixtures" / "designs"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Content Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "content_check"
    monkeypatch.chdir(root)
    return root


def _manage(python: Path, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "manage.py", *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(project)},
    )


def _load(python: Path, project: Path, *args: str) -> dict[str, Any]:
    proc = _manage(python, project, "karni_load", "content/site.json", "--json", *args)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    return json.loads(proc.stdout[proc.stdout.index("{") :])


def _models_with_decisions(analysis: dict[str, Any]) -> dict[str, list[str]]:
    """Every decision kept: each field a decision holds back, by model."""
    extra: dict[str, list[str]] = {}
    for model in analysis["models"]:
        for field in model["fields"]:
            if field.get("decide"):
                token = f"{field['name']}:{field['type']}{'?' if field['optional'] else ''}"
                extra.setdefault(model["name"], []).append(token)
    return extra


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
@pytest.mark.parametrize("design", ["school", "patisserie", "studio"])
def test_extract_then_load_fills_a_project_and_loading_again_changes_nothing(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, design: str
) -> None:
    python = _project_interpreter(project, tmp_path, monkeypatch)
    ok("make", "app", "website")
    folder = str(DESIGNS / design)
    analysis = json.loads(
        ok(
            "design", "analyze", folder, "--app", "website", "--json",
            "--map", "content/design-map.json",
        ).output
    )  # fmt: skip
    for command in analysis["commands"]:
        ok(*shlex.split(command)[1:])
    # Keep every decision: the field joins its model (once the models it names exist) and the
    # map keeps the value.
    for name, tokens in _models_with_decisions(analysis).items():
        command = next(c for c in analysis["commands"] if c.split()[3] == name)
        args = shlex.split(command)[1:]
        at = args.index("--app")
        ok(*args[:at], *tokens, *args[at:], "--force")
    mapped = json.loads((project / "content" / "design-map.json").read_text())
    for model in mapped["models"]:
        for source in model.get("sources", []):
            for rule in source["values"].values():
                if isinstance(rule, dict):
                    rule.pop("decide", None)
    (project / "content" / "design-map.json").write_text(json.dumps(mapped, indent=2))
    ok("make", "migration", "--app", "website")
    ok("migrate")
    ok("design", "extract", folder, "--map", "content/design-map.json", "-o", "content/site.json")

    first = _load(python, project)
    assert first["changed"] and not first["problems"]
    rows = {label: counts["created"] for label, counts in first["models"].items()}
    files = sum(counts["files"] for counts in first["models"].values())
    if design == "school":
        assert rows == {"website.Teacher": 3, "website.Course": 4, "website.CourseImage": 8}
        assert files == 3 + 4 + 8
    elif design == "patisserie":
        assert rows == {"website.Menu": 3, "website.MenuItem": 8} and files == 8
    else:  # slides on two pages, the founder's card as one more member, filter buttons
        assert rows == {
            "website.Slide": 5,
            "website.Member": 4,
            "website.ProjectType": 3,
            "website.Project": 4,
            "website.ProjectImage": 6,
        }
        assert files == 5 + 4 + 4 + 6
    second = _load(python, project)
    assert not second["changed"]
    again = ok(
        "design", "extract", folder, "--map", "content/design-map.json", "-o", "content/site.json"
    )
    assert "The content is unchanged since the last extract." in again.output
    assert not _load(python, project)["changed"]

    # A changed value: the dry run says which row and field would change, and writes nothing.
    content_file = project / "content" / "site.json"
    content = json.loads(content_file.read_text())
    label = next(name for name, rows in content.items() if "title" in rows[0])
    content[label][0]["title"] = "A new title"
    content_file.write_text(json.dumps(content))
    for _ in range(2):
        dry = _load(python, project, "--dry-run")
        (change,) = dry["models"][label]["changes"]
        assert change["status"] == "updated"
        assert change["fields"]["title"][1] == "'A new title'"

    # An invalid row (a required title left empty) rolls the whole load back: the valid
    # change in the same file is not written either.
    title = content[label][1]["title"]
    content[label][1]["title"] = ""
    content_file.write_text(json.dumps(content))
    failed = _manage(python, project, "karni_load", "content/site.json")
    output = failed.stdout + failed.stderr
    assert (
        failed.returncode != 0
        and "E805" in output
        and "title: This field may not be blank" in output
    )
    content[label][1]["title"] = title
    content_file.write_text(json.dumps(content))
    pending = _load(python, project, "--dry-run")["models"][label]["changes"]
    assert [c["fields"]["title"][1] for c in pending] == ["'A new title'"]

    # Seed refuses the tables that hold the real content now.
    model = label.split(".", 1)[1]
    seeded = _manage(python, project, "karni_seed", "--model", f"website.{model}")
    assert seeded.returncode != 0 and "E617" in seeded.stdout + seeded.stderr
