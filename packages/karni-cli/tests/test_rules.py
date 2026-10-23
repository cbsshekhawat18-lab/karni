"""``karni rules``: listing, explain, procedures, --check, data sources, budget."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from karni_cli import agent_data
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import REPO_ROOT

FIXTURES = REPO_ROOT / "packages" / "karni" / "tests" / "agent" / "fixtures"
#: ~4 characters per token is the usual English/code approximation; the
#: tiktoken check below is stricter when the package is available.
# Measured 561 cl100k tokens with 44 rules (K013-K015 and K030-K032 debugging, K114 typed
# fields, K115 and K116 lifecycle and capacity, K206 token classes, K309 public site). The
# README quotes the figure.
TOKEN_BUDGET = 570


def _rules_output(runner, monkeypatch, cwd: Path) -> str:
    monkeypatch.chdir(cwd)
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0, result.output
    return result.output


def test_lists_every_code(runner, tmp_path, monkeypatch) -> None:
    out = _rules_output(runner, monkeypatch, tmp_path)
    data = agent_data.load(None)
    for rule in data.rules:
        assert rule["code"] in out
    assert "K101!" in out  # enforced marker
    assert "K001 " in out  # convention, no marker


def test_token_budget(runner, tmp_path, monkeypatch) -> None:
    out = _rules_output(runner, monkeypatch, tmp_path)
    assert len(out) / 4 < TOKEN_BUDGET
    tiktoken = pytest.importorskip("tiktoken")
    for name in ("cl100k_base", "o200k_base"):
        try:
            encoding = tiktoken.get_encoding(name)
        except Exception:  # noqa: BLE001 - encodings download on first use
            pytest.skip("tiktoken encodings unavailable offline")
        assert len(encoding.encode(out)) < TOKEN_BUDGET, name


def test_explain_procedure_and_json(runner, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    explain = runner.invoke(app, ["rules", "--explain", "k101"])
    assert explain.exit_code == 0, explain.output
    assert "Why:" in explain.output and "Fix:" in explain.output
    assert "Enforced by: model-base" in explain.output

    procedure = runner.invoke(app, ["rules", "--procedure", "new-model"])
    assert procedure.exit_code == 0
    assert "1. Run `karni context`" in procedure.output

    raw = runner.invoke(app, ["rules", "--json"])
    assert json.loads(raw.output)["schema"] == 1

    assert runner.invoke(app, ["rules", "--explain", "K999"]).exit_code != 0
    assert runner.invoke(app, ["rules", "--procedure", "nope"]).exit_code != 0


def test_explain_the_public_site_rule(runner, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    explain = runner.invoke(app, ["rules", "--explain", "K309"])
    assert explain.exit_code == 0, explain.output
    out = explain.output
    assert out.startswith("K309 [architecture, must] A public, server-rendered website")
    assert "Why: " in out and "Fix: Run `karni make site <app>`" in out
    listing = _rules_output(runner, monkeypatch, tmp_path)
    assert "K309 Public site: a site app with Django views and templates." in listing
    assert "K306 App pages: frontend/src/pages/. Public site pages: K309." in listing


def test_check_exit_codes(runner, monkeypatch) -> None:
    monkeypatch.chdir(FIXTURES)
    bad = runner.invoke(app, ["rules", "--check", "app/bad_models.py"])
    assert bad.exit_code == 1
    assert "app/bad_models.py:" in bad.output and "fix:" in bad.output
    for code in ("K101", "K102", "K103", "K104", "K105", "K106", "K109", "K110", "K005"):
        assert code in bad.output, code

    page = runner.invoke(app, ["rules", "--check", "frontend/src/pages/bad_page.tsx"])
    assert page.exit_code == 1
    for code in ("K201", "K202", "K203", "K204"):
        assert code in page.output, code

    good = runner.invoke(
        app,
        [
            "rules",
            "--check",
            "app/good_models.py",
            "--check",
            "frontend/src/pages/good_page.tsx",
        ],
    )
    assert good.exit_code == 0, good.output
    assert "ok: no violations in 2 file(s)" in good.output

    as_json = runner.invoke(app, ["rules", "--check", "app/bad_models.py", "--json"])
    assert {f["code"] for f in json.loads(as_json.output)} >= {"K101", "K105"}

    missing = runner.invoke(app, ["rules", "--check", "nope.py"])
    assert missing.exit_code != 0


def test_project_overrides_apply(runner, generated_project, monkeypatch) -> None:
    (generated_project / "karni.rules.py").write_text(
        'ADD = [{"code": "P001", "rule": "Money is Decimal, never float."}]\nDISABLE = ["K304"]\n'
    )
    out = _rules_output(runner, monkeypatch, generated_project)
    assert "P001 Money is Decimal" in out and "[project]" in out
    assert "K304" not in out

    (generated_project / "karni.rules.py").write_text("import os\n")
    bad = runner.invoke(app, ["rules"])
    assert bad.exit_code != 0


def test_bundled_source_needs_no_karni(monkeypatch) -> None:
    """The fallback used by `karni new` on a machine with only karni-cli."""
    monkeypatch.setenv("KARNI_AGENT_SOURCE", "bundled")
    data = agent_data.load(None)
    assert data.source == "bundled"
    assert data.rule("K101") is not None
    local = agent_data._local()
    assert local is not None
    assert data.rules == local.dump()["rules"]


def test_project_source_runs_the_project_interpreter(tmp_path, monkeypatch) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    calls: list[list[str]] = []
    payload = agent_data._local().dump()  # type: ignore[union-attr]

    def fake_run(command, **kwargs):
        calls.append(list(command))
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(agent_data.subprocess, "run", fake_run)
    monkeypatch.setenv("KARNI_AGENT_SOURCE", "project")
    data = agent_data.load(tmp_path)
    assert data.source == "project"
    assert calls == [[str(python), "-m", "karni.agent", "dump", "--root", "."]]

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="karni.rules.py:1: bad")

    monkeypatch.setattr(agent_data.subprocess, "run", failing)
    with pytest.raises(CliError, match="karni.rules.py:1: bad"):
        agent_data.load(tmp_path)


def test_unknown_source_is_an_error(monkeypatch) -> None:
    monkeypatch.setenv("KARNI_AGENT_SOURCE", "cloud")
    with pytest.raises(CliError, match="KARNI_AGENT_SOURCE"):
        agent_data.load(None)
