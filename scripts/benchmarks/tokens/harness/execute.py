"""One run: a fresh folder, the agent, then the harness's own checks, then one record."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import acceptance, diffsize, paths, records, starts, streamjson
from .database import DatabaseAdmin, database_name

#: The model of every run: --model, else KARNI_BENCH_MODEL. Empty means not chosen yet.
DEFAULT_MODEL = os.environ.get("KARNI_BENCH_MODEL", "")
DEFAULT_LIMIT_SECONDS = 60 * 60
FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent.py"
#: How the Karni condition's prompt starts: the new-app procedure that AGENTS.md lists,
#: asked for in words, so no tool's own command files are needed.
NEW_APP_PREFIX = "Run `karni rules --procedure new-app` and follow every step for this request:\n\n"
NODE_BIN = "/opt/homebrew/bin"

Log = Callable[[str], None]


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    limit_seconds: float = DEFAULT_LIMIT_SECONDS
    #: The agent CLI and its leading arguments (--agent, else KARNI_BENCH_AGENT).
    agent: list[str] = field(default_factory=list)
    tasks_dir: Path = paths.TASKS_DIR
    data_file: Path = records.DATA_FILE
    database: DatabaseAdmin | None = None
    keep: bool = False
    log: Log = print
    karni_commit: str = ""
    agent_version: str = ""


def run_id_for(task: str, condition: str, index: int, stamp: str) -> str:
    return f"{task}-{condition}-{index}-{stamp}"


def task_prompt(tasks_dir: Path, task: str, condition: str) -> str:
    """The prompt both conditions get: the request, the contract, the common rules.

    The Karni condition starts it with the new-app procedure (:data:`NEW_APP_PREFIX`).
    """
    folder = tasks_dir / task
    parts = [
        (folder / "prompt.md").read_text().strip(),
        "## The API contract\n\n" + (folder / "contract.md").read_text().strip(),
    ]
    common = tasks_dir / "common.md"
    if common.is_file():
        parts.append(common.read_text().strip())
    text = "\n\n".join(parts)
    return NEW_APP_PREFIX + text if condition == "karni" else text


def agent_command(agent: list[str], prompt: str, model: str, mcp_config: Path) -> list[str]:
    """The command from the method (docs/benchmarks/tokens.md), the same for both conditions."""
    return [
        *agent,
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--mcp-config", str(mcp_config),
        "--no-session-persistence",
        "--dangerously-skip-permissions",
    ]  # fmt: skip


def project_env(project: Path, db_url: str, *, venv: bool) -> dict[str, str]:
    """The environment of the agent and of the harness's checks: the same for both."""
    env = {
        k: v for k, v in os.environ.items() if k not in ("DJANGO_SETTINGS_MODULE", "VIRTUAL_ENV")
    }
    bin_dirs = [NODE_BIN]
    if venv:
        bin_dirs.insert(0, str(project / ".venv" / "bin"))
        env["VIRTUAL_ENV"] = str(project / ".venv")
    env["PATH"] = os.pathsep.join([*bin_dirs, env.get("PATH", "")])
    env["DATABASE_URL"] = db_url
    env["KARNI_CACHE"] = "locmem"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CI"] = "1"
    return env


def run_agent(
    command: list[str], project: Path, env: dict[str, str], stream: Path, errors: Path,
    limit: float,
) -> tuple[int | str, bool, float]:  # fmt: skip
    """Run the agent with a wall-clock limit. Returns (exit status, timed out, seconds)."""
    started = time.monotonic()
    with stream.open("wb") as out, errors.open("wb") as err:
        process = subprocess.Popen(
            command, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            start_new_session=True,
        )  # fmt: skip
        try:
            status: int | str = process.wait(timeout=limit)
            timed_out = False
        except subprocess.TimeoutExpired:
            acceptance.kill_group(process)
            status, timed_out = "timeout", True
    return status, timed_out, round(time.monotonic() - started, 2)


def prepare_run(run_dir: Path, start: starts.Start, task_dir: Path) -> tuple[Path, Path | None]:
    """The run's folder: the project copied in with its venv and the checks, one git commit."""
    project = run_dir / "project"
    starts.clone(start.project, project)
    python = starts.make_venv(project, start) if start.wheelhouse is not None else None
    if start.mcp:
        mcp_config = starts.write_mcp(project)
    else:
        mcp_config = run_dir / "mcp-empty.json"
        mcp_config.write_text('{"mcpServers": {}}\n')
    shutil.copytree(task_dir / "acceptance", project / "acceptance")
    diffsize.commit_start(project)
    return mcp_config, python


def execute(
    task: str, condition: str, index: int, start: starts.Start, config: Config,
    stamp: str | None = None,
) -> records.RunRecord:  # fmt: skip
    """One run, start to finish. It always returns a record, and a failure is a record too."""
    now = datetime.now(UTC)
    stamp = stamp or now.strftime("%Y%m%dT%H%M%S")
    run_id = run_id_for(task, condition, index, stamp)
    record = records.RunRecord(
        run_id=run_id, task=task, condition=condition, index=index, model=config.model,
        started_at=now.isoformat(timespec="seconds"), karni_commit=config.karni_commit,
        agent_version=config.agent_version,
    )  # fmt: skip
    run_dir = paths.home() / "runs" / run_id
    db_name = database_name(run_id)
    database = config.database
    created = False
    try:
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True)
        project = run_dir / "project"
        mcp_config, python = prepare_run(run_dir, start, config.tasks_dir / task)
        python_path = python or Path(sys.executable)
        db_url = paths.database_url(db_name)
        env = project_env(project, db_url, venv=python is not None)
        if database is not None:
            database.create(db_name)
            created = True
        prompt = task_prompt(config.tasks_dir, task, condition)
        command = agent_command(config.agent, prompt, config.model, mcp_config)
        config.log(f"{run_id}: agent started (limit {config.limit_seconds:.0f}s)")
        record.exit_status, record.timed_out, record.wall_seconds = run_agent(
            command, project, env, run_dir / "stream.jsonl", run_dir / "stderr.log",
            config.limit_seconds,
        )  # fmt: skip
        stats = streamjson.parse(
            (run_dir / "stream.jsonl").read_text(errors="replace").splitlines()
        )
        record.input_tokens = stats.input_tokens
        record.output_tokens = stats.output_tokens
        record.cache_read_tokens = stats.cache_read_tokens
        record.cache_creation_tokens = stats.cache_creation_tokens
        record.cost_usd = stats.cost_usd
        record.tool_calls = stats.tool_calls
        record.tool_calls_total = stats.tool_calls_total
        record.agent_lines_written = stats.lines_written
        record.result_seen = stats.result_seen
        size = diffsize.measure(project)
        record.diff_lines_all, record.diff_lines_code = size.lines_all, size.lines_code
        record.diff_files_all, record.diff_files_code = size.files_all, size.files_code
        check(record, config, task, project, python_path, env, run_dir)
    except Exception as exc:  # a crashed run is a failure in the data, never dropped
        record.error = record.error or f"{type(exc).__name__}: {exc}"
        if record.exit_status == "not-run":
            record.exit_status = "crash"
    finally:
        if created and database is not None:
            try:
                database.drop(db_name)
            except Exception as exc:  # the data matters more than the cleanup
                config.log(f"{run_id}: could not drop {db_name}: {exc}")
        if not config.keep and run_dir.exists():
            shutil.rmtree(run_dir / "project", ignore_errors=True)
    record.finish()
    records.append(record, config.data_file)
    config.log(
        f"{run_id}: {'ok' if record.success else 'FAILED'} "
        f"{record.acceptance_passed}/{record.acceptance_total} tests, build "
        f"{'ok' if record.build_ok else 'failed'}, {record.wall_seconds:.0f}s"
    )
    return record


def check(
    record: records.RunRecord, config: Config, task: str, project: Path, python: Path,
    env: dict[str, str], run_dir: Path,
) -> None:  # fmt: skip
    """The harness's own checks after the agent stopped: migrate, serve, test, build."""
    acceptance_dir = config.tasks_dir / task / "acceptance"
    problem = acceptance.migrate(project, python, env)
    if not problem:
        try:
            with acceptance.server(project, python, env, acceptance.free_port()) as base_url:
                outcome = acceptance.run_tests(
                    acceptance_dir, base_url, project, python, env, run_dir / "junit.xml"
                )
        except RuntimeError as exc:
            problem = str(exc)
        else:
            record.acceptance_passed, record.acceptance_total = outcome.passed, outcome.total
            problem = outcome.error
    if problem:
        record.error = problem
        record.acceptance_total = record.acceptance_total or acceptance.count_tests(acceptance_dir)
    record.build_ok, build_error = acceptance.build_frontend(project, env)
    if build_error and not record.error:
        record.error = build_error
