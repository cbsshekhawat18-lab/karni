"""Experimental. A large Karni project, timed: does the tooling still scale?

It makes a project the way a user does (``karni new``, then a ``karni.yaml``
with N entities spread over apps, then ``karni build``) and times what an
agent runs on it again and again: ``karni check`` (cold, cached, and after one
file changed), ``karni context`` (the whole inventory and ``--summary``) and
the project's own tests. The times go to a JSON file. With a baseline, each
time is compared with the baseline's, and the run fails when one grew beyond
the threshold::

    python scripts/benchmark/large_project.py                       # 100 models, vs the baseline
    python scripts/benchmark/large_project.py --models 5 --apps 1   # a quick run
    python scripts/benchmark/large_project.py --record              # write the baseline

Machines differ, so every run first times a fixed piece of pure Python work
(the calibration) and scales the baseline's times by how much slower or
faster this machine is before it compares. A time fails when it is above
``baseline * scale * threshold + slack``: the slack (seconds) keeps a
sub-second step from failing on noise.

The frontend is left out (``frontend/`` is removed after ``karni new``): the
benchmark is about the backend tooling, and it runs without npm. The project
uses SQLite in its own folder and an in-process cache, so it needs no
service.

Override / escape hatch: every number is an option (``--models``, ``--apps``,
``--threshold``, ``--slack``), ``--keep`` leaves the project for a look, and
:func:`spec_text` and :func:`compare` are importable.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "baseline.json"
#: The output's format. It moves only for a breaking change.
VERSION = 1
NOUNS = ("Entry", "Record", "Batch", "Note", "Group", "Item", "Line", "Event", "Rule", "Slot")
#: The steps timed, in order. ``build`` is reported but never compared (it varies the most).
STEPS = (
    "check_cold",
    "check_cached",
    "check_one_edit",
    "context",
    "context_summary",
    "tests",
)


def entity_names(models: int, apps: int) -> dict[str, list[str]]:
    """App label -> entity names: ``models`` entities over ``apps`` apps, in order."""
    per_app = math.ceil(models / apps)
    found: dict[str, list[str]] = {}
    for index in range(models):
        app = index // per_app
        label = f"area{app + 1:02d}"
        noun = NOUNS[(index % per_app) % len(NOUNS)]
        cycle = (index % per_app) // len(NOUNS)
        found.setdefault(label, []).append(f"Area{app + 1:02d}{noun}{cycle + 1 if cycle else ''}")
    return found


def spec_text(models: int, apps: int) -> str:
    """A ``karni.yaml`` with ``models`` entities: a chain of relations in each app, and across.

    Every entity has seven plain fields, a relation to the entity before it
    in its app, and every third one a relation to the first entity of the app
    before. Reads need a signed-in user and writes the ``staff`` role.
    """
    names = entity_names(models, apps)
    lines = [
        "version: 1",
        "app:",
        "  name: Bench",
        "  kind: app",
        "apps:",
    ]
    labels = list(names)
    seed: list[str] = []
    for position, label in enumerate(labels):
        lines += [f"  {label}:", "    entities:"]
        for index, name in enumerate(names[label]):
            lines += [
                f"      {name}:",
                "        fields:",
                '          name: "str:120"',
                '          code: "str:40"',
                '          notes: "text?"',
                '          amount: "decimal:12:2?"',
                "          quantity: int",
                "          active: bool",
                '          happened_on: "date?"',
            ]
            if index:
                lines.append(f"          parent: fk:{names[label][index - 1]}")
            if position and index % 3 == 0:
                previous = labels[position - 1]
                lines.append(f"          source: fk:{previous}.{names[previous][0]}")
            lines += [
                "        search: [name, code]",
                '        access: {read: authenticated, write: "role:staff"}',
            ]
            seed.append(f"{name}: 0")
    lines.append("seed: {" + ", ".join(seed) + "}")
    return "\n".join(lines) + "\n"


def calibrate(rounds: int = 3) -> float:
    """Seconds this machine takes for a fixed piece of pure Python work (the best of ``rounds``)."""
    best = math.inf
    for _ in range(rounds):
        started = time.perf_counter()
        digest = b""
        for number in range(150_000):
            digest = hashlib.sha256(digest + number.to_bytes(4, "big")).digest()
        rows = json.dumps([{"n": number, "s": str(number) * 3} for number in range(60_000)])
        json.loads(rows)
        sorted(str(number)[::-1] for number in range(200_000))
        best = min(best, time.perf_counter() - started)
    return round(best, 4)


def _env(project: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{project / 'db.sqlite3'}",
            "KARNI_CACHE": "locmem",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CI": "1",  # no tips
        }
    )
    for name in ("DJANGO_SETTINGS_MODULE", "VIRTUAL_ENV"):
        env.pop(name, None)
    return env


def _karni(project: Path, *args: str, check: bool = True) -> tuple[float, str]:
    """Run ``karni ARGS`` in ``project``: ``(seconds, output)``."""
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "karni_cli.main", *args],
        cwd=project,
        env=_env(project),
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    if check and proc.returncode != 0:
        raise SystemExit(f"karni {' '.join(args)} failed ({proc.returncode}):\n{output[-4000:]}")
    return seconds, output


def make_project(parent: Path, models: int, apps: int) -> tuple[Path, float]:
    """``karni new`` without the frontend, then ``karni build`` of the spec: ``(root, seconds)``."""
    from karni_cli import scaffold
    from karni_cli.main import app
    from typer.testing import CliRunner

    def no_npm(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr="npm left out")

    scaffold.run_npm = no_npm  # the frontend is removed below: @karni/ui is never built
    result = CliRunner().invoke(app, ["new", "Bench", "--kind", "app", "-o", str(parent)])
    if result.exit_code != 0:
        raise SystemExit(f"karni new failed:\n{result.output}")
    root = parent / "bench"
    shutil.rmtree(root / "frontend")
    (root / "karni.yaml").write_text(spec_text(models, apps), encoding="utf-8")
    seconds, _ = _karni(root, "build")
    return root, seconds


def _cache_files(project: Path) -> list[Path]:
    local = project / ".karni" / "local"
    return sorted(local.glob("check-cache*")) if local.is_dir() else []


def measure(project: Path) -> dict[str, Any]:
    """Time every step of :data:`STEPS` on ``project``."""
    times: dict[str, float] = {}
    for path in _cache_files(project):
        path.unlink()
    times["check_cold"], _ = _karni(project, "check", "--no-frontend")
    times["check_cached"], _ = _karni(project, "check", "--no-frontend")
    edited = next(project.glob("area*/models.py"))
    edited.write_text(edited.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    times["check_one_edit"], _ = _karni(project, "check", "--no-frontend")
    times["context"], context = _karni(project, "context")
    times["context_summary"], _ = _karni(project, "context", "--summary")
    times["tests"], output = _karni(project, "test", "--", "-q", "-p", "no:cacheprovider")
    tail = [line for line in output.strip().splitlines() if " passed" in line]
    return {
        "times": {name: round(value, 3) for name, value in times.items()},
        "tests": tail[-1].strip("= ") if tail else "",
        "context_tokens": math.ceil(len(context) / 4),
    }


def compare(
    current: dict[str, Any], baseline: dict[str, Any], threshold: float, slack: float
) -> list[str]:
    """Each step whose time grew beyond ``baseline * scale * threshold + slack``, explained."""
    scale = current["calibration"] / baseline["calibration"] if baseline.get("calibration") else 1
    if baseline.get("models") != current["models"]:
        return [
            f"the baseline has {baseline.get('models')} models and this run {current['models']}: "
            "compare runs of the same size (--models), or record a baseline for this size"
        ]
    failures = []
    for step in STEPS:
        before = baseline["times"].get(step)
        now = current["times"].get(step)
        if before is None or now is None:
            continue
        allowed = before * scale * threshold + slack
        if now > allowed:
            failures.append(
                f"{step}: {now:.2f}s, above {allowed:.2f}s (baseline {before:.2f}s x scale "
                f"{scale:.2f} x threshold {threshold} + {slack}s slack)"
            )
    return failures


@contextlib.contextmanager
def _workdir(keep: Path | None) -> Iterator[Path]:
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        yield keep
        return
    with tempfile.TemporaryDirectory(prefix="karni-bench-") as folder:
        yield Path(folder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--models", type=int, default=100, help="Entities in the spec (100).")
    parser.add_argument("--apps", type=int, default=10, help="Apps they are spread over (10).")
    parser.add_argument("--out", type=Path, help="Write the times as JSON here.")
    parser.add_argument("--baseline", type=Path, default=BASELINE, help="The baseline JSON.")
    parser.add_argument("--no-compare", action="store_true", help="Only measure.")
    parser.add_argument(
        "--threshold", type=float, default=1.5, help="Fail above this many times the baseline."
    )
    parser.add_argument(
        "--slack", type=float, default=1.0, help="Seconds added to every allowed time (1.0)."
    )
    parser.add_argument("--record", action="store_true", help="Write the run as the baseline.")
    parser.add_argument("--keep", type=Path, help="Make the project in this folder and keep it.")
    args = parser.parse_args(argv)
    if args.models < 1 or args.apps < 1 or args.apps > args.models:
        parser.error("--models and --apps must be 1 or more, with no more apps than models.")
    from karni_cli import __version__

    calibration = calibrate()
    with _workdir(args.keep) as folder:
        project, build_seconds = make_project(folder, args.models, args.apps)
        result = measure(project)
    current = {
        "version": VERSION,
        "karni": __version__,
        "models": args.models,
        "apps": args.apps,
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "calibration": calibration,
        "build": round(build_seconds, 3),
        **result,
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
    failures = compare(current, baseline, args.threshold, args.slack)
    for failure in failures:
        print(f"SLOWER: {failure}", file=sys.stderr)
    if failures:
        print(
            "A step grew beyond the threshold. Find the change that slowed it, or, when the "
            "growth is expected, record a new baseline (--record) and commit it.",
            file=sys.stderr,
        )
        return 1
    print(f"Within {args.threshold}x the baseline ({args.baseline.name}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
