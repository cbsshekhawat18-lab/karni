#!/usr/bin/env python3
"""The token benchmark runner. Method, commands and limits: docs/benchmarks/tokens.md.

python scripts/benchmarks/tokens/run.py --build-starts          # once, installs everything
python scripts/benchmarks/tokens/run.py --reference shop        # the reference passes its tests
python scripts/benchmarks/tokens/run.py --dry-run               # print the plan and commands
python scripts/benchmarks/tokens/run.py --resume                # the 30 real runs
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import execute, order, paths, records, starts  # noqa: E402
from harness.database import Postgres, database_name  # noqa: E402

TASKS = ("booking", "crm", "shop")
DEFAULT_N = 5


def resolve_agent(explicit: str | None, fake: bool) -> list[str]:
    """The agent CLI: --agent, else KARNI_BENCH_AGENT (a name on PATH or a path)."""
    if fake:
        return [sys.executable, str(execute.FAKE_AGENT)]
    named = explicit or os.environ.get("KARNI_BENCH_AGENT", "")
    found = shutil.which(named) if named else None
    if not found:
        raise SystemExit(
            "No agent CLI: pass --agent NAME_OR_PATH or set KARNI_BENCH_AGENT "
            f"(found nothing for {named!r})."
            if named
            else "No agent CLI: pass --agent NAME_OR_PATH or set KARNI_BENCH_AGENT."
        )
    return [found]


def resolve_model(explicit: str, fake: bool) -> str:
    """The model: --model, else KARNI_BENCH_MODEL. The fake agent needs none."""
    if explicit or fake:
        return explicit or "fake"
    raise SystemExit("No model: pass --model NAME or set KARNI_BENCH_MODEL.")


def versions(agent: list[str], fake: bool) -> tuple[str, str]:
    """The checkout's commit and the agent CLI's version, recorded with every run."""
    commit = subprocess.run(
        ["git", "-C", str(paths.REPO_ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    if fake:
        return commit, "fake"
    done = subprocess.run([*agent, "--version"], capture_output=True, text=True, check=False)
    return commit, done.stdout.strip()


def describe(
    task: str, condition: str, index: int, config: execute.Config, show_prompt: bool
) -> str:
    run_id = execute.run_id_for(task, condition, index, "<time>")
    prompt = execute.task_prompt(config.tasks_dir, task, condition)
    shown = prompt if show_prompt else f"<prompt: {len(prompt)} characters, starts {prompt[:40]!r}>"
    command = execute.agent_command(
        config.agent,
        "@PROMPT@",
        config.model,
        Path("<project>/.mcp.json" if condition == "karni" else "<run>/mcp-empty.json"),
    )
    line = shlex.join(command).replace(
        "@PROMPT@", shlex.quote(shown) if not show_prompt else shlex.quote(prompt)
    )
    return "\n".join([
        f"== {run_id}",
        f"   start   copy starts/{condition}/project to runs/{run_id}/project, make its venv, "
        "git commit",
        f"   db      create {database_name(run_id)} on {paths.DATABASE_HOST}:{paths.DATABASE_PORT}",
        f"   agent   (in the project, killed after {config.limit_seconds / 60:.0f} minutes) {line}",
        "   checks  manage.py migrate, runserver on a free port in 8700-8799, pytest acceptance, "
        "npm run build in frontend/",
        f"   end     drop {database_name(run_id)}, append one line to {config.data_file}",
    ])  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--tasks", default=",".join(TASKS), help="comma-separated (default: all three)"
    )
    parser.add_argument(
        "--conditions", default=",".join(starts.CONDITIONS), help="plain, karni or both"
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="runs per task and condition (5)")
    parser.add_argument(
        "--model", default=execute.DEFAULT_MODEL, help="the model (default: KARNI_BENCH_MODEL)"
    )
    parser.add_argument("--limit-minutes", type=float, default=60, help="per run (60)")
    parser.add_argument("--fake", action="store_true", help="use the fake agent (no usage spent)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and commands only")
    parser.add_argument(
        "--show-prompt", action="store_true", help="with --dry-run: the full prompts"
    )
    parser.add_argument(
        "--resume", action="store_true", help="skip finished runs (interrupted ones run again)"
    )
    parser.add_argument("--keep", action="store_true", help="keep each run's project folder")
    parser.add_argument("--agent", help="the agent CLI (default: KARNI_BENCH_AGENT)")
    parser.add_argument(
        "--data", type=Path, default=records.DATA_FILE, help="the runs.jsonl to use"
    )
    parser.add_argument(
        "--build-starts", action="store_true", help="build the cached starting projects"
    )
    parser.add_argument(
        "--reference", choices=TASKS, help="build a task's reference, run its tests"
    )
    args = parser.parse_args(argv)
    # karni-cli prefers VIRTUAL_ENV: a run must never depend on the caller's shell.
    os.environ.pop("VIRTUAL_ENV", None)
    os.environ.pop("DJANGO_SETTINGS_MODULE", None)

    if args.build_starts:
        for name in starts.CONDITIONS:
            print(f"building the {name} starting project ...", flush=True)
            starts.build(name)
        return 0
    if args.reference:
        from harness import reference

        result = reference.run_reference(args.reference, keep=args.keep)
        return 0 if result["passed"] == result["total"] and result["frontend_build"] else 1

    tasks = [t for t in args.tasks.split(",") if t]
    conditions = [c for c in args.conditions.split(",") if c]
    unknown = [t for t in tasks if not (paths.TASKS_DIR / t).is_dir()] + [
        c for c in conditions if c not in starts.CONDITIONS
    ]
    if unknown:
        raise SystemExit(f"Unknown task or condition: {', '.join(unknown)}")
    if args.dry_run:
        agent = (
            [sys.executable, str(execute.FAKE_AGENT)]
            if args.fake
            else [args.agent or os.environ.get("KARNI_BENCH_AGENT") or "<agent>"]
        )
        model = args.model or ("fake" if args.fake else "<model>")
    else:
        agent = resolve_agent(args.agent, args.fake)
        model = resolve_model(args.model, args.fake)
    plan = order.plan(tasks, conditions, args.n)
    if args.resume:
        finished = records.done(records.load(args.data))
        plan = [run for run in plan if run not in finished]
    config = execute.Config(
        model=model, limit_seconds=args.limit_minutes * 60, agent=agent,
        data_file=args.data, keep=args.keep,
    )  # fmt: skip
    if args.dry_run:
        print(f"{len(plan)} runs, in this order: plain and karni alternate")
        for task, condition, index in plan:
            print(describe(task, condition, index, config, args.show_prompt))
        return 0
    config.karni_commit, config.agent_version = versions(agent, args.fake)
    config.database = Postgres()
    loaded = {name: starts.load(name) for name in conditions}
    for number, (task, condition, index) in enumerate(plan, 1):
        print(f"[{number}/{len(plan)}] {task} {condition} #{index}", flush=True)
        record = execute.execute(task, condition, index, loaded[condition], config)
        if record.interrupted_kind == "usage_limit":
            when = f" It resets: {record.reset_time}." if record.reset_time else ""
            print(
                f"Stopped: {record.run_id} was cut short by a usage or rate limit "
                f"({record.interrupted_reason}).{when} The run is not counted. "
                "Run the same command with --resume to continue from here.",
                flush=True,
            )
            return 2
    interrupted = [r for r in records.load(args.data) if r.get("interrupted")]
    if interrupted:
        print(f"{len(interrupted)} runs in the data were interrupted; --resume runs them again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
