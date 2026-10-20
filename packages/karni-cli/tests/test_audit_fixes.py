"""The launch audit's CLI findings, each pinned: --version, doctor paths, the interpreter
fallback, SIGTERM forwarding, the pytest hint, the upgrade baseline, ESLint in check."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import karni_cli.commands.doctor as doctor_mod
import karni_cli.commands.upgrade as upgrade_mod
from karni_cli import __version__
from karni_cli import project as project_mod
from karni_cli.commands.check import _frontend_lint
from karni_cli.main import app
from karni_cli.project import CliError, run_process, venv_python

# karni --version


def test_version_flag(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"karni-cli {__version__}"


# the interpreter running karni-cli

#: Captured at import, before the suite's autouse fixture stubs it out.
_REAL_RUNNING_INTERPRETER = project_mod._running_interpreter


def test_the_running_interpreter_is_the_last_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(project_mod, "_running_interpreter", _REAL_RUNNING_INTERPRETER)
    # This suite's interpreter has Django and karni: it counts (an MCP host that
    # inherited no VIRTUAL_ENV, the quickstart venv invoked by path).
    assert venv_python(project) == Path(sys.executable)
    assert project_mod.resolve_execution(project, None, "django") == "venv"


def test_an_interpreter_without_karni_does_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: None if name == "karni" else object()
    )
    assert _REAL_RUNNING_INTERPRETER() is None


# SIGTERM reaches the child


def test_run_process_forwards_sigterm(tmp_path: Path) -> None:
    code = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *a: sys.exit(7))\n"
        "time.sleep(30)\n"
    )
    threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    proc = run_process([sys.executable, "-c", code], cwd=tmp_path, capture=True)
    assert proc.returncode == 7
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL  # handler restored


def test_run_process_captures_output(tmp_path: Path) -> None:
    proc = run_process([sys.executable, "-c", "print('hi')"], cwd=tmp_path, capture=True)
    assert proc.returncode == 0 and proc.stdout.strip() == "hi"


# karni doctor with the venv outside the project (the quickstart's layout)


def test_doctor_shows_an_interpreter_outside_the_project(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "ticket_shop"
    project.mkdir()
    (project / "manage.py").write_text("")
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.chdir(project)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)
    monkeypatch.setattr(doctor_mod, "tool_version", lambda name: f"{name}-9.9.9")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert str(venv / "bin" / "python") in result.output


# karni test without pytest


def test_karni_test_names_the_missing_pytest(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "manage.py").write_text("")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)

    def no_pytest(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        code = 1 if cmd[-1] == "import pytest" else 0
        return subprocess.CompletedProcess(cmd, code, stdout="", stderr="No module named pytest")

    monkeypatch.setattr(project_mod, "run_process", no_pytest)
    result = runner.invoke(app, ["test"])
    assert isinstance(result.exception, CliError)
    assert result.exception.code == "C011" and "pip install pytest" in str(result.exception)


# karni upgrade starts from the scaffold's baseline


def test_upgrade_honours_the_baseline(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.karni]\nbaseline = "0.2.0"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upgrade_mod, "_installed_version", lambda *a: "0.1.0")
    result = runner.invoke(app, ["upgrade", "--dry-run"])
    assert result.exit_code == 0, result.output
    # From 0.2.0 only the deprecations that break in 1.0 remain; the 0.2.0
    # behaviour changes a fresh scaffold already follows are not reported.
    assert "karni 0.2.0 -> 0.3.0:" in result.output
    assert "mandatory-access" not in result.output and "23 change(s)" not in result.output
    # --from still wins over the baseline.
    result = runner.invoke(app, ["upgrade", "--from", "0.1.0", "--dry-run"])
    assert "karni 0.1.0 -> 0.3.0: 25 change(s)" in result.output


def test_baseline_reads_pyproject(tmp_path: Path) -> None:
    assert upgrade_mod._baseline(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("[tool.karni]\nbaseline = '0.3.0'\n")
    assert upgrade_mod._baseline(tmp_path) == "0.3.0"
    (tmp_path / "pyproject.toml").write_text("not = [toml")
    assert upgrade_mod._baseline(tmp_path) is None


# karni check runs ESLint


def test_frontend_lint_needs_eslint_and_uses_it(tmp_path: Path) -> None:
    assert _frontend_lint(tmp_path) == 0  # no frontend/
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    assert _frontend_lint(tmp_path) == 1  # frontend without node_modules
    bin_dir = frontend / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "eslint").write_text('#!/bin/sh\necho "$@" > eslint-args\nexit 2\n')
    (bin_dir / "eslint").chmod(0o755)
    assert _frontend_lint(tmp_path) == 2
    assert (frontend / "eslint-args").read_text().split() == [".", "--max-warnings", "0"]
