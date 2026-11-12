from __future__ import annotations

import subprocess
from pathlib import Path

import karni_cli.commands.check as check_mod
from karni_cli import project as project_mod
from karni_cli.main import app


def _fake_run(returncode: int, expected: list[str] | None = None):
    def fake(project, args, **kwargs):
        assert args == (expected or ["karni_check"])
        assert kwargs.get("capture") is False
        return subprocess.CompletedProcess(args, returncode)

    return fake


def test_deploy_passes_through_to_the_backend_check(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 0)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0, ["karni_check", "--deploy"]))
    result = runner.invoke(app, ["check", "--deploy"])
    assert result.exit_code == 0 and "karni check: ok" in result.output

    # a deploy finding (a warning there) fails the whole run
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(1, ["karni_check", "--deploy"]))
    result = runner.invoke(app, ["check", "--deploy"])
    assert result.exit_code == 1 and "karni check: FAILED" in result.output


def test_seo_passes_through_to_the_backend_check(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 0)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(1, ["karni_check", "--seo"]))
    result = runner.invoke(app, ["check", "--seo"])
    assert result.exit_code == 1 and "karni check: FAILED" in result.output
    both = ["karni_check", "--deploy", "--seo"]
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0, both))
    result = runner.invoke(app, ["check", "--seo", "--deploy"])
    assert result.exit_code == 0 and "karni check: ok" in result.output


def test_check_help_documents_deploy(runner) -> None:
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "--deploy" in result.output


def test_exit_code_aggregates_backend_and_frontend(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 0)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0 and "karni check: ok" in result.output

    # one verdict: a failing run never says "ok"
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(1))
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "karni check: ok" not in result.output

    # frontend failure alone must fail, and the backend step still ran
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 1)
    assert runner.invoke(app, ["check"]).exit_code == 1

    # an eslint failure alone (a raw <table> in a page) must fail too
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 1)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1 and "karni check: FAILED" in result.output


def test_no_frontend_flag_skips_duplication(runner, tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    called: list[Path] = []

    def fake_frontend(p: Path) -> int:
        called.append(p)
        return 1

    monkeypatch.setattr(check_mod, "_frontend_duplication", fake_frontend)
    assert runner.invoke(app, ["check", "--no-frontend"]).exit_code == 0
    assert called == []


def test_missing_jscpd_fails_with_instructions(tmp_path: Path, capsys) -> None:
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    assert check_mod._frontend_duplication(tmp_path) == 1
    err = capsys.readouterr().err
    assert "jscpd not installed" in err and "`npm install` in frontend/" in err
    assert "npm 10.8 or later" in err and "--no-frontend" in err


def test_missing_eslint_names_the_npm_floor(tmp_path: Path, capsys) -> None:
    (tmp_path / "frontend").mkdir()
    assert check_mod._frontend_lint(tmp_path) == 1
    err = capsys.readouterr().err
    assert "eslint not installed" in err and "`npm install` in frontend/" in err
    assert "npm 10.8 or later" in err and "--no-frontend" in err


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


def _fresh_frontend(tmp_path: Path, monkeypatch) -> None:
    """A project right after `karni new`: frontend/ without node_modules, outside CI."""
    from karni_cli.environment import CI_ENV_VARS

    (tmp_path / "manage.py").write_text("")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))


def test_a_fresh_frontend_is_skipped_with_the_exact_command(runner, tmp_path, monkeypatch) -> None:
    _fresh_frontend(tmp_path, monkeypatch)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "karni check: ok" in result.output
    assert "skipped: the frontend checks (eslint and jscpd) need frontend/node_modules" in (
        result.output
    )
    assert "`(cd frontend && npm install)`, which needs npm 10.8 or later" in result.output
    assert "npx" not in result.output
    assert result.output.count("frontend/node_modules") == 1  # one message, not one per tool


def test_a_missing_frontend_install_fails_in_ci_and_with_the_flag(
    runner, tmp_path, monkeypatch
) -> None:
    _fresh_frontend(tmp_path, monkeypatch)
    forced = runner.invoke(app, ["check", "--frontend"])
    assert forced.exit_code == 1 and "karni check: FAILED" in forced.output
    assert "`(cd frontend && npm install)`" in forced.output and "--no-frontend" in forced.output
    monkeypatch.setenv("CI", "true")
    in_ci = runner.invoke(app, ["check"])
    assert in_ci.exit_code == 1 and "karni check: FAILED" in in_ci.output
    skipped = runner.invoke(app, ["check", "--no-frontend"])
    assert skipped.exit_code == 0 and "node_modules" not in skipped.output


def test_the_build_check_step_agrees_with_karni_check(runner, tmp_path, monkeypatch) -> None:
    """F4: `karni build` ends in run_checks, which skips a missing install like `karni check`."""
    _fresh_frontend(tmp_path, monkeypatch)
    monkeypatch.setattr(
        project_mod, "run_manage", lambda *a, **k: subprocess.CompletedProcess([], 0, "ok", "")
    )
    passed, output = check_mod.run_checks(tmp_path)
    assert passed and "skipped: the frontend checks" in output
    assert "`(cd frontend && npm install)`" in output
    assert "not installed" not in output
    monkeypatch.setenv("CI", "true")
    passed, output = check_mod.run_checks(tmp_path)
    assert not passed and "--no-frontend" in output


# the check cache and --changed (experimental)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shop"
    (repo / "catalog").mkdir(parents=True)
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "manage.py").write_text("")
    (repo / "catalog" / "models.py").write_text("x = 1\n")
    (repo / "catalog" / "views.py").write_text("y = 1\n")
    (repo / "frontend" / "src" / "page.tsx").write_text("export {}\n")
    (repo / ".gitignore").write_text("*.log\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "one")
    return repo


def test_changed_files_are_the_working_tree_the_index_and_untracked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert check_mod.changed_files(repo) == []
    (repo / "catalog" / "models.py").write_text("x = 2\n")  # working tree
    (repo / "frontend" / "src" / "page.tsx").write_text("export const a = 1\n")
    _git(repo, "add", "frontend/src/page.tsx")  # index
    (repo / "catalog" / "new.py").write_text("")  # untracked
    (repo / "debug.log").write_text("")  # ignored
    (repo / "catalog" / "views.py").unlink()  # deleted: nothing to check
    assert check_mod.changed_files(repo) == [
        "catalog/models.py",
        "catalog/new.py",
        "frontend/src/page.tsx",
    ]
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "two")
    assert check_mod.changed_files(repo) == []
    # against a ref: everything since the first commit
    assert check_mod.changed_files(repo, "main~1") == [
        "catalog/models.py",
        "catalog/new.py",
        "frontend/src/page.tsx",
    ]


def test_changed_files_outside_git_or_with_an_unknown_ref_say_so(tmp_path: Path) -> None:
    import pytest

    from karni_cli.project import CliError

    with pytest.raises(CliError) as outside:
        check_mod.changed_files(tmp_path)
    assert outside.value.code == "C581"
    repo = _repo(tmp_path)
    with pytest.raises(CliError) as unknown:
        check_mod.changed_files(repo, "no-such-branch")
    assert unknown.value.code == "C581" and "no-such-branch" in unknown.value.message


def test_a_repository_without_a_commit_has_its_index_as_the_change(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    (repo / "a.py").write_text("")
    _git(repo, "init", "-q")
    _git(repo, "add", "a.py")
    (repo / "b.py").write_text("")
    assert check_mod.changed_files(repo) == ["a.py", "b.py"]


def test_changed_passes_the_files_and_lints_only_changed_frontend_files(
    runner, tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    (repo / "catalog" / "models.py").write_text("x = 3\n")
    (repo / "frontend" / "src" / "page.tsx").write_text("export const b = 1\n")
    (repo / "frontend" / "node_modules").mkdir()  # installed, so the frontend checks run
    monkeypatch.chdir(repo)
    seen: dict[str, object] = {}

    def run_manage(project, args, **kwargs):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="check cache: 1 of 1\n", stderr="")

    def lint(project, **kwargs):
        seen["lint"] = {key: value for key, value in kwargs.items() if key != "capture"}
        return 0

    monkeypatch.setattr(project_mod, "run_manage", run_manage)
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lint)
    result = runner.invoke(app, ["check", "--changed"])
    assert result.exit_code == 0, result.output
    assert seen["args"] == [
        "karni_check",
        "--changed",
        "catalog/models.py",
        "frontend/src/page.tsx",
    ]
    assert seen["lint"] == {"cache": True, "files": ["src/page.tsx"]}
    assert "2 changed file(s)" in result.output and "check cache: 1 of 1" in result.output

    result = runner.invoke(app, ["check", "--changed", "main", "--no-cache"])
    assert result.exit_code == 0, result.output
    assert seen["args"][:3] == ["karni_check", "--no-cache", "--changed"]
    assert seen["lint"] == {"cache": False, "files": ["src/page.tsx"]}


def test_a_ref_needs_changed_and_an_old_karni_is_named(runner, tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    assert runner.invoke(app, ["check", "main"]).exit_code == 2
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda project, args, **kw: subprocess.CompletedProcess(
            args, 2, stdout="", stderr="karni_check: error: unrecognized arguments: --no-cache"
        ),
    )
    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p, **kwargs: 0)
    monkeypatch.setattr(check_mod, "_frontend_lint", lambda p, **kwargs: 0)
    result = runner.invoke(app, ["check", "--no-cache"])
    assert result.exit_code == 1 and "C582" in result.output


def test_a_changed_run_without_frontend_changes_skips_eslint(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    assert check_mod._frontend_lint(tmp_path, files=[]) == 0  # not even "eslint missing"
    assert check_mod.eslint_args(tmp_path, cache=False, files=["src/a.tsx"]) == [
        "src/a.tsx",
        "--max-warnings",
        "0",
    ]


def test_a_frontend_pass_prints_nothing_more_and_a_failure_prints_the_tools_output(
    runner, tmp_path: Path, monkeypatch
) -> None:
    """jscpd's report table and ESLint's banner reach the output only when they fail."""
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "run_manage", _fake_run(0))
    monkeypatch.delenv("CI", raising=False)
    outcome = {"dup": 0}

    def tool(name: str):
        def run(project: Path, capture: list[str] | None = None, **kwargs: object) -> int:
            report = f"{name} REPORT TABLE"
            if capture is None:
                print(report)
            else:
                capture.append(report)
            return outcome["dup"] if name == "jscpd" else 0

        return run

    monkeypatch.setattr(check_mod, "_frontend_duplication", tool("jscpd"))
    monkeypatch.setattr(check_mod, "_frontend_lint", tool("eslint"))
    passed = runner.invoke(app, ["check", "-q"])
    assert passed.exit_code == 0, passed.output
    assert passed.output == "karni check: ok\n"  # nothing of the tools' own output
    verbose = runner.invoke(app, ["check", "--verbose"])
    assert "jscpd REPORT TABLE" in verbose.output and "eslint REPORT TABLE" in verbose.output
    outcome["dup"] = 1
    failed = runner.invoke(app, ["check"])
    assert failed.exit_code == 1
    assert "jscpd REPORT TABLE" in failed.output and "eslint REPORT TABLE" in failed.output
