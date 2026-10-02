"""`karni doctor`, `karni config`, local state, CI detection and the one-time tip."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import karni_cli.commands.check as check_mod
import karni_cli.commands.doctor as doctor_mod
from karni_cli import config, local_state, tips
from karni_cli import project as project_mod
from karni_cli.environment import CI_ENV_VARS, is_ci
from karni_cli.main import app

from .test_history import BACKEND, fake_provider  # noqa: F401 - fixture re-export

TIP_FIRST_LINE = "tip: no prompt-history store found."


@pytest.fixture
def no_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_ci: None) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "manage.py").write_text("")
    monkeypatch.chdir(root)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)
    monkeypatch.setattr(doctor_mod, "tool_version", lambda name: f"{name}-9.9.9")
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 0)
    return root


def _state(project: Path) -> Path:
    return local_state.state_path(project)


# --- CI detection -------------------------------------------------------------------------


@pytest.mark.parametrize("name", CI_ENV_VARS)
def test_every_ci_variable_counts(name: str) -> None:
    assert is_ci({name: "true"})
    assert is_ci({name: "1"})
    assert not is_ci({name: "false"})
    assert not is_ci({name: ""})


def test_no_ci_variables_is_not_ci() -> None:
    assert not is_ci({})
    assert not is_ci({"CI": "0", "PATH": "/bin"})
    assert is_ci({"JENKINS_URL": "https://ci.example.com/"})


# --- karni doctor -------------------------------------------------------------------------


def test_doctor_reports_the_environment(runner, project: Path) -> None:
    result = runner.invoke(app, ["doctor", "-q"])
    assert result.exit_code == 0, result.output
    labels = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    assert labels == ["project", "interpreter", "node", "ui", "adapters", "history"]
    assert "node-9.9.9 (npm npm-9.9.9)" in result.stdout
    assert "manifest absent" in result.stdout
    assert "stale (24 files)" in result.stdout  # no adapters generated in this bare project
    assert "no store detected (installed: gigai-chronicle)" in result.stdout
    assert TIP_FIRST_LINE not in result.output


def test_doctor_lists_a_detected_store(runner, project: Path) -> None:
    (project / ".chronicle").mkdir()
    out = runner.invoke(app, ["doctor"]).stdout
    assert "gigai-chronicle: store detected" in out
    assert TIP_FIRST_LINE not in out  # a provider is present: no tip


def test_doctor_outside_a_project(runner, tmp_path: Path, monkeypatch, no_ci) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor_mod, "tool_version", lambda name: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "not found" in result.stdout and TIP_FIRST_LINE not in result.output


# --- the tip --------------------------------------------------------------------------------


def test_tip_text_discloses_authorship_and_how_to_silence() -> None:
    assert tips.HISTORY_TIP == (
        "tip: no prompt-history store found. `karni context --with-history` can brief\n"
        "     an agent with what was already asked about a file. Works with Gigai\n"
        "     Chronicle (MIT, local-only, by Karni's author).\n"
        "     Silence this: karni config set suggest_tools false"
    )


def test_tip_appears_exactly_once_per_project(runner, project: Path) -> None:
    first = runner.invoke(app, ["doctor"])
    assert first.stdout.count(TIP_FIRST_LINE) == 1
    assert first.stdout.rstrip().endswith("Silence this: karni config set suggest_tools false")
    assert "history-provider" in _state(project).read_text()
    for args in (["doctor"], ["check"], ["doctor"]):
        again = runner.invoke(app, args)
        assert TIP_FIRST_LINE not in again.output, args


def test_tip_state_is_local_and_untracked(runner, project: Path) -> None:
    runner.invoke(app, ["doctor"])
    local = project / ".karni" / "local"
    assert (local / ".gitignore").read_text().splitlines()[-1] == "*"
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "manage.py" in status and ".karni/local" not in status
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".karni/local/state.json"], cwd=project, check=False
    )
    assert ignored.returncode == 0


def test_scaffold_ignores_local_state() -> None:
    from .conftest import TEMPLATE

    gitignore = TEMPLATE / "{{cookiecutter.project_slug}}" / ".gitignore"
    assert ".karni/local/" in gitignore.read_text().splitlines()


def test_check_prints_the_tip_on_stderr_only(runner, project: Path) -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert TIP_FIRST_LINE in result.stderr and TIP_FIRST_LINE not in result.stdout


def test_failing_check_keeps_the_tip_for_later(runner, project: Path, monkeypatch) -> None:
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 1)
    failed = runner.invoke(app, ["check"])
    assert failed.exit_code == 1 and TIP_FIRST_LINE not in failed.output
    assert not _state(project).exists()


@pytest.mark.parametrize("name", ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL"])
@pytest.mark.parametrize("command", ["doctor", "check"])
def test_never_in_ci(runner, project: Path, monkeypatch, name: str, command: str) -> None:
    monkeypatch.setenv(name, "true")
    result = runner.invoke(app, [command])
    assert TIP_FIRST_LINE not in result.output
    assert not _state(project).exists()


@pytest.mark.parametrize("command", ["doctor", "check"])
def test_quiet_flag_suppresses(runner, project: Path, command: str) -> None:
    for flag in ("-q", "--quiet"):
        assert TIP_FIRST_LINE not in runner.invoke(app, [command, flag]).output
    assert not _state(project).exists()


def test_suggest_tools_false_suppresses(runner, project: Path) -> None:
    assert runner.invoke(app, ["config", "set", "suggest_tools", "false"]).exit_code == 0
    assert TIP_FIRST_LINE not in runner.invoke(app, ["doctor"]).output
    assert not _state(project).exists()


def test_global_suggest_tools_false_suppresses(runner, project: Path) -> None:
    assert runner.invoke(app, ["config", "set", "--global", "suggest_tools", "off"]).exit_code == 0
    assert TIP_FIRST_LINE not in runner.invoke(app, ["doctor"]).output


def test_a_third_party_provider_suppresses(runner, project: Path, fake_provider) -> None:  # noqa: F811
    assert TIP_FIRST_LINE not in runner.invoke(app, ["doctor"]).output
    assert not _state(project).exists()


def test_unwritable_state_means_no_tip(project: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_state, "write_state", lambda *a: False)
    assert tips.history_tip(project) is None  # could not record it: never risk a repeat


def test_never_on_machine_output_commands(runner, project: Path, monkeypatch, tmp_path) -> None:
    called: list[object] = []

    def spy(*args: object, **kwargs: object) -> str:
        called.append(args)
        return "TIP"

    monkeypatch.setattr(tips, "history_tip", spy)
    for args in (
        ["context"],
        ["context", "--with-history"],
        ["rules"],
        ["rules", "--json"],
        ["types"],  # stops early (no schema here), never reaching any tip
    ):
        result = runner.invoke(app, args)
        assert "TIP" not in result.output and TIP_FIRST_LINE not in result.output, args
    from .conftest import TEMPLATE

    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    created = runner.invoke(app, ["new", "Tipless", "-o", str(tmp_path / "out")])
    assert created.exit_code == 0, created.output
    assert "TIP" not in created.output and TIP_FIRST_LINE not in created.output
    assert not (tmp_path / "out" / "tipless" / ".karni" / "local").exists()
    assert called == []
    assert not _state(project).exists()
    for name in ("context", "types", "rules", "new"):
        module = importlib.import_module(f"karni_cli.commands.{name}")
        assert "tips" not in vars(module), name  # these modules cannot even reach it


# --- karni config -----------------------------------------------------------------------------


def test_config_defaults_set_get_list(runner, project: Path) -> None:
    assert runner.invoke(app, ["config", "get", "suggest_tools"]).stdout == "true\n"
    assert "suggest_tools = true  # default" in runner.invoke(app, ["config", "list"]).stdout

    set_global = runner.invoke(app, ["config", "set", "--global", "suggest_tools", "false"])
    assert set_global.exit_code == 0
    assert config.global_path().read_text().strip() == "suggest_tools = false"
    assert runner.invoke(app, ["config", "get", "suggest_tools"]).stdout == "false\n"

    (project / ".karni").mkdir()
    (project / ".karni" / "config.toml").write_text("# team settings\n")
    assert runner.invoke(app, ["config", "set", "suggest_tools", "yes"]).exit_code == 0
    text = (project / ".karni" / "config.toml").read_text()
    assert "# team settings" in text and "suggest_tools = true" in text  # comments kept
    assert runner.invoke(app, ["config", "get", "suggest_tools"]).stdout == "true\n"  # project wins
    got_global = runner.invoke(app, ["config", "get", "--global", "suggest_tools"])
    assert got_global.stdout == "false\n"
    listed = runner.invoke(app, ["config", "list"]).stdout
    assert "suggest_tools = true  # project: .karni/config.toml" in listed


def test_config_honours_xdg_config_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.global_path() == tmp_path / "xdg" / "karni" / "config.toml"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert config.global_path() == tmp_path / "home" / ".config" / "karni" / "config.toml"


def test_config_validates_keys_and_values(runner, project: Path, tmp_path, monkeypatch) -> None:
    for args in (
        ["config", "set", "suggest_tools", "maybe"],
        ["config", "set", "no_such_key", "true"],
        ["config", "get", "no_such_key"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code != 0, args
    (project / ".karni").mkdir()
    (project / ".karni" / "config.toml").write_text('suggest_tools = "no"\n')
    bad = runner.invoke(app, ["config", "get", "suggest_tools"])
    assert bad.exit_code != 0 and "must be true or false" in str(bad.exception)
    assert tips.history_tip(project) is None  # a broken config never produces a tip

    monkeypatch.chdir(tmp_path)
    outside = runner.invoke(app, ["config", "set", "suggest_tools", "false"])
    assert outside.exit_code != 0 and "--global" in str(outside.exception)


def test_adding_a_setting_is_one_entry() -> None:
    assert set(config.KEYS) == {"suggest_tools"}
    spec = config.KEYS["suggest_tools"]
    assert spec.default is True and spec.help


def test_local_state_survives_corruption(project: Path) -> None:
    path = _state(project)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert local_state.read_state(project) == {}
    assert local_state.mark_tip_shown(project, "x")
    assert local_state.tip_shown(project, "x")
    assert sys.platform == "win32" or not list(path.parent.glob(".state-*"))  # no temp leftovers
