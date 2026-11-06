"""Experimental. What a user waits for with Karni, timed: does making an app stay fast?

``large_project.py`` times the tooling on a big project. This script times
what a person does on a small one, from the first command to a running
backend::

    karni new --recipe <name>     each recipe from scratch (its build steps are listed too)
    karni build, no spec change   a second build: it must stay near instant
    karni check                   cold and cached, on a recipe project
    karni spec validate, karni plan, karni plan --questions
    /new-app                      the fake-agent flow, end to end (no language model)

The times go to a JSON file. With a baseline each time is compared with the
baseline's, and the run fails when one grew beyond the budget::

    python scripts/benchmark/speed.py                  # every recipe, vs the baseline
    python scripts/benchmark/speed.py --recipes shop --runs 1 --no-compare
    python scripts/benchmark/speed.py --record         # write the baseline

A budget is ``baseline * scale * threshold + slack``. ``scale`` is how much
slower or faster this machine is than the one that recorded the baseline,
from the same calibration ``large_project.py`` uses. The no-change rebuild
has no baseline: it fails above an absolute ceiling (``--rebuild-ceiling``)
because it has to stay near instant on any machine.

Each time is the median of ``--runs`` runs (the quick steps) or of
``--build-runs`` runs (the from-scratch builds, which take a minute each).
The frontend is left out: npm and the frontend tools are stubbed as the test
suite does, so the run needs no Node. Every project uses SQLite in its own
folder and an in-process cache, so it needs no service.

Override / escape hatch: every number is an option, ``--keep`` leaves the
projects for a look, and :func:`compare` and :func:`median` are importable.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "speed-baseline.json"
TEMPLATE = ROOT / "templates" / "project"
#: The output's format. It moves only for a breaking change.
VERSION = 1
#: The steps timed on one recipe project, in order (``new_<recipe>`` and ``new_app`` come first).
QUICK = (
    "build_nochange",
    "check_cold",
    "check_cached",
    "spec_validate",
    "plan",
    "plan_questions",
)
#: The no-change rebuild's own ceiling (seconds), whatever the machine: it has to stay near instant.
REBUILD_CEILING = 5.0


def _large() -> ModuleType:
    """``large_project.py``: its calibration and its way of running ``karni`` in a project."""
    path = Path(__file__).resolve().parent / "large_project.py"
    spec = importlib.util.spec_from_file_location("karni_benchmark_large_project", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def median(values: list[float]) -> float:
    """The median, rounded to the millisecond."""
    return round(statistics.median(values), 3)


@contextlib.contextmanager
def _in_process(root: Path) -> Iterator[None]:
    """The environment ``karni new`` runs in: SQLite, a local cache, no npm, no frontend tools."""
    from karni_cli import project as project_mod
    from karni_cli import scaffold
    from karni_cli.commands import check as check_mod
    from karni_cli.commands import types as types_mod

    def no_npm(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr="npm left out")

    def types_stub(project: Path, schema: Path, out: Path) -> list[str]:
        code = "import sys; open(sys.argv[1], 'w').write('export type paths = {};\\n')"
        return [sys.executable, "-c", code, str(out)]

    saved_env = dict(os.environ)
    os.environ.update(
        {
            "DATABASE_URL": f"sqlite:///{root / 'db.sqlite3'}",
            "KARNI_CACHE": "locmem",
            "KARNI_TEMPLATES": str(TEMPLATE),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    # CI would make a missing frontend/node_modules fail the build's check step
    for name in (
        "CI",
        "DJANGO_SETTINGS_MODULE",
        "VIRTUAL_ENV",
        "KARNI_PAYMENTS_PROVIDER",
        "KARNI_2FA",
    ):
        os.environ.pop(name, None)
    saved = (
        scaffold.run_npm,
        project_mod._running_interpreter,
        types_mod._openapi_typescript_cmd,
        check_mod._frontend_lint,
        check_mod._frontend_duplication,
    )
    scaffold.run_npm = no_npm
    project_mod._running_interpreter = lambda: Path(sys.executable)  # type: ignore[assignment]
    types_mod._openapi_typescript_cmd = types_stub  # type: ignore[assignment]
    check_mod._frontend_lint = lambda project, capture=None: 0  # type: ignore[assignment]
    check_mod._frontend_duplication = lambda project, capture=None: 0  # type: ignore[assignment]
    try:
        yield
    finally:
        (
            scaffold.run_npm,
            project_mod._running_interpreter,
            types_mod._openapi_typescript_cmd,
            check_mod._frontend_lint,
            check_mod._frontend_duplication,
        ) = saved  # type: ignore[assignment]
        os.environ.clear()
        os.environ.update(saved_env)


def new_recipe(parent: Path, name: str) -> tuple[Path, float, dict[str, float]]:
    """``karni new --recipe name``, every build step real: ``(root, seconds, seconds per step)``."""
    from karni_cli.builder import run
    from karni_cli.main import app
    from typer.testing import CliRunner

    root = parent / f"demo_{name.replace('-', '_')}"
    steps: dict[str, float] = {}
    saved = dict(run.STEP_RUNNERS)

    def timed(step: str, runner: Callable[..., str]) -> Callable[..., str]:
        def wrapper(*args: Any) -> str:
            started = time.perf_counter()
            try:
                return runner(*args)
            finally:
                steps[step] = round(time.perf_counter() - started, 3)

        return wrapper

    for step, runner in saved.items():
        run.STEP_RUNNERS[step] = timed(step, runner)
    try:
        with _in_process(root):
            started = time.perf_counter()
            result = CliRunner().invoke(
                app, ["new", f"Demo {name}", "--recipe", name, "-o", str(parent)]
            )
            seconds = time.perf_counter() - started
    finally:
        run.STEP_RUNNERS.clear()
        run.STEP_RUNNERS.update(saved)
    if result.exit_code != 0:
        raise SystemExit(f"karni new --recipe {name} failed:\n{result.output[-4000:]}")
    return root, round(seconds, 3), steps


def new_app_flow(parent: Path) -> tuple[float, dict[str, float]]:
    """The /new-app flow with the test suite's scripted fake agent: ``(seconds, per step)``."""
    sys.path.insert(0, str(ROOT / "packages" / "karni-cli"))
    try:
        from tests import test_new_app as flow_mod
    finally:
        sys.path.pop(0)
    from karni_cli import mcp_server
    from karni_cli.main import app
    from typer.testing import CliRunner

    root = parent / "reading_log"
    with _in_process(root):
        started = time.perf_counter()
        created = CliRunner().invoke(app, ["new", "Reading Log", "-o", str(parent)])
        if created.exit_code != 0:
            raise SystemExit(f"karni new failed:\n{created.output[-4000:]}")
        saved_override = mcp_server._project_override
        mcp_server._project_override = root  # type: ignore[assignment]
        cwd = Path.cwd()
        os.chdir(root)
        flow = flow_mod.Flow(root)
        try:
            flow.steps.append(("karni new", time.perf_counter() - started))
            flow_mod._agent(flow, flow_mod.REQUEST)
            seconds = time.perf_counter() - started
        finally:
            os.chdir(cwd)
            mcp_server._project_override = saved_override  # type: ignore[assignment]
    return round(seconds, 3), {name: round(value, 3) for name, value in flow.steps}


def _cache_files(project: Path) -> list[Path]:
    local = project / ".karni" / "local"
    return sorted(local.glob("check-cache*")) if local.is_dir() else []


def measure_quick(project: Path, runs: int) -> dict[str, float]:
    """The median of ``runs`` runs of each step of :data:`QUICK` on a built recipe project."""
    large = _large()

    def once(step: str, *args: str, cold: bool = False) -> float:
        if cold:
            for path in _cache_files(project):
                path.unlink()
        seconds, _ = large._karni(project, *args)
        return seconds

    found: dict[str, list[float]] = {step: [] for step in QUICK}
    once("check_cached", "check", "--no-frontend")  # fills the cache and the pyc-less warm-up
    for _ in range(runs):
        found["build_nochange"].append(once("build_nochange", "build"))
        found["check_cold"].append(once("check_cold", "check", "--no-frontend", cold=True))
        found["check_cached"].append(once("check_cached", "check", "--no-frontend"))
        found["spec_validate"].append(once("spec_validate", "spec", "validate"))
        found["plan"].append(once("plan", "plan", "--offline"))
        found["plan_questions"].append(once("plan_questions", "plan", "--questions", "--offline"))
    return {step: median(values) for step, values in found.items()}


def compare(
    current: dict[str, Any],
    baseline: dict[str, Any],
    threshold: float,
    slack: float,
    build_slack: float,
    rebuild_ceiling: float = REBUILD_CEILING,
) -> list[str]:
    """Each time above its budget, explained. ``new_*`` and ``new_app`` get ``build_slack``."""
    scale = current["calibration"] / baseline["calibration"] if baseline.get("calibration") else 1
    failures = []
    for step, now in current["times"].items():
        if step == "build_nochange":
            if now > rebuild_ceiling:
                failures.append(
                    f"{step}: {now:.2f}s, above the {rebuild_ceiling:.1f}s ceiling "
                    "(a rebuild with no spec change has to stay near instant)"
                )
            continue
        before = baseline["times"].get(step)
        if before is None:
            continue
        extra = build_slack if step.startswith("new_") else slack
        allowed = before * scale * threshold + extra
        if now > allowed:
            failures.append(
                f"{step}: {now:.2f}s, above {allowed:.2f}s (baseline {before:.2f}s x scale "
                f"{scale:.2f} x threshold {threshold} + {extra}s slack)"
            )
    return failures


@contextlib.contextmanager
def _workdir(keep: Path | None) -> Iterator[Path]:
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        yield keep
        return
    with tempfile.TemporaryDirectory(prefix="karni-speed-") as folder:
        yield Path(folder)


def _recipe_names() -> list[str]:
    from karni_cli import recipes as recipes_mod

    return sorted(recipes_mod.load(installed=False).recipes)


def _load() -> str:
    with contextlib.suppress(OSError):
        return " ".join(f"{value:.2f}" for value in os.getloadavg())
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--recipes", nargs="*", help="The recipes to time (every built-in one).")
    parser.add_argument("--runs", type=int, default=3, help="Runs of each quick step (3).")
    parser.add_argument(
        "--build-runs", type=int, default=1, help="Runs of each from-scratch build (1)."
    )
    parser.add_argument("--no-new-app", action="store_true", help="Leave the /new-app flow out.")
    parser.add_argument("--out", type=Path, help="Write the times as JSON here.")
    parser.add_argument("--baseline", type=Path, default=BASELINE, help="The baseline JSON.")
    parser.add_argument("--no-compare", action="store_true", help="Only measure.")
    parser.add_argument(
        "--threshold", type=float, default=1.5, help="Fail above this many times the baseline."
    )
    parser.add_argument(
        "--slack", type=float, default=1.0, help="Seconds added to a quick step's budget (1.0)."
    )
    parser.add_argument(
        "--build-slack",
        type=float,
        default=10.0,
        help="Seconds added to a from-scratch build's budget (10).",
    )
    parser.add_argument(
        "--rebuild-ceiling",
        type=float,
        default=REBUILD_CEILING,
        help="Seconds a no-change rebuild may take (5).",
    )
    parser.add_argument("--record", action="store_true", help="Write the run as the baseline.")
    parser.add_argument(
        "--note", default="", help="A line stored with the baseline (the machine, the load)."
    )
    parser.add_argument("--keep", type=Path, help="Make the projects in this folder and keep it.")
    args = parser.parse_args(argv)
    if args.runs < 1 or args.build_runs < 1:
        parser.error("--runs and --build-runs must be 1 or more.")
    from karni_cli import __version__

    names = args.recipes if args.recipes is not None else _recipe_names()
    unknown = sorted(set(names) - set(_recipe_names()))
    if unknown:
        parser.error(f"unknown recipe: {', '.join(unknown)}")
    large = _large()
    load_before = _load()
    calibration = large.calibrate()
    times: dict[str, float] = {}
    inner: dict[str, dict[str, float]] = {}
    quick_project: Path | None = None
    with _workdir(args.keep) as folder:
        for name in names:
            seconds: list[float] = []
            per_step: list[dict[str, float]] = []
            for number in range(args.build_runs):
                parent = folder / f"{name}-{number}"
                parent.mkdir()
                root, took, steps = new_recipe(parent, name)
                seconds.append(took)
                per_step.append(steps)
                if quick_project is None and number == args.build_runs - 1:
                    quick_project = (
                        root  # the first recipe's last project: the quick steps run on it
                    )
                else:
                    shutil.rmtree(parent, ignore_errors=True)
            times[f"new_{name}"] = median(seconds)
            inner[f"new_{name}"] = {
                step: median([found[step] for found in per_step if step in found])
                for step in per_step[0]
            }
            print(f"new --recipe {name}: {times[f'new_{name}']}s", file=sys.stderr)
        if not args.no_new_app:
            seconds = []
            flows: list[dict[str, float]] = []
            for number in range(args.build_runs):
                parent = folder / f"new-app-{number}"
                parent.mkdir()
                took, steps = new_app_flow(parent)
                seconds.append(took)
                flows.append(steps)
                shutil.rmtree(parent, ignore_errors=True)
            times["new_app"] = median(seconds)
            inner["new_app"] = {step: median([found[step] for found in flows]) for step in flows[0]}
            print(f"/new-app flow: {times['new_app']}s", file=sys.stderr)
        if quick_project is not None:
            times.update(measure_quick(quick_project, args.runs))
    current = {
        "version": VERSION,
        "karni": __version__,
        "recipes": names,
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "calibration": calibration,
        "load_before": load_before,
        "load_after": _load(),
        "runs": args.runs,
        "build_runs": args.build_runs,
        "note": args.note,
        "times": times,
        "inner": inner,
    }
    text = json.dumps(current, indent=2) + "\n"
    print(text, end="")
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    if args.record:
        args.baseline.write_text(text, encoding="utf-8")
        print(f"Recorded the baseline in {args.baseline}.")
        return 0
    if args.no_compare or not args.baseline.is_file():
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = compare(
        current, baseline, args.threshold, args.slack, args.build_slack, args.rebuild_ceiling
    )
    for failure in failures:
        print(f"SLOWER: {failure}", file=sys.stderr)
    if failures:
        print(
            "A step went over its budget. Find the change that slowed it, or, when the growth "
            "is expected, record a new baseline (--record) on a quiet machine and commit it.",
            file=sys.stderr,
        )
        return 1
    print(f"Within budget ({args.baseline.name}, {args.threshold}x the baseline).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
