---
description: "Launch audit tier 5: Karni's numbers measured on one machine (time to a running app, query counts, code per model)."
---

# Tier 5: Measurement audit

- Repo: `<REDACTED>`, branch `main`, commit `0873e51` (2026-10-18 22:34 +0530)
- Audited: 2026-10-18 / 2026-10-19 (local time)
- Machine: Apple M4, 10 cores, 24 GiB RAM (`sysctl -n machdep.cpu.brand_string hw.memsize hw.ncpu` → `Apple M4`, `25769803776`, `10`), macOS 26.6.2
- Tools: Python 3.12.12 (repo `.venv`), Node v20.20.1, npm 10.8.2, PostgreSQL 17.9 server on 127.0.0.1:5432, Redis on 127.0.0.1:6379 (db 9), no Docker
- Token counts: tiktoken 0.14.0, `cl100k_base`, in a throwaway venv
- Scratch: `<REDACTED>/audit/t5/`
- Raw outputs: `docs/audit/evidence/tier-5/` (file names in the Evidence column)
- Report only: no tracked file was modified. The audit DB `karni_audit_t5` was dropped and Redis db 9 flushed afterwards, and servers on 8551/8552 were stopped.

Every figure below was produced on this machine by the command shown. Nothing is estimated.

## Summary table

| # | Metric | README claim (source) | Measured | Command | Verdict |
|---|---|---|---|---|---|
| 1 | EventHub project code, total | **582** (`README.md` "What is measured", `examples/eventhub/README.md`, `docs/quickstart.md`) | **583** | `cd Karni && .venv/bin/python examples/eventhub/scripts/loc.py --pristine <scratch>/pristine/eventhub` (pristine = fresh `karni new "EventHub" -o <scratch>/pristine`, `KARNI_UI_SRC` set) | **PARTIAL**: off by 1, cause identified (row 1d) |
| 1a | models | 83 | 83 (`events/models.py`) | same | PASS |
| 1b | viewsets | 87 | 87 (`events/viewsets.py`) | same | PASS |
| 1c | pages | 291 | 291 (9 page/component files 273 + `routes.tsx` added 18) | same | PASS |
| 1d | other | 121 | 122 (apps 4, listeners 28, payments 9, seeds 65, factories 11, `settings.py` added 3, `urls.py` added 2) | same, detail in `loc-added-lines-detail.txt` | PARTIAL: commit `c1e710d` (2026-10-18, "admin path") changed the scaffold's `config/urls.py` to `path(settings.KARNI_ADMIN_PATH, …)` after EventHub was generated (2026-10-10), so EventHub's `path("admin/", …)` now counts as +1 added line against today's template |
| 1e | total without `--pristine` | (none, and the script itself says this "overstates") | 622 (pages 304, other 148) | `.venv/bin/python examples/eventhub/scripts/loc.py` | n/a, informational |
| 2 | Tokens consumed by an agent adding one entity end to end | README states **no figure** ("not measured yet") | not measurable here (needs an agent run with token accounting) | none | UNVERIFIED (consistent: README claims nothing) |
| 2a | `karni rules` size | **396 cl100k tokens for 32 rules** (`README.md`) | **396 tokens, 1,447 chars, 32 K-codes** when run outside a project or in the pristine scaffold. **667 tokens, 2,433 chars, 33 K-codes** when run inside `examples/eventhub` (adds `[module:payments]` guidance + conditional `K008`) | `karni rules` in `<scratch>/emptydir`, `<scratch>/pristine/eventhub`, `examples/eventhub`, tokens via tiktoken | PASS (claim reproduced exactly for the base rule set, and the README does not say it grows per module) |
| 2b | `karni context` size, EventHub | "the project in a few hundred tokens" (`README.md`) | **285 tokens, 1,388 chars, 9 lines** | `cd examples/eventhub && karni context` (project `.venv`) | PASS |
| 2c | `karni context` size, fresh scaffold | (no figure) | **173 tokens, 868 chars, 5 lines** | `cd <scratch>/timing/timing_app && karni context` (quickstart venv, PostgreSQL env) | n/a, measured |
| 2d | Generated agent adapter files | "adapters for seven tools" (no size claim) | **24 files, 25,025 chars, 6,749 tokens** total. Per file (tokens): `AGENTS.md` 222, `CLAUDE.md` 37, `CONVENTIONS.md` 260, `.cursor/rules/karni.mdc` 255, `.github/copilot-instructions.md` 222, `.windsurf/rules/karni.md` 229, `.clinerules/karni.md` 222, `.junie/AGENTS.md` 222, and 16 slash-command/prompt/workflow files 262–415 each | tiktoken over the pristine scaffold, `adapter-tokens.txt` | n/a, measured (24 files matches `karni new`'s own "24 agent adapter files") |
| 3 | Time from `karni new` to a running, seeded app | "Ten minutes from an empty directory to a running app" (`docs/quickstart.md`) | **29.01 s** from `karni new` to `/health/ready/` = 200 (DB, cache and 1 Celery worker all ok). Vite answered 200 after 1.87 s of step 6. Pre-step outside the window: venv 3.02 s + `pip install -e karni -e karni-cli psycopg[binary]` 22.33 s | `timing-run.sh` (`date +%s.%N` around every step), steps in `timing-steps.tsv` | PASS |
| 4a | `karni` suite | 1,150 tests | **1,156 passed, 2 skipped** (22.65 s) | `cd packages/karni && .venv/bin/python -m pytest -q` | PARTIAL: all green, README undercounts by 6 |
| 4b | `karni-cli` suite | 375 | **375 passed, 1 skipped** (37.41 s) | `cd packages/karni-cli && .venv/bin/python -m pytest -q` | PASS |
| 4c | `karni-payments` suite | 127 | **127 passed, 2 skipped** (1.30 s, stripe/razorpay SDK tests skipped, not installed) | `cd modules/karni-payments && .venv/bin/python -m pytest -q` | PASS |
| 4d | `@karni/ui` suite | 442 | **442 passed** (44 files, 16.33 s) | `cd packages/karni-ui && npx vitest run` | PASS |
| 4e | `@karni/payments-ui` suite | 14 | **14 passed** (3 files, 2.20 s) | `cd modules/karni-payments/ui && npx vitest run` | PASS |
| 4f | ruff clean | "ruff … clean" | clean: 4/4 targets "All checks passed!", 351 files already formatted | `PYTHON=.venv/bin/python make lint-py` → exit 0 | PASS |
| 4g | mypy clean | "mypy … clean" | **1 error**: `packages/karni/tests/test_links.py:75: error: Need type annotation for "prose" [var-annotated]` (karni-cli and karni-payments clean) | `PYTHON=.venv/bin/python make typecheck-py` → exit 2 | **FAIL** |
| 4h | ESLint clean | "ESLint … clean" | clean (eslint + prettier --check, both UI packages) | `make lint-ui` → exit 0 | PASS |
| 4i | tsc clean | "tsc clean" | clean (`tsc --noEmit`, both UI packages) | `make typecheck-ui` → exit 0 | PASS |
| 5a | EventHub backend tests | 14 | **14 passed** (2.73 s) | `cd examples/eventhub && .venv/bin/python -m pytest -q` | PASS |
| 5b | EventHub Playwright journeys | 3, "in CI on every push" | **3 `test(...)` in `frontend/e2e/*.spec.ts`**, not executed here | `grep -c 'test(' frontend/e2e/*.spec.ts` | PARTIAL: count verified, run not possible (`scripts/e2e.sh` binds 8431, taken on this machine, and Playwright browsers not provisioned) |

Verdict key: PASS = claim reproduced, PARTIAL = reproduced with a measurable deviation or only partly verifiable, FAIL = not reproduced, UNVERIFIED = cannot be measured on this machine.

## 1. EventHub lines of code

Command and output (`loc-pristine.txt`):

```
$ .venv/bin/python examples/eventhub/scripts/loc.py --pristine <scratch>/pristine/eventhub
models    events/models.py                          83
viewsets  events/viewsets.py                        87
pages     frontend/src/pages/login.tsx              14
pages     frontend/src/pages/events.tsx             42
pages     frontend/src/pages/event-detail.tsx       41
pages     frontend/src/pages/event-form.tsx         17
pages     frontend/src/pages/event-dashboard.tsx    36
pages     frontend/src/pages/bookings.tsx           23
pages     frontend/src/pages/booking-detail.tsx     39
pages     frontend/src/pages/booking-form.tsx       26
pages     frontend/src/components/TierList.tsx      35
other     events/apps.py                             4
other     events/listeners.py                       28
other     events/payments.py                         9
other     events/seeds.py                           65
other     events/factories.py                       11
other     config/settings.py (added)                 3
other     config/urls.py (added)                     2
pages     frontend/src/routes.tsx (added)           18
models 83  viewsets 87  pages 291  other 122  total 583
```

The pristine scaffold was produced by `karni new "EventHub" -o <scratch>/pristine` with `KARNI_UI_SRC=packages/karni-ui` (`karni-new-pristine.log`, slug `eventhub`, 24 adapter files). It printed a warning that `packages/karni-ui/dist` is older than its sources. `dist/` is gitignored and was not rebuilt (report-only).

**What `--pristine` subtracts.** Three scaffold files that EventHub edited (`config/settings.py`, `config/urls.py`, `frontend/src/routes.tsx`) are diffed against the fresh scaffold with `difflib.ndiff`, and only `+ ` lines count. Without `--pristine` they count whole: settings 13 instead of 3, urls 18 instead of 2, routes 31 instead of 18, i.e. 39 scaffold lines are subtracted (622 → 583). Lines EventHub removed from the scaffold are never counted.

**Why 583, not 582.** `loc-added-lines-detail.txt` lists the added lines. `config/urls.py` shows `+2 / -2`: today's template has `path(settings.KARNI_ADMIN_PATH, admin.site.urls)` (commit `c1e710d`, 2026-10-18 22:03, "Security baseline: … admin path"), while EventHub (generated 2026-10-10, commit `b5e3452`) still has `path("admin/", admin.site.urls)`, which the diff now reports as an added line. The other 582 lines match the README's breakdown exactly. The figure is therefore stale by one line because the scaffold moved under it, not because EventHub grew.

## 2. Agent surface

Tokens consumed by an agent adding an entity end to end: **not measurable in this audit** (requires driving an AI agent with token accounting). The README explicitly states no figure for this, so there is no claim to fail.

`karni rules` (`karni-rules-tokens.txt`):

```
karni-rules-emptydir.txt           chars= 1447 cl100k= 396 lines= 38 K-codes=32
karni-rules-pristine-scaffold.txt  chars= 1447 cl100k= 396 lines= 38 K-codes=32
karni-rules-examples-eventhub.txt  chars= 2433 cl100k= 667 lines= 54 K-codes=33
```

The README's 396 / 32 is exact for the base rule set (also what `packages/karni-cli/tests/test_rules.py::test_token_budget` checks, with a `< 400` budget, from an empty directory). Inside EventHub the output gains the `[module:payments]` section (15 lines) and `K008 Before editing a file: karni context --with-history FILE` (a conditional rule: the repo root has an untracked `.chronicle/` history store), giving 667 tokens / 33 rules. The README does not say the figure is per-project, so an agent working in a project with a module reads more than 396.

`karni context` (`context-tokens.txt`): EventHub 285 tokens / 1,388 chars (9 lines: APPS, MODELS, VIEWSETS, ROLES, COMPONENTS, HOOKS, PAGES, MODULES, BASES), fresh scaffold 173 tokens / 868 chars. Both inside "a few hundred tokens".

Adapter files: `adapter-tokens.txt` has the 24-row table, total 6,749 cl100k tokens. `CLAUDE.md` is a 37-token pointer. The eight tool-facing rule files are 222–260 tokens each, and the 16 slash-command/prompt/workflow files are 262–415 tokens each.

## 3. `karni new` to a running, seeded app

Script `timing-run.sh`, per-step log `timing-steps.tsv`, console `timing-run.out`. Environment: quickstart-style host venv active (`VIRTUAL_ENV`), `KARNI_UI_SRC=packages/karni-ui`, `DATABASE_URL=postgres://localhost/karni_audit_t5`, `REDIS_URL=redis://127.0.0.1:6379/9`, `KARNI_FRONTEND_URL=http://127.0.0.1:8552`, `KARNI_API_PROXY=http://127.0.0.1:8551`. The `.env` came from `.env.example` plus the quickstart's `MEDIA_ROOT`/`STATIC_ROOT` lines.

| Step | Command | Wall time |
|---|---|---|
| pre (outside window) | `python -m venv qsvenv` | 3.02 s |
| pre (outside window) | `pip install -e packages/karni -e packages/karni-cli 'psycopg[binary]'` | 22.33 s |
| pre (outside window) | `createdb karni_audit_t5` | 0.27 s |
| 1 | `karni new timing_app -o <scratch>/timing` | 2.02 s |
| 2 | `cp .env.example .env` + 2 lines | 0.01 s |
| 3 | `cd frontend && npm install` (327 packages added, 328 audited) | 14.48 s |
| 4 | `karni migrate` (PostgreSQL 17, 3 roles, 84 permissions synced) | 6.18 s |
| 5 | `karni seed` (3 users, demo login printed) | 1.69 s |
| 6 | start `karni serve --local --port 8551`, `karni worker`, `npm run dev -- --port 8552`, Vite 200 | 1.87 s |
| 6 | … `/health/ready/` first 200 (`{"status":"ok", database ok, cache ok, "1 worker(s) replied"}`) | 4.56 s |
| **Total** | **`karni new` → `/health/ready/` 200** | **29.01 s** |

Including the venv pre-step the empty-directory-to-running figure is ≈ 54.6 s, against the quickstart's "ten minutes". Deviations from the quickstart: PostgreSQL instead of SQLite (as instructed), and the Celery worker was started because the default readiness check pings workers (`karni/health/checks.py::check_celery`), exactly as `examples/eventhub/scripts/e2e.sh` does.

npm cache: `~/.npm/_cacache` was 13 GB before the run (warm), and `npm install` resolved 327 packages in 14 s. Whether every tarball was served from the cache is not determinable from the install log, and a cold-cache run was not performed, so the 14.48 s is a warm-cache figure.

## 4. Karni's own suites

All five suites pass, with counts in the table. The README's `karni` figure (1,150) is 6 below the 1,156 that pass today (plus 2 environment skips: 2FA apps not installed, PostgreSQL search provider), i.e. the README is stale on the low side. `ruff`, ESLint/Prettier and `tsc` are clean. `mypy` is not: one `var-annotated` error in `packages/karni/tests/test_links.py:75` (file added in the HEAD commit `0873e51`). The Makefile defaults to `PYTHON=python3`, which on this machine is a Python 3.14 without ruff/mypy. The first attempt (`lint-typecheck-default-python3-FAILED-ATTEMPT.txt`) failed for that reason, and the figures above come from `PYTHON=.venv/bin/python make …`.

## Not measurable here

- Agent token consumption for adding an entity (item 2): needs an agent run with token accounting. UNVERIFIED, and the README claims no figure.
- The 3 Playwright journeys (item 5b): counted, not run. `scripts/e2e.sh` binds `127.0.0.1:8431`, which another process owns on this machine and which this audit may not touch. Playwright browsers are not provisioned.
- Cold-cache `npm install` time: not run.
- The quickstart's exact commands were not replayed verbatim (`pip install karni karni-cli` from PyPI is impossible while the packages are unpublished, so the checkout path from `docs/quickstart.md` was used, as CI does).

## Observations outside the numeric claims (not fixed)

- `karni new` warns that `packages/karni-ui/dist` is older than its sources, and the scaffold's `file:` install ships that stale `dist/`.
- `karni context` in `examples/eventhub` reports `ROLES: staff![*=all] user[*=own] customer[*=own]`, while the EventHub README describes the roles as anonymous / attendee / organizer / staff. It is not a measurement claim and is noted for whoever audits correctness.
- Suite durations in the table were measured with the three pytest suites and the payments-ui vitest run executing concurrently, and the `@karni/ui` vitest run executed alone.
