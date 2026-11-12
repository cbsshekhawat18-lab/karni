"""The token benchmark harness (scripts/benchmarks/tokens): fast, no network, no real agent.

The end-to-end test runs the harness with the fake agent on a tiny starting project and a
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

from .conftest import REPO_ROOT, requires_git

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
inventory = _load("inventory")


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
    text = (
        "10\t2\tshop/models.py\n500\t0\tfrontend/package-lock.json\n"
        "40\t0\tshop/migrations/0001_initial.py\n7\t1\tfrontend/node_modules/x/index.js\n"
        "-\t-\tlogo.png\n3\t0\tuv.lock"
    )
    size = diffsize.parse_numstat(text)
    assert size.lines_all == 12 + 500 + 40 + 8 + 3
    assert size.lines_code == 12
    assert (size.files_all, size.files_code) == (
        6,
        2,
    )  # the binary logo is a file with no counted lines


@requires_git
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


@requires_git
def test_measure_counts_work_the_agent_committed_itself(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\n")
    commit = diffsize.commit_start(tmp_path)
    (tmp_path / "b.py").write_text("x\ny\nz\n")
    (tmp_path / "package-lock.json").write_text("l\n" * 4)
    for args in (
        ["add", "-A"],
        ["-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "-qm", "m"],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    (tmp_path / "c.py").write_text("u\n")  # committed and uncommitted work count alike
    size = diffsize.measure(tmp_path, commit)
    assert (size.lines_code, size.files_code) == (4, 2)
    assert (size.lines_all, size.files_all) == (8, 3)


def _bash(command: str) -> int:
    return streamjson.written_lines("Bash", {"command": command})


def test_heredocs_that_write_files_are_counted() -> None:
    assert _bash("cat > app.py <<'EOF'\none\ntwo\nthree\nEOF") == 3
    assert _bash("cat >> app.py <<EOF\nmore\nEOF\nls") == 1
    assert _bash("tee out.txt <<'X' >/dev/null\na\nb\nX") == 2
    script = "python - <<'PY'\nfrom pathlib import Path\nPath('a').write_text('x')\nPY"
    assert _bash(script) == 2
    two = "cat > a <<EOF\n1\nEOF\ncat > b <<EOF\n2\n3\nEOF"
    assert _bash(two) == 3


def test_heredocs_that_do_not_write_files_and_plain_commands_are_not_counted() -> None:
    assert _bash("ls -la") == 0
    assert _bash("python - <<'PY'\nprint(1)\nPY") == 0
    assert _bash("cat <<EOF | grep a\na\nb\nEOF") == 0
    assert _bash("cat /dev/null > /dev/null <<EOF\na\nEOF") == 0
    assert streamjson.written_lines("NotebookEdit", {"new_source": "a\nb"}) == 2


def test_a_mixed_stream_adds_tool_inputs_and_heredocs() -> None:
    usage = {"input_tokens": 1, "output_tokens": 1}
    parsed = streamjson.parse(
        lines(
            assistant(
                "m1",
                usage,
                {"name": "Write", "input": {"content": "a\nb\n"}},
                {"name": "Bash", "input": {"command": "cat > x <<'EOF'\n1\n2\n3\nEOF"}},
            ),
        )
    )
    assert parsed.lines_written == 5
    heredoc_only = streamjson.parse(
        lines(
            assistant("m2", usage, {"name": "Bash", "input": {"command": "cat > x <<EOF\nq\nEOF"}})
        )
    )
    assert heredoc_only.lines_written == 1


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


PUBLISHED_SETS = ("before", "after")


def test_the_docs_page_is_current_for_the_published_data() -> None:
    """The page shows exactly what the committed data sets give, so the raw data is the proof."""
    page = report.PAGE.read_text()
    data = TOKENS / "data"
    sets = [(label, records.load(data / f"{label}.jsonl")) for label in PUBLISHED_SETS]
    assert all(rows for _, rows in sets), "a published data set is missing or empty"
    assert report.splice(page, report.render_sets(sets)) == page, (
        "run scripts/benchmarks/tokens/report.py "
        + " ".join(
            f"--data {label}=scripts/benchmarks/tokens/data/{label}.jsonl"
            for label in PUBLISHED_SETS
        )
    )


def test_the_published_data_names_no_ai_tool() -> None:
    """The project names no AI tool or company: the published runs carry a neutral model label."""
    for label in (*PUBLISHED_SETS, "inventory"):
        for row in records.load(TOKENS / "data" / f"{label}.jsonl"):
            assert row["model"] == "model-A"
            assert row["agent_version"].endswith("(coding-agent CLI)")


# --- the command line the runs use ---------------------------------------------------------------


def test_the_agent_command_is_the_methods_and_the_karni_prompt_starts_with_new_app() -> None:
    command = execute.agent_command(["agent-cli"], "PROMPT", "a-model", Path("m.json"))
    assert command[:3] == ["agent-cli", "-p", "PROMPT"]
    for flag in (
        "--verbose", "--strict-mcp-config", "--no-session-persistence",
        "--dangerously-skip-permissions",
    ):  # fmt: skip
        assert flag in command
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--setting-sources") + 1] == "project"
    assert command[command.index("--model") + 1] == "a-model"
    tasks = TOKENS / "tasks"
    plain = execute.task_prompt(tasks, "shop", "plain")
    karni = execute.task_prompt(tasks, "shop", "karni")
    assert karni == execute.NEW_APP_PREFIX + plain and not plain.startswith("Run `karni")
    assert "`karni rules --procedure new-app`" in execute.NEW_APP_PREFIX
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


def test_a_real_run_names_its_agent_cli_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """No agent or model is built in: --agent/KARNI_BENCH_AGENT and --model/KARNI_BENCH_MODEL."""
    monkeypatch.delenv("KARNI_BENCH_AGENT", raising=False)
    with pytest.raises(SystemExit, match="KARNI_BENCH_AGENT"):
        run_module.resolve_agent(None, fake=False)
    monkeypatch.setenv("KARNI_BENCH_AGENT", sys.executable)
    assert run_module.resolve_agent(None, fake=False) == [sys.executable]
    assert run_module.resolve_agent(None, fake=True)[1].endswith("fake_agent.py")
    with pytest.raises(SystemExit, match="KARNI_BENCH_MODEL"):
        run_module.resolve_model("", fake=False)
    assert run_module.resolve_model("a-model", fake=False) == "a-model"
    assert run_module.resolve_model("", fake=True) == "fake"


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
        agent=[sys.executable, str(execute.FAKE_AGENT)],
        tasks_dir=tmp_path / "tasks",
        data_file=tmp_path / "runs.jsonl",
        database=FakeDatabase(),
        keep=True,
        log=lambda _m: None,
    )
    return config, starts.Start(name="plain", project=project)


@requires_git
def test_a_fake_run_makes_the_folder_the_repo_the_database_and_one_recorded_line(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    argv_log = config.tasks_dir.parent / "argv.json"
    monkeypatch.setenv("FAKE_AGENT_ARGV", str(argv_log))
    record = execute.execute("mini", "plain", 1, start, config, stamp="T1")

    assert record.run_id == "mini-plain-1-T1"
    run_dir = Path(config.tasks_dir.parent / "home" / "runs" / record.run_id)
    project = run_dir / "project"
    assert (project / "fake_note.txt").read_text().startswith("1st") is False  # the fake wrote it
    assert (project / "acceptance" / "test_mini.py").is_file()  # the checks the agent may run
    log = subprocess.run(
        ["git", "-C", str(project), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
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


@requires_git
def test_a_run_over_the_time_limit_is_killed_and_recorded_as_a_failure(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    config.limit_seconds = 1
    monkeypatch.setenv("FAKE_AGENT_SLEEP", "30")
    record = execute.execute("mini", "plain", 2, start, config, stamp="T2")
    assert record.timed_out and record.exit_status == "timeout"
    assert record.wall_seconds < 20
    assert not record.success and not record.result_seen
    assert record.input_tokens == 10  # the first message only: summed, there is no result line
    assert len(records.load(config.data_file)) == 1  # a timed-out run stays in the data
    assert config.database.calls[-1][0] == "drop"


@requires_git
def test_a_crashing_agent_and_a_crashing_harness_both_leave_a_failed_record(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, start = world
    monkeypatch.setenv("FAKE_AGENT_EXIT", "3")
    record = execute.execute("mini", "plain", 3, start, config, stamp="T3")
    assert record.exit_status == 3 and not record.success

    config.agent = ["/nonexistent/agent-cli"]
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


# --- runs the agent CLI did not finish --------------------------------------------------------------


@requires_git
@pytest.mark.parametrize(
    ("env", "kind"),
    [
        ({"FAKE_AGENT_END": "usage_limit"}, "usage_limit"),
        ({"FAKE_AGENT_END": "is_error"}, "api_error"),
        ({"FAKE_AGENT_END": "none"}, "no_result"),
        ({"FAKE_AGENT_END": "none", "FAKE_AGENT_EXIT": "2"}, "exit"),
    ],
)
def test_an_interrupted_run_is_recorded_excluded_and_run_again(
    world: Any, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], kind: str
) -> None:
    config, start = world
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    record = execute.execute("mini", "plain", 1, start, config, stamp="T1")
    assert record.interrupted and record.interrupted_kind == kind and not record.success
    saved = records.load(config.data_file)
    assert saved[0]["interrupted"] is True and saved[0]["interrupted_reason"]
    assert records.done(saved) == set()  # --resume runs it again
    assert report.render(saved).startswith(report.PENDING)
    assert "1 interrupted runs are left out" in report.render(saved)
    if kind == "usage_limit":
        assert record.reset_time.startswith("2030-")


def test_an_error_result_with_a_limit_message_is_a_usage_limit_and_a_time_limit_is_not() -> None:
    def kind(*events: dict[str, Any], status: int | str = 0, late: bool = False) -> str:
        parsed = streamjson.parse(lines(*events))
        return streamjson.interruption(parsed, status, late)[0]

    limit = {"type": "result", "is_error": True, "result": "429 rate_limit_error: slow down"}
    assert kind(limit) == "usage_limit"
    assert kind({"type": "error", "error": {"type": "overloaded_error"}}) == "api_error"
    assert kind({"type": "result", "is_error": True, "result": "boom"}) == "api_error"
    ok = {"type": "result", "is_error": False, "result": "I added a rate limit to the API"}
    assert kind(ok) == ""
    retried = {"type": "system", "subtype": "api_retry", "error_status": 429}
    assert kind(retried, ok) == ""  # it recovered
    assert kind(status="timeout", late=True) == ""  # the time limit is part of the result
    assert kind(status=-9) == "exit"
    reset = streamjson.reset_time_in("Limit reached, resets 3pm (UTC). Thanks")
    assert reset == "3pm (UTC)"


def test_a_usage_limit_stops_the_batch_and_resume_runs_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KARNI_BENCH_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(run_module, "versions", lambda *_a: ("c", "fake"))
    monkeypatch.setattr(run_module, "Postgres", FakeDatabase)
    seen: list[tuple[str, str, int]] = []

    def fake_execute(task: str, condition: str, index: int, _start: Any, config: Any) -> Any:
        seen.append((task, condition, index))
        record = records.RunRecord("r", task, condition, index, "m", "t")
        if len(seen) == 2 and not config.keep:
            record.interrupted, record.interrupted_kind = True, "usage_limit"
            record.interrupted_reason, record.reset_time = "Usage limit reached", "2030-01-01"
        records.append(record, config.data_file)
        return record

    monkeypatch.setattr(run_module.execute, "execute", fake_execute)
    monkeypatch.setattr(run_module.starts, "load", lambda name: name)
    data = tmp_path / "runs.jsonl"
    argv = ["--fake", "--tasks", "shop", "--n", "2", "--data", str(data)]
    assert run_module.main(argv) == 2
    out = capsys.readouterr().out
    assert "usage or rate limit" in out and "2030-01-01" in out and "--resume" in out
    assert len(seen) == 2  # the other runs never started
    seen.clear()

    def fake_ok(task: str, condition: str, index: int, _s: Any, config: Any) -> Any:
        seen.append((task, condition, index))
        record = records.RunRecord("r", task, condition, index, "m", "t")
        records.append(record, config.data_file)
        return record

    monkeypatch.setattr(run_module.execute, "execute", fake_ok)
    assert run_module.main([*argv, "--resume"]) == 0
    assert seen[0] == ("shop", "karni", 1) and len(seen) == 3  # the interrupted one is first


def test_the_report_leaves_interrupted_runs_out_and_refuses_short_cells(tmp_path: Path) -> None:
    rows = [_row("shop", "plain", t) for t in (10, 20, 30)]
    rows.append(
        {**_row("shop", "plain", 999), "interrupted": True, "interrupted_kind": "api_error"}
    )
    text = report.render(rows)
    assert "| shop | plain | 3 | 3 | 100% | 0 |" in text and "999" not in text
    assert "1 interrupted runs are left out of every figure (1 api error)" in text
    short = report.short_cells(rows, 3, ("shop",), ("plain",))
    assert short == []
    assert report.short_cells(rows, 4, ("shop",), ("plain", "karni")) == [
        "shop plain: 3 of 4 completed runs",
        "shop karni: 0 of 4 completed runs",
    ]
    data, page = tmp_path / "d.jsonl", tmp_path / "p.md"
    page.write_text(f"{report.START}\n{report.END}\n")
    data.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert report.main(["--data", str(data), "--page", str(page)]) == 1
    assert page.read_text() == f"{report.START}\n{report.END}\n"


# --- several labelled data sets side by side -----------------------------------------------------


def _set_rows(plain: int, karni: int, tokens: int, commit: str, day: str) -> list[dict[str, Any]]:
    extra = {"model": "m1", "agent_version": "9.9", "started_at": f"{day}T10:00:00"}
    rows: list[dict[str, Any]] = []
    for task in report.TASKS:
        rows += [{**_row(task, "plain", 100 + i), **extra} for i in range(plain)]
        rows += [
            {**_row(task, "karni", tokens + i), **extra, "karni_commit": commit, "build_ok": True}
            for i in range(karni)
        ]
    return rows


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_two_labelled_sets_pool_plain_and_give_one_karni_column_each() -> None:
    before = _set_rows(2, 3, 50, "aaa111", "2026-11-01")
    after = _set_rows(3, 3, 20, "bbb222", "2026-11-05")
    text = report.render_sets([("before", before), ("after", after)])
    header = "| | plain | karni before | karni after |"
    assert header in text
    assert "| Runs completed | 5 | 3 | 3 |" in text  # plain pooled: 2 + 3, per task
    assert "| Runs completed | 15 | 9 | 9 |" in text  # all tasks
    assert "| Output tokens | 0 (0 to 0) | 0 (0 to 0) | 0 (0 to 0) |" in text
    assert "| Total tokens | 101 (100 to 102) | 51 (50 to 52) | 21 (20 to 22) |" in text
    assert "| Total tokens | 303 (300 to 306) | 153 (150 to 156) | 63 (60 to 66) |" in text
    assert "| Frontend builds | 0 of 5 | 3 of 3 | 3 of 3 |" in text
    assert "| Runs that passed every test | 0 of 5 (0%) | 0 of 3 (0%) | 0 of 3 (0%) |" in text
    assert "- **before**: " in text and "Karni commit: aaa111." in text
    assert "Karni commit: bbb222." in text and "run 2026-11-05." in text
    assert "Model: m1. Agent CLI version: 9.9." in text
    assert "plain side does not depend on Karni's version" in text
    assert "### All tasks" in text


def test_each_column_must_have_enough_completed_runs(tmp_path: Path) -> None:
    before = _set_rows(2, 3, 50, "aaa111", "2026-11-01")
    after = _set_rows(1, 2, 20, "bbb222", "2026-11-05")
    sets = [("before", before), ("after", after)]
    only_shop = ("shop",)
    assert report.short_columns(sets, 3, only_shop) == ["shop karni after: 2 of 3 completed runs"]
    assert report.short_columns(sets, 4, only_shop) == [
        "shop plain: 3 of 4 completed runs",
        "shop karni before: 3 of 4 completed runs",
        "shop karni after: 2 of 4 completed runs",
    ]
    page = tmp_path / "p.md"
    page.write_text(f"{report.START}\n{report.END}\n")
    args = [
        "--data", f"before={_write(tmp_path / 'b.jsonl', before)}",
        "--data", f"after={_write(tmp_path / 'a.jsonl', after)}",
        "--page", str(page),
    ]  # fmt: skip
    assert report.main([*args, "--n", "9"]) == 1
    assert page.read_text() == f"{report.START}\n{report.END}\n"


def test_labelled_sets_are_written_and_checked_and_labels_are_required(tmp_path: Path) -> None:
    before = _write(tmp_path / "b.jsonl", _set_rows(1, 1, 50, "aaa111", "2026-11-01"))
    after = _write(tmp_path / "a.jsonl", _set_rows(1, 1, 20, "bbb222", "2026-11-05"))
    page = tmp_path / "p.md"
    page.write_text(f"{report.START}\n{report.END}\n")
    args = ["--data", f"before={before}", "--data", f"after={after}", "--page", str(page)]
    assert report.main([*args, "--n", "1"]) == 0
    assert "karni before | karni after" in page.read_text()
    assert report.main([*args, "--n", "1", "--check"]) == 0
    with pytest.raises(SystemExit):
        report.parse_data_args([f"before={before}", str(after)])
    with pytest.raises(SystemExit):
        report.parse_data_args([f"x={before}", f"x={after}"])


def test_one_unlabelled_data_file_behaves_as_before(tmp_path: Path) -> None:
    rows = [_row(task, "plain", t) for task in report.TASKS for t in (10, 20, 30)]
    assert report.parse_data_args(None) == [("", records.DATA_FILE)]
    assert report.parse_data_args(["x.jsonl"]) == [("", Path("x.jsonl"))]
    page = tmp_path / "p.md"
    page.write_text(f"{report.START}\n{report.END}\n")
    data = _write(tmp_path / "d.jsonl", rows)
    assert report.main(["--data", str(data), "--page", str(page), "--n", "3"]) == 1  # karni short
    both = rows + [_row(task, "karni", t) for task in report.TASKS for t in (1, 2, 3)]
    data = _write(tmp_path / "d.jsonl", both)
    assert report.main(["--data", str(data), "--page", str(page), "--n", "3"]) == 0
    assert page.read_text() == report.splice(page.read_text(), report.render(both))
    assert "### Success" in page.read_text()


def test_the_inventory_tables_are_current_for_the_measured_data() -> None:
    """README.md, docs/index.md and the report show data/inventory.json and nothing else."""
    data = json.loads(inventory.DATA.read_text())
    stale = [
        str(page) for page, text in inventory.render_pages(data).items() if text != page.read_text()
    ]
    assert stale == [], "run scripts/benchmarks/tokens/inventory.py"


def test_the_inventory_measures_one_passing_run_per_app_and_side() -> None:
    data = json.loads(inventory.DATA.read_text())
    cells = sorted((run["task"], run["condition"]) for run in data["runs"])
    assert cells == sorted((task, side) for task in inventory.TASKS for side in ("plain", "karni"))
    assert all(run["success"] for run in data["runs"])
    recorded = {row["run_id"] for row in records.load(TOKENS / "data" / "inventory.jsonl")}
    assert {run["run_id"] for run in data["runs"]} <= recorded


def test_the_inventory_ranges_read_as_words() -> None:
    assert inventory._range([22, 25, 24]) == "22 to 25"
    assert inventory._range([16, 16]) == "16"
    assert inventory._range([0, 0]) == "none"
    assert inventory._range([True, True]) == "yes"
    assert inventory._range([False, False]) == "no"
    assert inventory._range([True, False, True]) == "2 of 3"
