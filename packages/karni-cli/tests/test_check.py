from __future__ import annotations

import subprocess
from pathlib import Path

import karni_cli.commands.check as check_mod
from karni_cli import project as project_mod
from karni_cli.main import app


def _fake_run(returncode: int):
    def fake(project, args, **kwargs):
        assert args == ["karni_check"]
        assert kwargs.get("capture") is False
        return subprocess.CompletedProcess(args, returncode)

    return fake


def test_exit_code_aggregates_backend_and_frontend(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 0)
    assert runner.invoke(app, ["check"]).exit_code == 0

    monkeypatch.setattr(project_mod, "run_manage", _fake_run(1))
    assert runner.invoke(app, ["check"]).exit_code == 1

    # frontend failure alone must fail, and the backend step still ran
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 1)
    assert runner.invoke(app, ["check"]).exit_code == 1


def test_no_frontend_flag_skips_duplication(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    called = []
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: called.append(p) or 1)
    assert runner.invoke(app, ["check", "--no-frontend"]).exit_code == 0
    assert called == []


def test_missing_jscpd_fails_with_instructions(tmp_path: Path) -> None:
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    assert check_mod._frontend_duplication(tmp_path) == 1


def test_no_frontend_dir_is_clean(tmp_path: Path) -> None:
    assert check_mod._frontend_duplication(tmp_path) == 0


def test_bare_ignore_marker_fails(tmp_path: Path) -> None:
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    bin_dir = tmp_path / "frontend" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "jscpd").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "jscpd").chmod(0o755)
    (src / "page.tsx").write_text("// jscpd:ignore-start\nconst x = 1;\n// jscpd:ignore-end\n")
    assert check_mod._frontend_duplication(tmp_path) == 1
    (src / "page.tsx").write_text(
        "// jscpd:ignore-start -- vendor snippet kept verbatim\nconst x = 1;\n// jscpd:ignore-end\n"
    )
    assert check_mod._frontend_duplication(tmp_path) == 0


def test_check_outside_project_errors(runner, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code != 0
