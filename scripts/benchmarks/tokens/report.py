#!/usr/bin/env python3
"""Write the results of data/runs.jsonl between markers in docs/benchmarks/tokens.md.

    python scripts/benchmarks/tokens/report.py            # rewrite the section
    python scripts/benchmarks/tokens/report.py --check    # fail when the page is out of date

Per task and condition: the success rate, and for each figure the median, minimum, maximum and
interquartile range over all runs of that cell. Failed runs stay in: a failed run has real
tokens too. Runs the agent CLI did not finish (a usage or rate limit, an API error, a kill) are
interrupted: they are left out of every figure, counted in a note, and the report is not written
while a task and condition has fewer completed runs than --n.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import paths, records, starts, stats  # noqa: E402

START = "<!-- bench:results:start -->"
END = "<!-- bench:results:end -->"
PAGE = paths.REPO_ROOT / "docs" / "benchmarks" / "tokens.md"
PENDING = "The runs are pending. No numbers are published yet."
TASKS = ("booking", "crm", "shop")

Row = dict[str, Any]

#: (heading, how to read the figure from a run)
FIGURES: list[tuple[str, Callable[[Row], float]]] = [
    (
        "Total tokens (input, output, cache read, cache creation)",
        lambda r: (
            r.get("input_tokens", 0)
            + r.get("output_tokens", 0)
            + r.get("cache_read_tokens", 0)
            + r.get("cache_creation_tokens", 0)
        ),
    ),
    ("Input tokens", lambda r: r.get("input_tokens", 0)),
    ("Output tokens", lambda r: r.get("output_tokens", 0)),
    ("Cache-read tokens", lambda r: r.get("cache_read_tokens", 0)),
    ("Cache-creation tokens", lambda r: r.get("cache_creation_tokens", 0)),
    ("Reported cost (USD)", lambda r: r.get("cost_usd", 0.0)),
    ("Tool calls", lambda r: r.get("tool_calls_total", 0)),
    ("Wall time (seconds)", lambda r: r.get("wall_seconds", 0.0)),
    ("Lines the agent wrote itself (Write and Edit)", lambda r: r.get("agent_lines_written", 0)),
    ("Project diff, lines, code only (no lockfiles, node_modules, migrations)",
     lambda r: r.get("diff_lines_code", 0)),
    ("Project diff, lines, everything", lambda r: r.get("diff_lines_all", 0)),
]  # fmt: skip


def number(value: float) -> str:
    return f"{value:,.2f}" if abs(value) < 100 and value != int(value) else f"{value:,.0f}"


def cells(rows: list[Row]) -> dict[tuple[str, str], list[Row]]:
    grouped: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        grouped.setdefault((str(row.get("task")), str(row.get("condition"))), []).append(row)
    return dict(sorted(grouped.items()))


def split(rows: list[Row]) -> tuple[list[Row], list[Row]]:
    """(completed runs, interrupted runs)."""
    return [r for r in rows if not r.get("interrupted")], [r for r in rows if r.get("interrupted")]


def interrupted_note(interrupted: list[Row]) -> str:
    """How many interrupted runs were left out, and why."""
    reasons: dict[str, int] = {}
    for row in interrupted:
        why = str(row.get("interrupted_kind") or "interrupted")
        reasons[why] = reasons.get(why, 0) + 1
    detail = ", ".join(f"{count} {why.replace('_', ' ')}" for why, count in sorted(reasons.items()))
    return (
        f"{len(interrupted)} interrupted runs are left out of every figure ({detail}): the agent "
        "CLI was cut short by a usage or rate limit, an API error or a kill, so the run says "
        "nothing about its condition. Each was run again."
    )


def short_cells(
    rows: list[Row], n: int, tasks: tuple[str, ...] = TASKS,
    conditions: tuple[str, ...] = starts.CONDITIONS,
) -> list[str]:  # fmt: skip
    """The task and condition cells with fewer completed runs than ``n``, as text."""
    counts = {key: len(group) for key, group in cells(split(rows)[0]).items()}
    return [
        f"{task} {condition}: {counts.get((task, condition), 0)} of {n} completed runs"
        for task in tasks
        for condition in conditions
        if counts.get((task, condition), 0) < n
    ]


def render(all_rows: list[Row]) -> str:
    """The markdown between the markers."""
    rows, interrupted = split(all_rows)
    if not rows:
        return PENDING + (f"\n\n{interrupted_note(interrupted)}" if interrupted else "")
    grouped = cells(rows)
    out = [f"{len(rows)} completed runs in the data.", ""]
    if interrupted:
        out += [interrupted_note(interrupted), ""]
    out += [
        "### Success",
        "",
        "| Task | Condition | Runs | Succeeded | Success rate | Hit the time limit |",
    ]
    out += ["|---|---|---:|---:|---:|---:|"]
    for (task, condition), group in grouped.items():
        ok = sum(1 for r in group if r.get("success"))
        late = sum(1 for r in group if r.get("timed_out"))
        out.append(
            f"| {task} | {condition} | {len(group)} | {ok} | {ok / len(group):.0%} | {late} |"
        )
    out += ["", "### Acceptance tests passed (median, of the total)", ""]
    out += ["| Task | Condition | Median passed | Total |", "|---|---|---:|---:|"]
    for (task, condition), group in grouped.items():
        passed = stats.spread([r.get("acceptance_passed", 0) for r in group])
        total = max(r.get("acceptance_total", 0) for r in group)
        out.append(
            f"| {task} | {condition} | {number(passed.median) if passed else '-'} | {total} |"
        )
    for heading, read in FIGURES:
        out += ["", f"### {heading}", ""]
        out += [
            "| Task | Condition | Runs | Median | Min | Max | IQR |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for (task, condition), group in grouped.items():
            s = stats.spread([read(r) for r in group])
            assert s is not None
            out.append(
                f"| {task} | {condition} | {s.n} | {number(s.median)} | {number(s.minimum)} | "
                f"{number(s.maximum)} | {number(s.iqr)} |"
            )
    return "\n".join(out)


def splice(page: str, section: str) -> str:
    """Replace what is between the markers (they must be there, once each)."""
    if page.count(START) != 1 or page.count(END) != 1 or page.index(START) > page.index(END):
        raise SystemExit(f"{PAGE} needs {START} and {END} once each, in that order")
    head, rest = page.split(START)
    _old, tail = rest.split(END)
    return f"{head}{START}\n\n{section}\n\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=records.DATA_FILE)
    parser.add_argument("--page", type=Path, default=PAGE)
    parser.add_argument("--n", type=int, default=5, help="completed runs wanted per cell (5)")
    parser.add_argument("--check", action="store_true", help="fail when the page is out of date")
    args = parser.parse_args(argv)
    page = args.page.read_text()
    rows = records.load(args.data)
    short = short_cells(rows, args.n) if split(rows)[0] else []
    if short:
        print(
            "No comparison written: these have fewer completed runs than asked for "
            "(interrupted runs do not count; run.py --resume):\n  " + "\n  ".join(short)
        )
        return 1
    updated = splice(page, render(rows))
    if args.check:
        if updated != page:
            print(f"{args.page} is out of date: run scripts/benchmarks/tokens/report.py")
            return 1
        return 0
    args.page.write_text(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
