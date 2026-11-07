#!/usr/bin/env python3
"""Write the results of data/runs.jsonl between markers in docs/benchmarks/tokens.md.

    python scripts/benchmarks/tokens/report.py            # rewrite the section
    python scripts/benchmarks/tokens/report.py --check    # fail when the page is out of date

Per task and condition: the success rate, and for each figure the median, minimum, maximum and
interquartile range over all runs of that cell. Failed runs stay in: a failed run has real
tokens too. Runs the agent CLI did not finish (a usage or rate limit, an API error, a kill) are
interrupted: they are left out of every figure, counted in a note, and the report is not written
while a task and condition has fewer completed runs than --n.

Several labelled data sets give side-by-side columns (plain Django, Karni before, Karni after):

    python scripts/benchmarks/tokens/report.py --data before=before.jsonl --data after=after.jsonl

The plain rows of every set are pooled into one column (plain does not depend on Karni's
version); each label gets its own Karni column, in the order given. One unlabelled --data (or
none) writes the single-set report.
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


#: A set of runs under a label: ``--data LABEL=PATH``.
DataSet = tuple[str, list[Row]]

#: (name, how to read the figure) for the side-by-side tables, as median with min to max.
COLUMN_FIGURES: list[tuple[str, Callable[[Row], float]]] = [
    ("Output tokens", lambda r: r.get("output_tokens", 0)),
    ("Cache-read tokens", lambda r: r.get("cache_read_tokens", 0)),
    ("Total tokens", FIGURES[0][1]),
    ("Cost (USD)", lambda r: r.get("cost_usd", 0.0)),
    ("Wall time (seconds)", lambda r: r.get("wall_seconds", 0.0)),
    ("Tool calls", lambda r: r.get("tool_calls_total", 0)),
    ("Diff lines, code", lambda r: r.get("diff_lines_code", 0)),
    ("Diff lines, all", lambda r: r.get("diff_lines_all", 0)),
    ("Lines the agent wrote", lambda r: r.get("agent_lines_written", 0)),
]  # fmt: skip


def parse_data_args(values: list[str] | None) -> list[tuple[str, Path]]:
    """``LABEL=PATH`` pairs; a single bare path has the label ``""`` (the single-set report)."""
    if not values:
        return [("", records.DATA_FILE)]
    parsed: list[tuple[str, Path]] = []
    for value in values:
        label, sep, path = value.partition("=")
        parsed.append((label, Path(path)) if sep and label else ("", Path(value)))
    labels = [label for label, _ in parsed]
    if len(parsed) > 1 and "" in labels:
        raise SystemExit("with several --data, every one needs a label: --data LABEL=PATH")
    if len(set(labels)) != len(labels):
        raise SystemExit("--data labels must be different from each other")
    return parsed


def column_rows(sets: list[DataSet]) -> list[tuple[str, list[Row]]]:
    """The columns: plain pooled over every set, then one Karni column per label, in order."""
    columns: list[tuple[str, list[Row]]] = []
    plain = [r for _, rows in sets for r in rows if r.get("condition") == "plain"]
    if plain:
        columns.append(("plain", plain))
    for label, rows in sets:
        karni = [r for r in rows if r.get("condition") == "karni"]
        if karni:
            columns.append((f"karni {label}", karni))
    return columns


def short_columns(sets: list[DataSet], n: int, tasks: tuple[str, ...] = TASKS) -> list[str]:
    """The task and column cells with fewer completed runs than ``n``, as text.

    A column is plain (pooled over the sets) or one set's Karni rows. A set with no Karni rows
    at all (a set holding only the plain runs) has no Karni column.
    """
    columns = dict(column_rows([(label, split(rows)[0]) for label, rows in sets]))
    wanted = ["plain"] + [
        f"karni {label}" for label, rows in sets if any(r.get("condition") == "karni" for r in rows)
    ]
    out = []
    for name in wanted:
        counts = {t: 0 for t in tasks}
        for row in columns.get(name, []):
            if row.get("task") in counts:
                counts[str(row["task"])] += 1
        out += [
            f"{task} {name}: {counts[task]} of {n} completed runs"
            for task in tasks
            if counts[task] < n
        ]
    return out


def range_text(values: list[float]) -> str:
    s = stats.spread(values)
    if s is None:
        return "-"
    return f"{number(s.median)} ({number(s.minimum)} to {number(s.maximum)})"


def passed_all(row: Row) -> bool:
    return row.get("acceptance_total", 0) > 0 and row.get("acceptance_passed", 0) == row.get(
        "acceptance_total"
    )


def figure_rows(group: list[Row]) -> list[tuple[str, str]]:
    """(label, text) for one task and column: counts, tests, build, then the spread figures."""
    ok = sum(1 for r in group if r.get("success"))
    full = sum(1 for r in group if passed_all(r))
    builds = sum(1 for r in group if r.get("build_ok"))
    passed = stats.spread([r.get("acceptance_passed", 0) for r in group])
    total = max((r.get("acceptance_total", 0) for r in group), default=0)
    out = [
        ("Runs completed", str(len(group))),
        ("Runs that succeeded", f"{ok} of {len(group)}"),
        (
            "Acceptance tests passed (median of total)",
            f"{number(passed.median)} of {total}" if passed else "-",
        ),
        ("Runs that passed every test", f"{full} of {len(group)} ({full / len(group):.0%})"),
        ("Frontend builds", f"{builds} of {len(group)}"),
    ]
    return out + [(name, range_text([read(r) for r in group])) for name, read in COLUMN_FIGURES]


def total_rows(per_task: list[list[Row]]) -> list[tuple[str, str]]:
    """The same rows across tasks: counts add up, a figure is the sum of the per-task medians
    with the sum of the minimums to the sum of the maximums."""
    flat = [r for group in per_task for r in group]
    if not flat:
        return []
    wins = sum(1 for r in flat if r.get("success"))
    out = [("Runs completed", str(len(flat))), ("Runs that succeeded", f"{wins} of {len(flat)}")]
    passed = [stats.spread([r.get("acceptance_passed", 0) for r in g]) for g in per_task if g]
    totals = [max(r.get("acceptance_total", 0) for r in g) for g in per_task if g]
    out.append((
        "Acceptance tests passed (sum of task medians, of the total)",
        f"{number(sum(s.median for s in passed if s))} of {sum(totals)}",
    ))  # fmt: skip
    full = sum(1 for r in flat if passed_all(r))
    out.append(("Runs that passed every test", f"{full} of {len(flat)} ({full / len(flat):.0%})"))
    out.append(("Frontend builds", f"{sum(1 for r in flat if r.get('build_ok'))} of {len(flat)}"))
    for name, read in COLUMN_FIGURES:
        spreads = [s for g in per_task if g and (s := stats.spread([read(r) for r in g]))]
        out.append((
            name,
            f"{number(sum(s.median for s in spreads))} "
            f"({number(sum(s.minimum for s in spreads))} to "
            f"{number(sum(s.maximum for s in spreads))})",
        ))  # fmt: skip
    return out


def span(rows: list[Row]) -> str:
    days = sorted(str(r["started_at"])[:10] for r in rows if r.get("started_at"))
    if not days:
        return "unknown"
    return days[0] if days[0] == days[-1] else f"{days[0]} to {days[-1]}"


def joined(rows: list[Row], key: str) -> str:
    values = sorted({str(r[key]) for r in rows if r.get(key)})
    return ", ".join(values) if values else "not recorded"


def describe_sets(sets: list[DataSet]) -> list[str]:
    """Per set: the Karni commit, the model, the agent CLI version and the dates of the runs."""
    out = ["### Data sets", ""]
    for label, all_rows in sets:
        rows = split(all_rows)[0]
        karni = [r for r in rows if r.get("condition") == "karni"]
        kinds = ", ".join(
            f"{sum(1 for r in rows if r.get('condition') == c)} {c}" for c in starts.CONDITIONS
        )
        out.append(
            f"- **{label}**: {kinds} completed runs, run {span(rows)}. "
            f"Karni commit: {joined(karni, 'karni_commit')}. Model: {joined(rows, 'model')}. "
            f"Agent CLI version: {joined(rows, 'agent_version')}."
        )
    out += [
        "",
        "The plain column pools the plain runs of every set that has them: the plain side does "
        "not depend on Karni's version, so it is measured once and shown beside each Karni "
        "column.",
    ]
    return out


def render_sets(sets: list[DataSet]) -> str:
    """The side-by-side markdown: plain, then one Karni column per labelled set."""
    done = [(label, split(rows)[0]) for label, rows in sets]
    interrupted = [r for _, rows in sets for r in split(rows)[1]]
    if not any(rows for _, rows in done):
        return PENDING + (f"\n\n{interrupted_note(interrupted)}" if interrupted else "")
    columns = column_rows(done)
    names = [name for name, _ in columns]
    count = sum(len(rows) for _, rows in done)
    out = [f"{count} completed runs in the data.", ""]
    if interrupted:
        out += [interrupted_note(interrupted), ""]
    out += describe_sets(sets) + [""]
    figures = "median (minimum to maximum) over the completed runs"
    for task in TASKS:
        per_column = [[r for r in rows if r.get("task") == task] for _, rows in columns]
        if not any(per_column):
            continue
        out += [f"### {task}", "", f"Figures are {figures}.", ""]
        out += ["| | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
        tables = [figure_rows(g) if g else [] for g in per_column]
        for i, (label, _) in enumerate(next(t for t in tables if t)):
            cells_ = [t[i][1] if t else "-" for t in tables]
            out.append(f"| {label} | " + " | ".join(cells_) + " |")
        out.append("")
    out += ["### All tasks", "", "Counts add up. A figure is the sum of the task medians, with the "
            "sum of the task minimums to the sum of the task maximums.", ""]  # fmt: skip
    out += ["| | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    tables = [
        total_rows([[r for r in rows if r.get("task") == t] for t in TASKS]) for _, rows in columns
    ]
    for i, (label, _) in enumerate(next(t for t in tables if t)):
        out.append(f"| {label} | " + " | ".join(t[i][1] if t else "-" for t in tables) + " |")
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
    parser.add_argument(
        "--data", action="append", metavar="[LABEL=]PATH",
        help="a data file; repeat as LABEL=PATH for plain, Karni before and Karni after",
    )  # fmt: skip
    parser.add_argument("--page", type=Path, default=PAGE)
    parser.add_argument("--n", type=int, default=5, help="completed runs wanted per cell (5)")
    parser.add_argument("--check", action="store_true", help="fail when the page is out of date")
    args = parser.parse_args(argv)
    page = args.page.read_text()
    given = parse_data_args(args.data)
    sets = [(label, records.load(path)) for label, path in given]
    single = len(sets) == 1 and not sets[0][0]
    any_done = any(split(rows)[0] for _, rows in sets)
    short = (
        short_cells(sets[0][1], args.n)
        if single and any_done
        else short_columns(sets, args.n)
        if any_done
        else []
    )
    if short:
        print(
            "No comparison written: these have fewer completed runs than asked for "
            "(interrupted runs do not count; run.py --resume):\n  " + "\n  ".join(short)
        )
        return 1
    updated = splice(page, render(sets[0][1]) if single else render_sets(sets))
    if args.check:
        if updated != page:
            print(f"{args.page} is out of date: run scripts/benchmarks/tokens/report.py")
            return 1
        return 0
    args.page.write_text(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
