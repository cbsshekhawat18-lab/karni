#!/usr/bin/env python3
"""What each finished benchmark project contains, measured, and the tables that show it.

    python scripts/benchmarks/tokens/inventory.py --measure HOME   # into data/inventory.json
    python scripts/benchmarks/tokens/inventory.py                  # write the tables into the pages
    python scripts/benchmarks/tokens/inventory.py --check          # fail when a page is out of date

HOME is a benchmark home (KARNI_BENCH_HOME) whose runs were made with ``run.py --keep`` and
whose records are HOME/inventory.jsonl. Each kept project is measured the same way for both
conditions: its own Django serves the counts (harness/django_probe.py: API routes and the
methods they answer, sign-in and account routes outside the admin, models in the admin, an
OpenAPI schema), and its files give the rest (React screens, the tests the project ships with,
a typed API client, the production Docker stack, rules for the coding agent). The harness's
acceptance tests are not the project's and are left out.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import paths, records  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "inventory.json"
PROBE = Path(__file__).resolve().parent / "harness" / "django_probe.py"
SKIP = {".venv", "node_modules", "acceptance", "dist", ".git", "__pycache__", ".karni"}
TASKS = ("booking", "crm", "shop")
TASK_NAMES = {"booking": "Booking", "crm": "CRM", "shop": "Shop"}
SHORT = ("<!-- bench:inventory:start -->", "<!-- bench:inventory:end -->")
FULL = ("<!-- bench:inventory-full:start -->", "<!-- bench:inventory-full:end -->")
PAGES = {
    paths.REPO_ROOT / "README.md": SHORT,
    paths.REPO_ROOT / "docs" / "index.md": SHORT,
    paths.REPO_ROOT / "docs" / "benchmarks" / "tokens.md": FULL,
}
#: (key, the row's label): counts first, then what a project has or lacks.
ROWS = (
    ("api_operations", "API operations (route and method)"),
    ("account_routes", "Sign-in and account endpoints, outside the admin"),
    ("admin_models", "Models in the admin"),
    ("frontend_screens", "React screens"),
    ("project_tests", "Tests the project ships with"),
    ("openapi_schema", "OpenAPI schema served"),
    ("typed_api_client", "Typed API client in the frontend"),
    ("production_stack", "Production Docker stack"),
    ("agent_rules", "Rules for the coding agent"),
)


def _files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        found += [Path(dirpath) / name for name in filenames if name.endswith(suffixes)]
    return found


def probe(project: Path) -> dict[str, Any]:
    """Run harness/django_probe.py with the project's own interpreter and settings."""
    database = Path(tempfile.mkdtemp()) / "probe.sqlite3"
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE")
    }
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings", DATABASE_URL=f"sqlite:///{database}",
        KARNI_CACHE="locmem", DEBUG="True", SECRET_KEY="inventory-only-not-secret",
        ALLOWED_HOSTS="*", PYTHONPATH=str(project),
    )  # fmt: skip
    result = subprocess.run(
        [str(project / ".venv" / "bin" / "python"), str(PROBE)],
        cwd=project, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise SystemExit(f"the probe failed in {project}:\n{result.stderr[-2000:]}")
    measured: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return measured


def measure_project(project: Path) -> dict[str, Any]:
    tests = sum(
        len(re.findall(r"^\s*def test_", path.read_text(errors="ignore"), re.MULTILINE))
        for path in _files(project, (".py",))
    )
    source = project / "frontend" / "src"
    screens = (
        [
            path
            for path in _files(source, (".tsx",))
            if ".test." not in path.name and ".stories." not in path.name
            and path.name not in ("main.tsx", "App.tsx")
        ]
        if source.is_dir()
        else []
    )  # fmt: skip
    typed = source.is_dir() and any(
        "export interface paths" in path.read_text(errors="ignore")
        or "export type paths" in path.read_text(errors="ignore")
        for path in _files(source, (".ts",))
    )
    return {
        **probe(project),
        "frontend_screens": len(screens),
        "project_tests": tests,
        "typed_api_client": typed,
        "production_stack": (project / "docker-compose.prod.yml").is_file()
        and (project / "Dockerfile").is_file(),
        "agent_rules": (project / "AGENTS.md").is_file(),
    }


def measure(home: Path) -> dict[str, Any]:
    """Every kept run of HOME, with its record's outcome, as the data file stores it."""
    finished = {row["run_id"]: row for row in records.load(home / "inventory.jsonl")}
    runs = []
    for run_id, row in sorted(finished.items()):
        if row.get("interrupted"):
            continue
        project = home / "runs" / run_id / "project"
        runs.append(
            {
                "task": row["task"],
                "condition": row["condition"],
                "run_id": run_id,
                "karni_commit": row["karni_commit"],
                "passed": f"{row['acceptance_passed']} of {row['acceptance_total']}",
                "success": bool(row["success"]),
                **measure_project(project),
            }
        )
    return {"version": 1, "runs": runs}


def _range(values: list[Any]) -> str:
    if all(isinstance(value, bool) for value in values):
        yes = sum(values)
        return "yes" if yes == len(values) else "no" if yes == 0 else f"{yes} of {len(values)}"
    low, high = min(values), max(values)
    return "none" if high == 0 else str(low) if low == high else f"{low} to {high}"


def by_condition(data: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    return [run for run in data["runs"] if run["condition"] == condition]


def render_short(data: dict[str, Any]) -> str:
    """Plain against Karni, each figure the range over the apps."""
    plain, karni = by_condition(data, "plain"), by_condition(data, "karni")
    lines = [
        "| In the finished app | Plain Django + React | Karni |",
        "|---|---|---|",
        *(
            f"| {label} | {_range([r[key] for r in plain])} | {_range([r[key] for r in karni])} |"
            for key, label in ROWS
        ),
    ]
    return "\n".join(lines)


def render_full(data: dict[str, Any]) -> str:
    """One column per app and condition, then the runs measured."""
    columns = [
        (task, condition)
        for task in TASKS
        for condition in ("plain", "karni")
        if any(r["task"] == task and r["condition"] == condition for r in data["runs"])
    ]
    run = {(r["task"], r["condition"]): r for r in data["runs"]}
    head = " | ".join(
        f"{TASK_NAMES[task]}, {'plain' if condition == 'plain' else 'Karni'}"
        for task, condition in columns
    )
    lines = [f"| In the finished app | {head} |", "|---|" + "---|" * len(columns)]
    for key, label in ROWS:
        cells = " | ".join(_range([run[column][key]]) for column in columns)
        lines.append(f"| {label} | {cells} |")
    passed = " | ".join(run[column]["passed"] for column in columns)
    lines.append(f"| Acceptance tests passed | {passed} |")
    commits = sorted({r["karni_commit"] for r in data["runs"]})
    lines += ["", f"Runs measured: {', '.join(sorted(run[c]['run_id'] for c in columns))} "
              f"(repository commit {', '.join(commits)})."]  # fmt: skip
    return "\n".join(lines)


def splice(page: str, markers: tuple[str, str], section: str, where: Path) -> str:
    start, end = markers
    if page.count(start) != 1 or page.count(end) != 1 or page.index(start) > page.index(end):
        raise SystemExit(f"{where} needs {start} and {end} once each, in that order")
    head, rest = page.split(start)
    _old, tail = rest.split(end)
    return f"{head}{start}\n{section}\n{end}{tail}"


def render_pages(data: dict[str, Any]) -> dict[Path, str]:
    """Each page with its table written in: the updated text, or the page as it is."""
    updated = {}
    for page, markers in PAGES.items():
        section = render_full(data) if markers == FULL else render_short(data)
        updated[page] = splice(page.read_text(), markers, section, page)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--measure", type=Path, metavar="HOME", help="measure HOME's kept runs")
    parser.add_argument("--check", action="store_true", help="fail when a page is out of date")
    args = parser.parse_args(argv)
    if args.measure is not None:
        DATA.write_text(json.dumps(measure(args.measure), indent=1) + "\n")
    data = json.loads(DATA.read_text())
    stale = []
    for page, text in render_pages(data).items():
        if text != page.read_text():
            if args.check:
                stale.append(str(page.relative_to(paths.REPO_ROOT)))
            else:
                page.write_text(text)
    if stale:
        print("Out of date (run scripts/benchmarks/tokens/inventory.py): " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
