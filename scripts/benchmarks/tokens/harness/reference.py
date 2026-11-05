"""The reference solutions: each task built with Karni, then checked by its acceptance tests.

A reference is a folder under reference/<task>/ with the files that go over a fresh Karni
starting project (karni.yaml and the project's own domain code). The build is
``karni build``, the same command an agent runs. A reference proves the tests can be passed.
It is never shown to the agents under test: the prompt and the project do not contain it.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from . import acceptance, execute, paths, records, starts
from .database import Postgres, database_name


def build_reference(task: str, project: Path, python: Path, env: dict[str, str]) -> float:
    """Copy the task's reference files over the project and run ``karni build``. Returns seconds."""
    source = paths.REFERENCE_DIR / task
    if not source.is_dir():
        raise SystemExit(f"There is no reference solution for {task!r} in {source}")
    for file in sorted(source.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            target = project / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
    started = time.monotonic()
    done = subprocess.run(
        [str(python.parent / "karni"), "build"], cwd=project, env=env, capture_output=True,
        text=True, timeout=1800, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise SystemExit(f"karni build failed for {task}:\n{(done.stdout + done.stderr)[-2500:]}")
    return round(time.monotonic() - started, 1)


def run_reference(task: str, *, keep: bool = False, log: execute.Log = print) -> dict[str, object]:
    """Build the reference for ``task`` and run its acceptance tests. Returns the result."""
    start = starts.load("karni")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    run_dir = paths.home() / "reference-runs" / f"{task}-{stamp}"
    run_dir.mkdir(parents=True)
    project = run_dir / "project"
    starts.clone(start.project, project)
    python = starts.make_venv(project, start)
    db = database_name(f"ref-{task}-{stamp}")
    database = Postgres()
    database.create(db)
    try:
        env = execute.project_env(project, paths.database_url(db), venv=True)
        build_seconds = build_reference(task, project, python, env)
        log(f"{task}: karni build took {build_seconds}s")
        acceptance_dir = paths.TASKS_DIR / task / "acceptance"
        problem = acceptance.migrate(project, python, env)
        outcome = acceptance.TestOutcome()
        if not problem:
            with acceptance.server(project, python, env, acceptance.free_port()) as base_url:
                outcome = acceptance.run_tests(
                    acceptance_dir, base_url, project, python, env, run_dir / "junit.xml"
                )
        built, build_error = acceptance.build_frontend(project, env)
        result: dict[str, object] = {
            "task": task,
            "passed": outcome.passed,
            "total": outcome.total or acceptance.count_tests(acceptance_dir),
            "frontend_build": built,
            "build_seconds": build_seconds,
            "error": problem or outcome.error or build_error,
        }
        log(f"{task}: {result}")
        return result
    finally:
        database.drop(db)
        if not keep:
            shutil.rmtree(run_dir, ignore_errors=True)


__all__ = ["records", "run_reference"]
