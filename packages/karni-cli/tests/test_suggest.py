"""``karni suggest`` and the suggestions in ``karni check`` and ``karni doctor`` (experimental)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import karni_cli.commands.check as check_mod
import karni_cli.commands.doctor as doctor_mod
from karni_cli import errorcodes, services
from karni_cli import project as project_mod
from karni_cli import suggest as suggest_mod
from karni_cli.main import app

from .conftest import REPO_ROOT

SCHEMA = REPO_ROOT / "docs" / "assets" / "karni-suggestions.schema.json"

CORE_ITEM = {
    "code": "SUG001",
    "rule": "suggest-tree-model",
    "file": "shop/models.py",
    "line": 7,
    "message": "Category.category_parent is a hand-written tree.",
    "fix": "inherit karni.models.TreeModel first",
    "command": None,
}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "shop"
    root.mkdir()
    (root / "manage.py").write_text("")
    (root / "config").mkdir()
    (root / "config" / "settings.py").write_text("DEBUG = True\n")
    monkeypatch.chdir(root)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)
    return root


def core_answer(items: list[dict[str, Any]], *, enabled: bool = True) -> Any:
    def fake(project: Path, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args == ["karni_suggest", "--json"]
        data = {"version": 1, "enabled": enabled, "suggestions": items}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(data), stderr="")

    return fake


def rules_of(data: dict[str, Any]) -> list[str]:
    return [item["code"] for item in data["suggestions"]]


# SUG006: a module the spec or the README describes


def test_a_use_when_phrase_in_the_readme_suggests_adding_the_module(project: Path) -> None:
    (project / "README.md").write_text("# Shop\n\nWe plan to start taking card payments soon.\n")
    (found,) = suggest_mod.module_suggestions(project)
    assert found["code"] == "SUG006" and found["rule"] == "suggest-add-module"
    assert (found["file"], found["line"]) == ("README.md", 3)
    assert found["command"] == "karni add payments"
    assert "karni add payments" in found["fix"] and "'taking card payments'" in found["message"]


def test_a_phrase_in_karni_yaml_suggests_adding_the_module(project: Path) -> None:
    (project / "karni.yaml").write_text(
        "version: 1\napp: {name: Shop, purpose: a public website}\n"
    )
    found = suggest_mod.module_suggestions(project)
    assert [(item["file"], item["command"]) for item in found] == [("karni.yaml", "karni add site")]


def test_no_phrase_a_listed_module_or_an_added_one_suggests_nothing(project: Path) -> None:
    (project / "README.md").write_text("# Shop\n\nA catalog of products. Payments elsewhere.\n")
    (project / "README.md").write_text("# Shop\n\nA catalog of products and suppliers.\n")
    assert suggest_mod.module_suggestions(project) == []
    # the spec already lists the module: karni plan is the place to read it
    (project / "karni.yaml").write_text("version: 1\nmodules: {payments: {}}\nnotes: payments\n")
    assert suggest_mod.module_suggestions(project) == []
    # the module is added: its app is in the karni:apps block
    (project / "karni.yaml").unlink()
    (project / "README.md").write_text("We start taking card payments.\n")
    (project / "config" / "settings.py").write_text(
        'INSTALLED_APPS += [\n    "karni_payments",\n]  # karni:apps\n'
    )
    assert suggest_mod.module_suggestions(project) == []
    # a phrase inside a longer word is not a match
    (project / "README.md").write_text("Our prepayments page.\n")
    assert suggest_mod.module_suggestions(project) == []
    # a single word is no signal in a README (checkout, payments), only in karni.yaml
    (project / "README.md").write_text("Update the local checkout, then payments.\n")
    assert suggest_mod.module_suggestions(project) == []
    (project / "config" / "settings.py").write_text("DEBUG = True\n")
    (project / "karni.yaml").write_text("version: 1\napp: {name: Shop, purpose: payments}\n")
    assert [i["file"] for i in suggest_mod.module_suggestions(project)] == ["karni.yaml"]


def test_a_module_suggestion_is_silenced_with_a_reason_only(project: Path) -> None:
    readme = project / "README.md"
    readme.write_text(
        "<!-- karni: allow(suggest-add-module): handled by the host app -->\nWe start taking card payments.\n"
    )
    assert suggest_mod.module_suggestions(project) == []
    readme.write_text("We start taking card payments.  # karni: allow(suggest-add-module):\n")
    (found,) = suggest_mod.module_suggestions(project)
    assert "without a reason" in found["message"]
    (project / "karni.yaml").write_text(
        "version: 1\n# karni: allow(suggest-add-module): the spec only describes it\n"
        "app: {name: Shop, purpose: a public website}\n"
    )
    readme.write_text("# Shop\n")
    assert suggest_mod.module_suggestions(project) == []


def test_a_text_that_already_names_the_module_or_a_project_that_has_it_is_left_alone(
    project: Path,
) -> None:
    readme = project / "README.md"
    # the scaffold's own README: it names the module and the command
    readme.write_text("A public website: `karni add site` adds it, on [karni-site](https://x).\n")
    assert suggest_mod.module_suggestions(project) == []
    # a site project has the module from the scaffold, outside the karni:apps block
    readme.write_text("A public website for the studio.\n")
    assert [item["command"] for item in suggest_mod.module_suggestions(project)] == [
        "karni add site"
    ]
    (project / "config" / "settings.py").write_text('INSTALLED_APPS = ["karni_site"]\n')
    assert suggest_mod.module_suggestions(project) == []
    (project / "config" / "settings.py").write_text("DEBUG = True\n")
    (project / "pyproject.toml").write_text('dependencies = ["karni-site>=0.5"]\n')
    assert suggest_mod.module_suggestions(project) == []


# SUG007: the project drifted from karni.yaml


def stub_plan(monkeypatch: pytest.MonkeyPatch, changes: list[Any]) -> None:
    from karni_cli.spec import export, plan

    monkeypatch.setattr(export, "read_facts", lambda *a, **k: {"databases": ["default"]})
    result = SimpleNamespace(changes=changes, not_managed=[c for c in changes if not c.managed])
    monkeypatch.setattr(plan, "plan_project", lambda *a, **k: result)


SPEC = "version: 1\napp: {name: Shop}\n"


def test_a_plan_with_changes_suggests_build_or_export(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "karni.yaml").write_text(SPEC)
    stub_plan(monkeypatch, [SimpleNamespace(managed=True), SimpleNamespace(managed=False)])
    (found,) = suggest_mod.drift_suggestions(project)
    assert (found["code"], found["file"], found["line"]) == ("SUG007", "karni.yaml", 1)
    assert "karni plan has 1 change:" in found["message"]  # the not managed one is not drift
    assert "karni build" in found["fix"] and "karni spec export" in found["fix"]


def test_facts_given_to_the_drift_check_start_no_second_django(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """karni check passes the facts manage.py karni_check wrote: karni_facts is not run again."""
    from karni_cli.spec import export

    (project / "karni.yaml").write_text(SPEC)
    stub_plan(monkeypatch, [SimpleNamespace(managed=True)])

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("manage.py karni_facts was started")

    monkeypatch.setattr(export, "read_facts", fail)
    (found,) = suggest_mod.drift_suggestions(project, facts={"databases": ["default"]})
    assert found["code"] == "SUG007"


def test_check_reads_the_facts_from_the_suggestions_file(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from karni_cli.commands import check as check_mod

    seen: dict[str, Any] = {}

    def collect(project: Path, core: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"suggestions": []}

    monkeypatch.setattr(suggest_mod, "collect", collect)
    file = project / "suggestions.json"
    file.write_text(json.dumps({"enabled": True, "suggestions": [], "facts": {"apps": []}}))
    check_mod._suggestions_block(project, file, docker=None, service="django")
    assert seen["facts"] == {"apps": []}
    assert not file.exists()
    file.write_text(json.dumps({"enabled": True, "suggestions": []}))  # an older karni
    check_mod._suggestions_block(project, file, docker=None, service="django")
    assert seen["facts"] is None


def test_changes_plan_calls_not_managed_are_no_drift(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Area 5 A5-07: a hand-written code page is plan's "not managed", not a SUG007."""
    (project / "karni.yaml").write_text(SPEC)
    stub_plan(monkeypatch, [SimpleNamespace(managed=False), SimpleNamespace(managed=False)])
    assert suggest_mod.drift_suggestions(project) == []


def test_an_empty_plan_no_spec_or_a_silenced_spec_suggests_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert suggest_mod.drift_suggestions(project) == []  # no karni.yaml
    (project / "karni.yaml").write_text(SPEC)
    stub_plan(monkeypatch, [])
    assert suggest_mod.drift_suggestions(project) == []
    stub_plan(monkeypatch, [SimpleNamespace(managed=True)])
    (project / "karni.yaml").write_text("# karni: allow(suggest-sync-spec): drafted ahead\n" + SPEC)
    assert suggest_mod.drift_suggestions(project) == []
    (project / "karni.yaml").write_text("# karni: allow(suggest-sync-spec):\n" + SPEC)
    (found,) = suggest_mod.drift_suggestions(project)
    assert "without a reason" in found["message"]


def test_a_spec_with_problems_or_an_unreadable_project_suggests_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "karni.yaml").write_text("version: 1\napp: [not, a, mapping\n")
    assert suggest_mod.drift_suggestions(project) == []
    (project / "karni.yaml").write_text(SPEC)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout="", stderr="boom"),
    )
    assert suggest_mod.drift_suggestions(project) == []


# the setting


def test_the_project_setting_turns_every_suggestion_off(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "README.md").write_text("We start taking card payments.\n")
    assert rules_of(suggest_mod.collect(project, (True, [CORE_ITEM]))) == ["SUG001", "SUG006"]
    settings = project / "config" / "settings.py"
    settings.write_text("DEBUG = True\nKARNI_SUGGESTIONS = False\n")
    assert suggest_mod.turned_off(project)
    data = suggest_mod.collect(project, (True, [CORE_ITEM]))
    assert data == {"version": 1, "enabled": False, "suggestions": [], "problems": []}
    # the project's karni says it is off even when the line is not a plain assignment
    settings.write_text("DEBUG = True\n")
    assert suggest_mod.collect(project, (False, []))["enabled"] is False


# the command


def test_karni_suggest_prints_the_block_and_exits_zero(
    runner: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "run_manage", core_answer([CORE_ITEM]))
    (project / "README.md").write_text("We start taking card payments.\n")
    result = runner.invoke(app, ["suggest"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "suggestions (2), they never fail the run:"
    assert "  [SUG001] shop/models.py:7: Category.category_parent is a hand-written tree." in lines
    assert "      fix: inherit karni.models.TreeModel first" in lines
    assert any(line.startswith("  [SUG006] README.md:1:") for line in lines)


def test_karni_suggest_says_none_and_off(
    runner: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "run_manage", core_answer([]))
    assert runner.invoke(app, ["suggest"]).stdout.strip() == "suggestions: none"
    monkeypatch.setattr(project_mod, "run_manage", core_answer([], enabled=False))
    assert "off (KARNI_SUGGESTIONS = False)" in runner.invoke(app, ["suggest"]).stdout


def test_karni_suggest_json_follows_the_published_schema(
    runner: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    monkeypatch.setattr(project_mod, "run_manage", core_answer([CORE_ITEM]))
    (project / "README.md").write_text("We start taking card payments.\n")
    result = runner.invoke(app, ["suggest", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["version"] == 1 and data["enabled"] is True
    assert rules_of(data) == ["SUG001", "SUG006"]
    published = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    jsonschema.Draft202012Validator(published).validate(data)
    assert set(data["suggestions"][0]) == {
        "code",
        "rule",
        "file",
        "line",
        "message",
        "fix",
        "command",
    }


def test_the_published_suggestions_schema_is_current() -> None:
    expected = json.dumps(suggest_mod.json_schema(), indent=2) + "\n"
    assert SCHEMA.read_text() == expected, (
        "docs/assets/karni-suggestions.schema.json is stale. Regenerate it: "
        "python -m karni_cli.suggest > docs/assets/karni-suggestions.schema.json"
    )


def test_a_karni_without_the_command_is_c780_and_the_rest_still_runs(
    runner: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, stdout="", stderr="Unknown command: 'karni_suggest'"
        ),
    )
    (project / "README.md").write_text("We start taking card payments.\n")
    result = runner.invoke(app, ["suggest"])
    assert result.exit_code == 0
    assert "C780" in result.output and "[SUG006]" in result.output
    assert errorcodes.lookup("C780") is not None and errorcodes.lookup("C781") is not None


def test_the_suggestion_codes_are_in_the_registry_karni_explain_reads(runner: Any) -> None:
    for number in range(1, 8):
        entry = errorcodes.lookup(f"SUG00{number}")
        assert entry is not None and entry["kind"] == "suggestion"
    result = runner.invoke(app, ["explain", "SUG005"])
    assert result.exit_code == 0 and "karni remove" in result.output


# karni check


def fake_backend(
    returncode: int, items: list[dict[str, Any]] | None, seen: dict[str, Any] | None = None
) -> Any:
    """``manage.py karni_check``: writes the suggestions file the CLI asks for, as it does."""

    def fake(project: Path, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        import os

        assert args == ["karni_check"]
        target = os.environ.get("KARNI_SUGGESTIONS_FILE")
        if seen is not None:
            seen["file"] = target
        if target and items is not None:
            data = {"version": 1, "enabled": True, "suggestions": items}
            (project / target).write_text(json.dumps(data))
        return subprocess.CompletedProcess(args, returncode)

    return fake


@pytest.fixture
def quiet_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 0)


def test_karni_check_prints_the_suggestions_after_the_verdict_and_keeps_its_exit_code(
    runner: Any, project: Path, quiet_frontend: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "README.md").write_text("We start taking card payments.\n")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(project_mod, "run_manage", fake_backend(0, [CORE_ITEM], seen))
    result = runner.invoke(app, ["check", "-q"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "karni check: ok"
    assert lines[1] == "suggestions (2), they never fail the run:"
    assert any("[SUG001] shop/models.py:7" in line for line in lines)
    assert any("[SUG006] README.md:1" in line for line in lines)
    assert seen["file"] == str(suggest_mod.SUGGESTIONS_FILE)
    assert not (project / suggest_mod.SUGGESTIONS_FILE).exists()  # read, then removed

    # a failing run fails the same way, and still ends with its suggestions
    monkeypatch.setattr(project_mod, "run_manage", fake_backend(1, [CORE_ITEM]))
    result = runner.invoke(app, ["check", "-q"])
    assert result.exit_code == 1
    assert "karni check: FAILED" in result.output and "[SUG001]" in result.output
    assert "karni check: ok" not in result.output


def test_karni_check_without_suggestions_prints_nothing_more(
    runner: Any, project: Path, quiet_frontend: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "run_manage", fake_backend(0, []))
    result = runner.invoke(app, ["check", "-q"])
    assert result.exit_code == 0 and result.stdout == "karni check: ok\n"


def test_a_karni_that_predates_suggestions_still_gets_the_cli_suggestions(
    runner: Any, project: Path, quiet_frontend: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "README.md").write_text("We start taking card payments.\n")
    monkeypatch.setattr(project_mod, "run_manage", fake_backend(0, None))  # no file written
    result = runner.invoke(app, ["check", "-q"])
    assert result.exit_code == 0
    assert "[SUG006] README.md:1" in result.stdout and "SUG001" not in result.stdout


def test_the_project_setting_stops_check_from_asking_for_suggestions(
    runner: Any, project: Path, quiet_frontend: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "config" / "settings.py").write_text("KARNI_SUGGESTIONS = False\n")
    (project / "README.md").write_text("We start taking card payments.\n")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(project_mod, "run_manage", fake_backend(0, [CORE_ITEM], seen))
    result = runner.invoke(app, ["check", "-q"])
    assert result.exit_code == 0 and result.stdout == "karni check: ok\n"
    assert seen["file"] is None


# karni doctor


def test_karni_doctor_ends_with_the_suggestions(
    runner: Any, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor_mod, "tool_version", lambda name: f"{name}-9.9.9")
    monkeypatch.setattr(services, "resolves", lambda host, timeout=0: False)
    monkeypatch.setattr(services, "speaks", lambda *a, **k: None)
    monkeypatch.setattr(project_mod, "run_manage", core_answer([CORE_ITEM]))
    result = runner.invoke(app, ["doctor", "-q"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert any(
        line.startswith("suggestions") and "1, they never fail a run" in line for line in lines
    )
    assert any("[SUG001] shop/models.py:7" in line for line in lines)

    monkeypatch.setattr(project_mod, "run_manage", core_answer([]))
    out = runner.invoke(app, ["doctor", "-q"]).stdout
    assert any(line.split()[:2] == ["suggestions", "none"] for line in out.splitlines())


def test_the_cli_reads_every_marker_and_a_colonless_one() -> None:
    line = "q()  # karni: allow(raw-sql): totals  # karni: allow(suggest-aggregate): one-off"
    assert suggest_mod._marker([line], "suggest-aggregate", (1,)) == "silenced"
    bare = ["x  # karni: allow(suggest-unused-module)"]
    assert suggest_mod._marker(bare, "suggest-unused-module", (1,)) == "no-reason"


def test_suggest_json_says_when_the_project_side_failed(runner, tmp_path, monkeypatch) -> None:
    """Area 1 F7: an empty list with exit 0 read as a clean project."""
    from karni_cli.project import CliError

    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)

    def broken(*args, **kwargs):
        raise CliError("manage.py karni_suggest failed", code="C781")

    monkeypatch.setattr(suggest_mod, "core_suggestions", broken)
    monkeypatch.setattr(suggest_mod, "module_suggestions", lambda p: [])
    monkeypatch.setattr(suggest_mod, "drift_suggestions", lambda p, **k: [])
    result = runner.invoke(app, ["suggest", "--json"])
    data = json.loads(result.stdout)
    assert data["suggestions"] == [] and "C781" in data["problems"][0]
