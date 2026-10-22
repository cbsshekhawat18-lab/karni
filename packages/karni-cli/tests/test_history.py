"""History-aware context: `karni context --with-history`, the conditional rule,
adapter stability, the bundled fallback, and silence with no provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from karni_cli import agent_data
from karni_cli import project as project_mod
from karni_cli.adapters import render_all
from karni_cli.commands import context as context_cmd
from karni_cli.main import app

from .conftest import REPO_ROOT
from .test_rules import TOKEN_BUDGET

BACKEND = (
    "MODELS: Event(title,starts_at,capacity,status) Venue(name,address)\n"
    "VIEWSETS: EventViewSet VenueViewSet\n"
    "MODULES: payments\n"
    "BASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser"
)
K008 = "K008 Before editing a file: karni context --with-history FILE."

PROVIDER_SOURCE = '''
from pathlib import Path


class FakeHistory:
    """Keeps its "store" in <project>/.fakehistory/; one brief file per path."""

    name = "fake-history"

    def detect(self, project_root):
        return (Path(project_root) / ".fakehistory").is_dir()

    def context(self, project_root, path):
        print("chatter a provider must never get onto karni's stdout")
        brief = Path(project_root) / ".fakehistory" / (path.replace("/", "__") + ".txt")
        return brief.read_text() if brief.is_file() else None

    def project_context(self, project_root):
        brief = Path(project_root) / ".fakehistory" / "_project.txt"
        return brief.read_text() if brief.is_file() else None

    def full_command(self, project_root, path):
        return f"fakehist show {path}"
'''


def _tokens(text: str) -> float:
    """The `karni rules` budget measure: ~4 characters per token."""
    return len(text) / 4


@pytest.fixture
def fake_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A third-party provider registered through a REAL entry point (dist-info on sys.path)."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "karni_fake_history.py").write_text(PROVIDER_SOURCE)
    dist = site / "karni_fake_history-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: karni-fake-history\nVersion: 1.0\n"
    )
    (dist / "entry_points.txt").write_text(
        "[karni.history_providers]\nfake-history = karni_fake_history:FakeHistory\n"
    )
    monkeypatch.delitem(sys.modules, "karni_fake_history", raising=False)
    monkeypatch.syspath_prepend(str(site))
    return site


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    (root / "apps" / "events").mkdir(parents=True)
    (root / "manage.py").write_text("")
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    return root


def _store(project: Path, briefs: dict[str, str] | None = None) -> None:
    store = project / ".fakehistory"
    store.mkdir(exist_ok=True)
    for path, text in (briefs or {}).items():
        (store / (path.replace("/", "__") + ".txt")).write_text(text)


def _run(runner, *args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.stdout


# karni context --with-history


def test_with_history_and_no_store_is_byte_identical(runner, project, fake_provider) -> None:
    plain = _run(runner, "context")
    assert _run(runner, "context", "--with-history") == plain
    assert _run(runner, "context", "--with-history", "apps/events/models.py") == plain
    assert plain.strip() == BACKEND


def test_store_without_a_brief_adds_nothing(runner, project, fake_provider) -> None:
    _store(project)
    assert _run(runner, "context", "--with-history", "apps/events/models.py").strip() == BACKEND


def test_brief_is_appended_under_a_history_heading(runner, project, fake_provider) -> None:
    _store(
        project,
        {"apps/events/models.py": "Decided: soft delete.\n\nReverted: hard delete (refunds).\n"},
    )
    out = _run(runner, "context", "--with-history", "apps/events/models.py")
    assert out == (
        f"{BACKEND}\n"
        "HISTORY: apps/events/models.py (fake-history)\n"
        "Decided: soft delete.\n"
        "Reverted: hard delete (refunds).\n"
    )
    assert "chatter" not in out  # whatever a provider prints is discarded


def test_paths_resolve_from_the_cwd(runner, project, fake_provider, monkeypatch) -> None:
    _store(project, {"apps/events/models.py": "Decided: soft delete."})
    monkeypatch.chdir(project / "apps" / "events")
    out = _run(runner, "context", "--with-history", "models.py")
    assert "HISTORY: apps/events/models.py (fake-history)" in out
    absolute = _run(runner, "context", "--with-history", str(project / "apps/events/models.py"))
    assert absolute == out


def test_without_path_uses_the_project_brief(runner, project, fake_provider) -> None:
    _store(project)
    (project / ".fakehistory" / "_project.txt").write_text("Recorded decisions:\n- Decimal money")
    out = _run(runner, "context", "--with-history")
    assert out.endswith("HISTORY: project (fake-history)\nRecorded decisions:\n- Decimal money\n")


def test_the_cap_holds_and_names_the_full_command(runner, project, fake_provider) -> None:
    lines = [f"- decision {i:03d}: kept because of reason number {i}" for i in range(200)]
    _store(project, {"apps/events/models.py": "\n".join(lines)})
    out = _run(runner, "context", "--with-history", "apps/events/models.py")
    inventory, block = out.rstrip("\n").split("\nHISTORY:", 1)
    block = "HISTORY:" + block
    assert inventory == BACKEND
    assert _tokens(block) <= context_cmd.HISTORY_TOKEN_CAP
    shown = block.split("\n")
    assert (
        shown[-1] == "… truncated at ~300 tokens. Full brief: fakehist show apps/events/models.py"
    )
    assert shown[1:-1] == lines[: len(shown) - 2]  # cut at line boundaries
    assert _tokens(out) <= _tokens(BACKEND + "\n") + context_cmd.HISTORY_TOKEN_CAP + 1


def test_cap_constant_and_help_match_the_enforcing_module(runner) -> None:
    from karni.agent.history import HISTORY_TOKEN_CAP

    assert context_cmd.HISTORY_TOKEN_CAP == HISTORY_TOKEN_CAP
    result = runner.invoke(app, ["context", "--help"], env={"COLUMNS": "200"})
    assert "--with-history" in result.output and "~300 tokens" in result.output


def test_path_needs_the_flag_and_must_be_inside(runner, project, fake_provider) -> None:
    assert runner.invoke(app, ["context", "apps/events/models.py"]).exit_code == 2
    outside = runner.invoke(app, ["context", "--with-history", "../elsewhere.py"])
    assert outside.exit_code == 1 and "outside the project" in outside.stderr
    assert outside.stdout == ""


# the conditional rule


def test_rule_only_with_a_store(runner, project, fake_provider) -> None:
    without = _run(runner, "rules")
    assert "K008" not in without
    _store(project)
    with_store = _run(runner, "rules")
    assert K008 in with_store
    assert sorted(with_store.splitlines()) == sorted([*without.splitlines(), K008])
    explained = _run(runner, "rules", "--explain", "K008")
    assert "karni context --with-history <file>" in explained


def test_builtin_chronicle_store_turns_the_rule_on_without_running_chronicle(
    runner, project
) -> None:
    (project / ".chronicle").mkdir()
    assert K008 in _run(runner, "rules")  # the autouse guard fails on any chronicle spawn


def test_rules_budget_with_and_without_a_store(runner, project, fake_provider) -> None:
    assert _tokens(_run(runner, "rules")) < TOKEN_BUDGET
    _store(project)
    assert _tokens(_run(runner, "rules")) < TOKEN_BUDGET + _tokens(K008 + "\n")


def test_adapters_are_identical_with_and_without_a_store(
    runner, generated_project: Path, fake_provider, monkeypatch
) -> None:
    monkeypatch.chdir(generated_project)
    before = render_all(generated_project, agent_data.load(generated_project))
    assert runner.invoke(app, ["rules", "sync", "--check"]).exit_code == 0
    _store(generated_project)
    (generated_project / ".chronicle").mkdir()
    data = agent_data.load(generated_project)
    assert any(rule["code"] == "K008" for rule in data.rules)  # the store is seen...
    assert render_all(generated_project, data) == before  # ...and no adapter changes
    check = runner.invoke(app, ["rules", "sync", "--check"])
    assert check.exit_code == 0, check.output


# where providers run


def test_project_interpreter_gets_the_clis_detection(tmp_path, monkeypatch) -> None:
    """In project mode the CLI's own detection is handed over (env / `-e`)."""
    (tmp_path / ".chronicle").mkdir()
    local = agent_data._local()
    assert local is not None
    payload = local.dump()
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((list(command), kwargs.get("env")))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(agent_data.subprocess, "run", fake_run)
    monkeypatch.setenv("KARNI_AGENT_SOURCE", "project")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    agent_data.load(tmp_path)
    command, env = calls[-1]
    assert command == [str(python), "-m", "karni.agent", "dump", "--root", "."]
    assert env is not None and env["KARNI_AGENT_CONDITIONS"] == "history"

    python.unlink()
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: True)
    agent_data.load(tmp_path)
    command, _env = calls[-1]
    assert command[:7] == [
        "docker", "compose", "exec", "-T", "-e", "KARNI_AGENT_CONDITIONS=history", "django",
    ]  # fmt: skip


def test_bundled_copy_finds_the_builtin_provider_without_karni() -> None:
    """`python -S`: no site-packages, so karni is not importable — only karni-cli's bundle."""
    code = (
        "from karni_cli import agent_data\n"
        "assert agent_data._local() is None\n"
        "m = agent_data.history_module()\n"
        "assert m is not None and m.__name__ == 'karni_cli._bundled_karni_agent.history', m\n"
        "found = m.discover()\n"
        "assert found.names == ['gigai-chronicle'], found\n"
        "assert not found.errors, found.errors\n"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT / "packages/karni-cli"),
        },
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_bundled_source_discovers_cli_entry_points(project, fake_provider, monkeypatch) -> None:
    monkeypatch.setenv("KARNI_AGENT_SOURCE", "bundled")
    module = agent_data.history_module()
    assert module is not None and module.__name__.startswith("karni_cli._bundled")
    assert module.discover().names == ["fake-history", "gigai-chronicle"]


def test_no_store_spawns_no_provider_process(runner, project, monkeypatch) -> None:
    """Every command, no store: nothing named chronicle is ever started."""
    spawned: list[Any] = []
    real_run = subprocess.run

    def spy(args: Any, *a: Any, **kw: Any) -> Any:
        spawned.append(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)
    import karni_cli.commands.check as check_mod

    monkeypatch.setattr(check_mod, "_frontend_duplication", lambda p: 0)
    for args in (
        ["context", "--with-history", "apps/events/models.py"],
        ["context", "--with-history"],
        ["rules"],
        ["doctor"],
        ["check"],
    ):
        assert runner.invoke(app, args).exit_code == 0, args
    assert not [a for a in spawned if "chronicle" in str(a)]


# the built-in provider end to end (fake `chronicle` on PATH)

FAKE_CHRONICLE = """#!{python}
import json, os, sys
sys.stderr.write("note: workspace moved (discarded)\\n")
print(json.dumps({{
    "apiVersion": 1, "command": "context", "file": sys.argv[2], "empty": False,
    "prompts": [], "knowledge": [],
    "markdown": "# Context for " + sys.argv[2] + "\\n\\n_Assembled from your history._\\n\\n"
        "## What shaped this file\\n\\n1. 2026-09-30 14:02  +12 \\u22123  \\u2014 \\"soft delete\\"\\n\\n"
        "## Why this file looks the way it does (Project Memory)\\n\\n"
        "**Failed / superseded approaches (do NOT repeat)**\\n- hard delete: reverted\\n\\n"
        "---\\n_Derived from the Chronicle record on this machine._\\n",
}}))
"""


@pytest.mark.history_provider
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang fake binary")
@pytest.mark.parametrize("source", ["local", "bundled"])
def test_chronicle_brief_through_the_cli(
    runner, project, tmp_path, monkeypatch, source: str
) -> None:
    (project / ".chronicle").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "chronicle"
    fake.write_text(FAKE_CHRONICLE.format(python=sys.executable))
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("KARNI_AGENT_SOURCE", source)
    out = _run(runner, "context", "--with-history", "apps/events/models.py")
    assert out == (
        f"{BACKEND}\n"
        "HISTORY: apps/events/models.py (gigai-chronicle)\n"
        "## Why this file looks the way it does (Project Memory)\n"
        "**Failed / superseded approaches (do NOT repeat)**\n"
        "- hard delete: reverted\n"
        "## What shaped this file\n"
        '1. 2026-09-30 14:02 +12 −3 — "soft delete"\n'
    )
