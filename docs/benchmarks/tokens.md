---
description: "The token benchmark: three apps built by a coding agent with and without Karni, with the method, the exact commands to repeat it, the limits and the raw data."
---

# Token benchmark: the same apps with and without Karni

!!! warning "Experimental"
    The benchmark harness is a script in the repository, not a public API. It may
    change in any release.

Karni's claim is that an AI coding agent writes less when the framework carries the
repeated parts. This page measures that claim on three small apps, and publishes the
method, the commands to repeat it, the limits and the raw data. The numbers come from
the runs and from nothing else.

## Results

<!-- bench:results:start -->

The runs are pending. No numbers are published yet.

<!-- bench:results:end -->

The raw data is one JSON line per run in
[`scripts/benchmarks/tokens/data/runs.jsonl`](https://github.com/cbsshekhawat18-lab/karni/blob/main/scripts/benchmarks/tokens/data/runs.jsonl).
The tables above are written from it by `report.py`. A failed run stays in the data and
counts as a failure. Its tokens are in the figures too.

A run the agent CLI did not finish is different: when a usage or rate limit, an overloaded or
other API error, or a kill cuts it short (an error result, a stream with no result line, or a
non-zero exit without one), the run says nothing about its condition. It is recorded with
`interrupted: true` and the reason, left out of every figure, and counted in a note under the
results. `run.py --resume` runs it again, and a usage or rate limit stops the batch at once and
prints the reset time when the message gives one. `report.py` writes no comparison while a task
and condition has fewer completed runs than `--n`. Hitting the time limit is not an
interruption: it counts as part of the result.

## The method

Three tasks, each one written prompt plus an API contract that both conditions must meet:

1. **Booking with payments.** Resources, time slots with a capacity, bookings owned by the
   member, a checkout that creates a payment through a test provider, and staff who see
   every booking.
2. **A CRM with three roles and import.** Companies, contacts and deals in a pipeline. The
   roles are sales (own deals), manager (all deals) and admin. Contacts import from a CSV
   file.
3. **A shop with orders and refunds.** Products in categories, a cart, orders with a state
   (pending, paid, shipped, refunded), checkout and a refund through a test payment provider.

The prompt, the contract and the checks are in `scripts/benchmarks/tokens/tasks/<task>/`.
The contract names endpoints, fields, roles and status codes, and is written so that a plain
Django REST app and a Karni app can both meet it. A list may be a plain array or a paginated
object with `results`.

**Acceptance.** The checks are black-box HTTP tests (pytest and requests) against the running
app, plus `npm run build` in `frontend/`. The agent sees the contract and the checks and may run
them. The harness runs its own copy after the agent stops, and that run is what counts, never
the agent's claim.

**Two conditions, everything else equal.**

- **Plain.** An empty Django 5.2 and DRF project with a Vite, React and TypeScript frontend.
  Dependencies are installed, Karni is not.
- **Karni.** `karni new` from wheels built from the checkout under test, its generated
  AGENTS.md, the Karni MCP server in `.mcp.json`, and a prompt that starts with the new-app
  procedure (``Run `karni rules --procedure new-app` and follow every step for this
  request:``).

The agent CLI, the model, the task prompt and contract, the checks, the time limit, the tool
permissions, a fresh directory and a fresh PostgreSQL database per run are the same. No user settings, hooks,
plugins or memory are loaded (`--setting-sources project`, `--strict-mcp-config`,
`--no-session-persistence`, and a new path per run so auto-memory starts empty).

**The command of every run.** `<agent>` is the agent CLI (`--agent` or `KARNI_BENCH_AGENT`)
and `<model>` the model (`--model` or `KARNI_BENCH_MODEL`). The harness reads the stream-json
events the CLI prints.

```sh
<agent> -p "<prompt>" --output-format stream-json --verbose --model <model> \
  --setting-sources project --strict-mcp-config --mcp-config <the condition's MCP file> \
  --no-session-persistence --dangerously-skip-permissions
```

It runs inside a throwaway folder under `~/.cache/karni-dev/bench/`, with a limit of 60
minutes of wall time. `--dangerously-skip-permissions` is used only there, for both conditions.

**Decisions.** One model for both conditions, recorded with every run. There are 5 runs per task
and condition, 30 runs in all. Acceptance is the API tests plus the frontend build. The time
limit is 60 minutes per run. The runs alternate between the conditions, plain then Karni, so the
time of day touches both alike.

**Recorded per run.** Input, output, cache-read and cache-creation tokens, the reported cost,
tool calls by tool, wall time, the agent CLI's version, the lines the agent wrote itself (counted from its Write and
Edit tool inputs), the size of the project's git diff (lines added plus deleted, shown with and
without lockfiles, `node_modules`, migrations and build output), tests passed out of the total,
the frontend build, whether the time limit hit, and the exit status. The report gives the
success rate and, per figure, the median, minimum, maximum and interquartile range.

A run counts as a success when the agent ended by itself, every acceptance test passed and the
frontend built.

## Reproduce it

Everything is run from a Karni checkout with a virtualenv that has `karni`, `karni-cli`,
`psycopg`, `pytest` and `requests`, Node 20 or later, a test PostgreSQL and the agent CLI
signed in. Unset `VIRTUAL_ENV` first: the Karni commands prefer it over a project's own
virtualenv.

```sh
unset VIRTUAL_ENV
export KARNI_BENCH_AGENT=<the agent CLI> KARNI_BENCH_MODEL=<the model>
# once: the two starting projects (wheels from this checkout, dependencies, node_modules)
python scripts/benchmarks/tokens/run.py --build-starts

# the reference solutions: each task built with Karni, passing its own checks
python scripts/benchmarks/tokens/run.py --reference booking
python scripts/benchmarks/tokens/run.py --reference crm
python scripts/benchmarks/tokens/run.py --reference shop

# see the plan and the exact commands, nothing is started
python scripts/benchmarks/tokens/run.py --dry-run --show-prompt

# test the harness with a stand-in for the agent (no usage is spent)
python scripts/benchmarks/tokens/run.py --fake --n 1 --data /tmp/fake-runs.jsonl

# the 30 real runs (re-run the same command to continue where a stop left off)
python scripts/benchmarks/tokens/run.py --resume

# write the results into this page
python scripts/benchmarks/tokens/report.py
```

`--tasks`, `--conditions`, `--n`, `--agent`, `--model` and `--limit-minutes` narrow or change a
run.
The PostgreSQL is `127.0.0.1:55432` (user `postgres`) and each run uses a database named
`bm_<run id>` that is dropped afterwards. Servers listen on a free port between 8700 and 8799.

The reference solutions are in `scripts/benchmarks/tokens/reference/`. They prove that the
checks can be passed and are never shown to the agents under test.

## Limits

- One model. The result says nothing about other models.
- Small N: five runs per task and condition. Read the spread, not only the median.
- The tasks and contracts are written by Karni's author. Two of the three fit Karni's recipes
  closely.
- Agent runs are not deterministic. The same prompt gives different runs.
- The Karni condition includes agent rules written for agents. That is the point of Karni, and
  it is also part of the condition.
- Package install time is excluded for both conditions. Dependencies are installed before the
  agent starts.
- Lines written by the agent are counted from Write and Edit inputs only. Lines written through
  shell commands show up in the diff size, not in that count.
- The checks measure the contract, not the quality or the look of the app.
- The Karni condition may use a recipe the contract fits. The result describes tasks like these
  and not every project.
