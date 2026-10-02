from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from karni_cli.commands import add as add_command
from karni_cli.project import CliError
from karni_cli.settings_edit import add_app

FRAGMENT = "## Payments\n- go through karni_payments.services\n"


@pytest.fixture
def no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the fragment-read resolution away from a real docker daemon."""
    monkeypatch.setattr(add_command, "compose_service_running", lambda project, service: False)


@pytest.fixture
def project_venv(generated_project: Path) -> Path:
    """A fake project .venv python so the fragment read picks the venv path."""
    python = generated_project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    return python


@pytest.fixture
def mocked_fragment_subprocess(monkeypatch: pytest.MonkeyPatch):
    """Replace subprocess.run in the add command; records the commands run."""
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, 0, stdout=FRAGMENT, stderr="")

    monkeypatch.setattr(add_command.subprocess, "run", fake_run)
    return calls


def test_add_into_generated_project(
    runner, generated_project: Path, monkeypatch, no_docker
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output
    settings = (generated_project / "config" / "settings.py").read_text()
    assert '"karni_payments",' in settings
    pyproject = (generated_project / "pyproject.toml").read_text()
    assert "karni-payments" in pyproject

    # idempotent second run
    again = runner.invoke(app, ["add", "payments"])
    assert again.exit_code == 0
    assert settings.count('"karni_payments"') == (
        (generated_project / "config" / "settings.py").read_text().count('"karni_payments"')
    )
    assert "already in" in again.output


def test_add_prints_the_urls_include_line(
    runner, generated_project: Path, monkeypatch, no_docker
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output
    assert 'path("payments/", include("karni_payments.urls"))' in result.output


def test_add_without_installed_module_prints_run_again_hint(
    runner, generated_project: Path, monkeypatch, no_docker
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output
    assert "run `karni add payments` again after installing" in result.output
    assert "karni:module:payments" not in (generated_project / "AGENTS.md").read_text()
    assert not (generated_project / ".karni" / "modules").exists()


def test_add_merges_agents_fragment_through_project_interpreter(
    runner,
    generated_project: Path,
    monkeypatch,
    no_docker,
    project_venv: Path,
    mocked_fragment_subprocess,
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output

    # Read through the PROJECT interpreter (the .venv python), never the CLI's.
    [command] = mocked_fragment_subprocess
    assert command[0] == str(project_venv)
    assert "importlib.resources" in command[2]
    assert "karni_payments" in command[2]

    # Recorded in the project (source of truth for module guidance) ...
    recorded = generated_project / ".karni" / "modules" / "payments.md"
    assert recorded.read_text() == FRAGMENT
    # ... and rendered into the canonical adapters between markers.
    for rel in ("AGENTS.md", ".junie/AGENTS.md"):
        agents = (generated_project / rel).read_text()
        assert "<!-- karni:module:payments -->" in agents
        assert "<!-- /karni:module:payments -->" in agents
        assert "go through karni_payments.services" in agents
        assert "karni context" in agents  # the generated guidance is still there
    # Tool-specific thin adapters stay thin; the CLI carries the guidance.
    assert "karni_payments" not in (generated_project / ".cursor/rules/karni.mdc").read_text()
    rules = runner.invoke(app, ["rules"])
    assert rules.exit_code == 0, rules.output
    assert "[module:payments]" in rules.output
    assert "go through karni_payments.services" in rules.output


def test_agents_fragment_merge_is_idempotent(
    runner,
    generated_project: Path,
    monkeypatch,
    no_docker,
    project_venv: Path,
    mocked_fragment_subprocess,
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    first = (generated_project / "AGENTS.md").read_text()
    assert runner.invoke(app, ["add", "payments"]).exit_code == 0
    second = (generated_project / "AGENTS.md").read_text()
    assert first == second
    assert second.count("<!-- karni:module:payments -->") == 1


def test_fragment_update_replaces_the_recorded_guidance(generated_project: Path) -> None:
    from karni_cli.adapters import module_fragments

    assert add_command.record_module_fragment(generated_project, "payments", "old guidance\n")
    assert add_command.record_module_fragment(generated_project, "payments", "new guidance\n")
    assert not add_command.record_module_fragment(generated_project, "payments", "new guidance")
    assert module_fragments(generated_project) == {"payments": "new guidance"}


def test_failing_subprocess_falls_back_to_the_hint(
    runner, generated_project: Path, monkeypatch, no_docker, project_venv: Path
) -> None:
    from karni_cli.main import app

    def failing_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="ModuleNotFoundError")

    monkeypatch.setattr(add_command.subprocess, "run", failing_run)
    monkeypatch.chdir(generated_project)
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output
    assert "run `karni add payments` again after installing" in result.output


def test_commented_entry_is_not_a_match(tmp_path: Path) -> None:
    settings = tmp_path / "settings.py"
    settings.write_text(
        'INSTALLED_APPS += [  # noqa: F821\n    # "karni_payments",\n]  # karni:apps\n'
    )
    assert add_app(settings, "karni_payments") is True
    text = settings.read_text()
    assert '    "karni_payments",\n' in text
    assert add_app(settings, "karni_payments") is False


def test_single_line_shape_rewritten(tmp_path: Path) -> None:
    settings = tmp_path / "settings.py"
    settings.write_text('INSTALLED_APPS += ["existing_app"]  # karni:apps\n')
    assert add_app(settings, "karni_payments") is True
    text = settings.read_text()
    assert '"existing_app",' in text and '"karni_payments",' in text
    assert text.rstrip().endswith("]  # karni:apps")


def test_missing_marker_errors(tmp_path: Path) -> None:
    settings = tmp_path / "settings.py"
    settings.write_text("INSTALLED_APPS += []\n")
    with pytest.raises(CliError, match="karni:apps"):
        add_app(settings, "karni_payments")


def test_unrecognized_shape_errors(tmp_path: Path) -> None:
    settings = tmp_path / "settings.py"
    settings.write_text("WEIRD = 1  # karni:apps\n")
    with pytest.raises(CliError, match="manually"):
        add_app(settings, "karni_payments")
