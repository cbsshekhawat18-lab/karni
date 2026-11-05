"""The token benchmark harness (scripts/benchmarks/tokens): fast, no network, no real claude.

The end-to-end test runs the harness with the fake claude on a tiny starting project and a
tiny task, so the folder, git, database calls, time limit and the recorded line are real.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from .conftest import REPO_ROOT

TOKENS = REPO_ROOT / "scripts" / "benchmarks" / "tokens"
pytestmark = pytest.mark.skipif(not TOKENS.is_dir(), reason="needs the Karni checkout")


def _load(name: str) -> Any:
    if str(TOKENS) not in sys.path:
        sys.path.insert(0, str(TOKENS))
    return importlib.import_module(name)


streamjson = _load("harness.streamjson")
diffsize = _load("harness.diffsize")
stats = _load("harness.stats")
order = _load("harness.order")
records = _load("harness.records")
execute = _load("harness.execute")
starts = _load("harness.starts")
report = _load("report")
run_module = _load("run")


def lines(*events: dict[str, Any]) -> list[str]:
    return [json.dumps(event) for event in events]


def assistant(message_id: str, usage: dict[str, int], *tools: dict[str, Any]) -> dict[str, Any]:
    content = [{"type": "tool_use", "id": f"{message_id}-{i}", **t} for i, t in enumerate(tools)]
    return {"type": "assistant", "message": {"id": message_id, "usage": usage, "content": content}}


# --- stream-json -------------------------------------------------------------------------------


def test_the_result_line_gives_tokens_cost_and_tool_counts() -> None:
    usage = {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5}
    result = {
        "type": "result",
        "total_cost_usd": 0.5,
        "num_turns": 2,
        "usage": {**usage, "cache_creation_input_tokens": 6},
    }
    parsed = streamjson.parse(
        lines(
            assistant(
                "m1",
                usage,
                {"name": "Write", "input": {"file_path": "a", "content": "one\ntwo\nthree\n"}},
                {"name": "Edit", "input": {"old_string": "x", "new_string": "a\nb"}},
                {"name": "Bash", "input": {"command": "ls"}},
            ),
            assistant("m2", usage, {"name": "Bash", "input": {"command": "pwd"}}),
            result,
        )
    )
    assert (parsed.input_tokens, parsed.output_tokens) == (3, 4)
    assert (parsed.cache_read_tokens, parsed.cache_creation_tokens) == (5, 6)
    assert parsed.cost_usd == 0.5 and parsed.num_turns == 2 and parsed.result_seen
    assert parsed.tool_calls == {"Write": 1, "Edit": 1, "Bash": 2}
    assert parsed.tool_calls_total == 4
    assert parsed.lines_written == 3 + 2  # Write counts its content, Edit its new string


def test_a_killed_run_has_no_result_line_and_its_tokens_are_summed_once_per_message() -> None:
    usage = {"input_tokens": 10, "output_tokens": 1}
    event = assistant("m1", usage, {"name": "Write", "input": {"content": "a\nb"}})
    parsed = streamjson.parse(
        [
            *lines(event, event, assistant("m2", {"input_tokens": 5, "output_tokens": 2})),
            '{"type": "ass',
        ]
    )
    assert not parsed.result_seen
    assert (parsed.input_tokens, parsed.output_tokens) == (15, 3)
    assert parsed.tool_calls == {"Write": 1}  # the repeated block counts once
    assert parsed.lines_written == 2
    assert parsed.bad_lines == 1  # the cut-off last line


def test_multiedit_and_odd_input_are_counted_safely() -> None:
    edits = {"edits": [{"new_string": "a\nb"}, {"new_string": "c"}, "junk"]}
    assert streamjson.written_lines("MultiEdit", edits) == 3
    assert streamjson.written_lines("Write", {}) == 0
    assert streamjson.written_lines("Read", {"content": "x"}) == 0
    assert streamjson.parse([]).input_tokens == 0


# --- the diff -----------------------------------------------------------------------------------


def test_numstat_counts_added_plus_deleted_with_and_without_lockfiles_and_migrations() -> None:
    text = "\n".join(
        [
            "10\t2\tshop/models.py",
            "500\t0\tfrontend/package-lock.json",
            "40\t0\tshop/migrations/0001_initial.py",
            "7\t1\tfrontend/node_modules/x/index.js",
            "-\t-\tlogo.png",
            "3\t0\tuv.lock",
        ]
    )
    size = diffsize.parse_numstat(text)
    assert size.lines_all == 12 + 500 + 40 + 8 + 3
    assert size.lines_code == 12
    assert (size.files_all, size.files_code) == (6, 2)  # the binary logo is a file with no counted lines


def test_measure_counts_new_and_changed_files_against_the_start_commit(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "a.py").write_text("one\ntwo\n")
    commit = diffsize.commit_start(tmp_path)
    assert diffsize.measure(tmp_path, commit).lines_all == 0
    (tmp_path / "a.py").write_text("one\nTWO\nthree\n")  # 1 deleted, 2 added
    (tmp_path / "b.py").write_text("x\ny\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "big.txt").write_text("z\n" * 100)
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    (tmp_path / "app" / "migrations" / "0001.py").write_text("m\n" * 10)
    size = diffsize.measure(tmp_path, commit)
    assert (size.lines_code, size.lines_all) == (5, 15)


# --- statistics, the order, the report ------------------------------------------------------------


def test_spread_gives_the_median_min_max_and_quartiles() -> None:
    s = stats.spread([1, 2, 3, 4, 100])
    assert (s.n, s.median, s.minimum, s.maximum) == (5, 3, 1, 100)
    assert (s.q1, s.q3, s.iqr) == (2, 4, 2)
    assert stats.spread([7]).iqr == 0
    assert stats.spread([]) is None


def test_conditions_alternate_and_every_round_covers_every_task() -> None:
    plan = order.plan(["a", "b"], ["plain", "karni"], 2)
    assert plan[:4] == [("a", "plain", 1), ("a", "karni", 1), ("b", "plain", 1), ("b", "karni", 1)]
    assert [c for _t, c, _i in plan] == ["plain", "karni"] * 4
    assert len(plan) == 8 and len(set(plan)) == 8
    assert len(order.plan(["a", "b", "c"], ["plain", "karni"], 5)) == 30


def _row(task: str, condition: str, tokens: int, success: bool = True) -> dict[str, Any]:
    return {
        "task": task, "condition": condition, "input_tokens": tokens, "output_tokens": 0,
        "success": success, "timed_out": not success, "acceptance_passed": 3, "acceptance_total": 4,
    }  # fmt: skip


def test_the_report_gives_success_rate_and_spread_per_task_and_condition() -> None:
    rows = [_row("shop", "plain", t) for t in (10, 20, 30, 40, 50)]
    rows += [_row("shop", "karni", 5, False), _row("shop", "karni", 7)]
    text = report.render(rows)
    assert "| shop | plain | 5 | 5 | 100% | 0 |" in text
    assert "| shop | karni | 2 | 1 | 50% | 1 |" in text
    assert "| shop | plain | 5 | 30 | 10 | 50 | 20 |" in text  # the input tokens table
    assert report.render([]) == report.PENDING


def test_the_report_replaces_only_what_is_between_the_markers() -> None:
    page = f"before\n{report.START}\nold\n{report.END}\nafter\n"
    updated = report.splice(page, "new")
    assert updated == f"before\n{report.START}\n\nnew\n\n{report.END}\nafter\n"
    assert report.splice(updated, "new") == updated
    with pytest.raises(SystemExit):
        report.splice("no markers", "new")


def test_the_docs_page_is_current_for_the_data_file() -> None:
    page = report.PAGE.read_text()
    assert report.splice(page, report.render(records.load())) == page, (
        "run scripts/benchmarks/tokens/report.py"
    )


# --- the command line the runs use ---------------------------------------------------------------


def test_the_claude_command_is_the_methods_and_the_karni_prompt_starts_with_new_app() -> None:
    command = execute.claude_command(["claude"], "PROMPT", "claude-sonnet-5-5", Path("m.json"))
    assert command[:3] == ["claude", "-p", "PROMPT"]
    for flag in (
        "--verbose", "--strict-mcp-config", "--no-session-persistence",
        "--dangerously-skip-permissions",
    ):  # fmt: skip
        assert flag in command
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--setting-sources") + 1] == "project"
    assert command[command.index("--model") + 1] == "claude-sonnet-5-5"
    tasks = TOKENS / "tasks"
    plain = execute.task_prompt(tasks, "shop", "plain")
    karni = execute.task_prompt(tasks, "shop", "karni")
    assert karni == "/new-app " + plain and not plain.startswith("/new-app")
    assert "API contract" in plain and "create_account" in plain


def test_runs_never_depend_on_the_callers_virtualenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/old/venv")
    env = execute.project_env(tmp_path, "postgres://x/y", venv=False)
    assert "VIRTUAL_ENV" not in env
    env = execute.project_env(tmp_path, "postgres://x/y", venv=True)
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert env["PATH"].startswith(str(tmp_path / ".venv" / "bin"))


def test_a_dry_run_prints_the_plan_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KARNI_BENCH_HOME", str(tmp_path))
    run_module.main(["--dry-run", "--tasks", "shop", "--n", "1", "--data", str(tmp_path / "d")])
    out = capsys.readouterr().out
    assert out.index("shop-plain-1") < out.index("shop-karni-1")
    assert "--setting-sources project" in out and "bm_shop_karni_1" in out
    assert list(tmp_path.iterdir()) == []


# --- one fake run, end to end ----------------------------------------------------------------------


class FakeDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def create(self, name: str) -> None:
        self.calls.append(("create", name))

    def drop(self, name: str) -> None:
        self.calls.append(("drop", name))


SERVER = """\
import http.server, sys
if sys.argv[1] == "runserver":
    host, port = sys.argv[2].split(":")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *args): pass

    http.server.HTTPServer((host, int(port)), Handler).serve_forever()
"""

MINI_TEST = """\
import os, requests

def test_up():
    assert requests.get(os.environ["BENCH_BASE_URL"], timeout=5).status_code == 200

def test_down():
    assert requests.get(os.environ["BENCH_BASE_URL"] + "/x", timeout=5).text == "ok"
"""


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    pytest.importorskip("requests")
    monkeypatch.setenv("KARNI_BENCH_HOME", str(tmp_path / "home"))
    project = tmp_path / "start"
    (project / "frontend").mkdir(parents=True)
    (project / "manage.py").write_text(SERVER)
    (project / "frontend" / "package.json").write_text('{"scripts": {"build": "node -e 0"}}\n')
    task = tmp_path / "tasks" / "mini"
    (task / "acceptance").mkdir(parents=True)
    (task / "prompt.md").write_text("Build a mini app.\n")
    (task / "contract.md").write_text("It answers ok.\n")
    (task / "acceptance" / "test_mini.py").write_text(MINI_TEST)
    config = execute.Config(
        claude=[sys.executable, str(execute.FAKE_CLAUDE)],
        tasks_dir=tmp_path / "tasks",
        data_file=tmp_path / "runs.jsonl",
        database=FakeDatabase(),
        keep=True,
        log=lambda _m: None,
    )
    return config, starts.Start(name="plain", project=project)


def test_a_fake_run_makes_the_folder_the_repo_the_database_and_one_recorded_line(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    argv_log = config.tasks_dir.parent / "argv.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(argv_log))
    record = execute.execute("mini", "plain", 1, start, config, stamp="T1")

    assert record.run_id == "mini-plain-1-T1"
    run_dir = Path(config.tasks_dir.parent / "home" / "runs" / record.run_id)
    project = run_dir / "project"
    assert (project / "fake_note.txt").read_text().startswith("1st") is False  # the fake wrote it
    assert (project / "acceptance" / "test_mini.py").is_file()  # the checks the agent may run
    log = subprocess.run(
        ["git", "-C", str(project), "log", "--format=%s"], capture_output=True, text=True
    ).stdout
    assert log.split() == ["start"]
    assert config.database.calls == [
        ("create", "bm_mini_plain_1_t1"),
        ("drop", "bm_mini_plain_1_t1"),
    ]
    argv = json.loads(argv_log.read_text())
    assert argv[0] == "-p" and "Build a mini app." in argv[1] and "--verbose" in argv

    assert (record.input_tokens, record.output_tokens) == (15, 27)
    assert (record.cache_read_tokens, record.cache_creation_tokens) == (250, 50)
    assert record.cost_usd == 0.0123
    assert record.tool_calls == {"Write": 1, "Edit": 1, "Bash": 1}
    assert record.agent_lines_written == 3 + 2
    assert record.diff_lines_code >= 3  # fake_note.txt
    assert (record.acceptance_passed, record.acceptance_total) == (2, 2)
    assert record.build_ok and not record.timed_out and record.exit_status == 0
    assert record.success and not record.error

    saved = records.load(config.data_file)
    assert len(saved) == 1 and saved[0]["run_id"] == record.run_id
    assert saved[0]["tool_calls"] == {"Write": 1, "Edit": 1, "Bash": 1}
    assert records.done(saved) == {("mini", "plain", 1)}


def test_a_run_over_the_time_limit_is_killed_and_recorded_as_a_failure(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    config.limit_seconds = 1
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    record = execute.execute("mini", "plain", 2, start, config, stamp="T2")
    assert record.timed_out and record.exit_status == "timeout"
    assert record.wall_seconds < 20
    assert not record.success and not record.result_seen
    assert record.input_tokens == 10  # the first message only: summed, there is no result line
    assert len(records.load(config.data_file)) == 1  # a timed-out run stays in the data
    assert config.database.calls[-1][0] == "drop"


def test_a_crashing_agent_and_a_crashing_harness_both_leave_a_failed_record(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "3")
    record = execute.execute("mini", "plain", 3, start, config, stamp="T3")
    assert record.exit_status == 3 and not record.success

    config.claude = ["/nonexistent/claude"]
    record = execute.execute("mini", "plain", 4, start, config, stamp="T4")
    assert record.exit_status == "crash" and "FileNotFoundError" in record.error
    assert not record.success
    assert len(records.load(config.data_file)) == 2
    assert [c for c, _n in config.database.calls].count("drop") == 2


def test_resume_skips_runs_already_in_the_data(tmp_path: Path) -> None:
    data = tmp_path / "runs.jsonl"
    rec = records.RunRecord("r", "shop", "plain", 1, "m", "t")
    records.append(rec, data)
    finished = records.done(records.load(data))
    plan = [run for run in order.plan(["shop"], ["plain", "karni"], 1) if run not in finished]
    assert plan == [("shop", "karni", 1)]
