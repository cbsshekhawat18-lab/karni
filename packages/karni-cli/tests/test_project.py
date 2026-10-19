from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from karni_cli import project as project_mod
from karni_cli.project import (
    CliError,
    find_project,
    resolve_execution,
    run_manage,
    venv_python,
)


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "manage.py").write_text("# manage\n")
    return tmp_path


def test_find_project_walks_up(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    nested = project / "frontend" / "src"
    nested.mkdir(parents=True)
    assert find_project(nested) == project


def test_find_project_none(tmp_path: Path) -> None:
    assert find_project(tmp_path) is None


def test_resolve_prefers_venv(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    assert resolve_execution(project, None, "django") == "venv"
    assert venv_python(project) == python


def test_venv_python_falls_back_to_the_active_virtualenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    assert venv_python(project) is None
    active = tmp_path / "shared-venv"
    (active / "bin").mkdir(parents=True)
    (active / "bin" / "python").write_text("")
    monkeypatch.setenv("VIRTUAL_ENV", str(active))
    assert venv_python(project) == active / "bin" / "python"
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "missing"))
    assert venv_python(project) is None


def test_resolve_falls_back_to_running_compose(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: True)
    assert resolve_execution(project, None, "django") == "docker"


def test_resolve_errors_with_both_remedies(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    with pytest.raises(CliError) as exc:
        resolve_execution(project, None, "django")
    message = str(exc.value)
    assert "docker compose up" in message and "venv" in message


def test_explicit_docker_requires_running_service(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    with pytest.raises(CliError, match="not running"):
        resolve_execution(project, True, "django")


def test_run_manage_docker_command_shape(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: True)
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(project_mod, "run_process", fake_run)
    run_manage(project, ["karni_context"], docker=True, service="web")
    assert captured["cmd"][:6] == ["docker", "compose", "exec", "-T", "web", "python"]
    assert captured["cmd"][-1] == "karni_context"
    assert captured["cwd"] == project
