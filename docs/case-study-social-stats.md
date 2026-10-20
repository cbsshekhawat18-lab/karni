---
description: One module of a real Django + React product, Social Stats' leads/CRM, rebuilt on Karni with the same data model, endpoints, screens and permission rule — measured before and after, with the friction it found.
---

# Case study: Social Stats' leads module, rebuilt on Karni

[Social Stats](https://github.com/cbsshekhawat18-lab/social-stats-social-media-manager)
is an open-source social media management product built by hand on Django
4.2, DRF and React 18. Its leads/CRM module was rebuilt as a fresh Karni
project, [`examples/social-leads`](https://github.com/cbsshekhawat18-lab/karni/tree/main/examples/social-leads),
using only Karni's documented public surface. Every number below comes from a
command in that directory; where something could not be measured, this page
says so instead of estimating.

## The result

| Category | Before (Social Stats) | After (Karni) |
|---|---:|---:|
| Models | 82 | 63 |
| Serializers | 35 | 0 |
| Views / viewsets | 332 | 114 |
| Pipeline services | (inside the views) | 66 |
| Module-specific permission code | 0 (shared mixin) | 13 |
| URLs | 2 | 0 |
| Admin | 0 (no admin for leads) | 0 (4 generated screens) |
| Settings | 0 | 5 |
| Frontend pages | 835 | 99 |
| Frontend components, hooks, API client | 20 | 202 |
| Frontend routes and navigation | 5 | 7 |
| Tests dedicated to the module | 0 | 128 |
| **Total** | **1,311** | **697** |
| Total without tests | 1,311 | 569 |

Lines are non-blank, non-comment lines. Migrations, lockfiles, generated API
types and the untouched `karni new` scaffold are left out. A scaffold file the
rebuild edited counts only the lines it added. Reproduce with:

```sh
cd examples/social-leads
python scripts/measure.py --before <social-stats checkout at 6e9308b> \
    --pristine <a fresh `karni new "Social Leads"`>
```

The backend went from 451 lines to 261; the frontend from 860 to 308. The
"after" total *includes* 128 lines of tests the original never had.

## Why this module

The leads module has clear boundaries: two models (`Lead`, `LeadActivity`),
one viewset, two screens. It has real CRUD and a pipeline (assign, change
status, convert, score, log activity, bulk-assign, import, export). It has a
permission rule that matters: a lead belongs to a client workspace, and only
people attached to that workspace may see or touch it. It is built the way
the rest of Social Stats is built: a hand-written `ModelViewSet` with a
tenant mixin, hand-written serializers, and pages with inline components.

The "before" boundary is what the module itself contains: the two model
classes, their three serializers, `lead_views.py`, the router line, the two
lead pages, the `leadAPI` client block, two routes and one sidebar entry.
Shared code it leans on — `TenantScopedMixin`, the axios instance, the
design tokens — is counted on neither side. Social Stats has no admin screen
for leads and no test file dedicated to them; 12 test functions in 5 files
touch leads as a side effect of testing the event bus, notifications,
dashboard counts and the AI tools.

## What the rebuild covers

- **Data model.** `Lead` and `LeadActivity` with the same fields, choices and
  defaults. Two stand-ins for models the original has elsewhere: `Workspace`
  (for `Client`) and `Contact` (for `WhatsAppContact`), 12 lines, outside the
  totals.
- **Endpoints.** CRUD plus `assign`, `status`, `activity`, `convert`,
  `timeline`, `bulk-assign` and `score-with-ai`, at the original paths.
  Export, import and three filter names differ; see the table under
  [caveats](#honest-caveats).
- **Screens.** The list as a table (the original's columns, search, status
  filter, bulk status change, import, CSV/XLSX export) and as a board with
  drag-and-drop between statuses; the detail with status picker, Score,
  Convert and the activity timeline with "add a note"; a form. Driven in
  headless Chromium against the running app: login, table, bulk status,
  board, drag to Converted, add a note, score, convert — every step passed,
  with no console errors and no server errors.
- **Permission rule.** Staff see every workspace; a member sees and changes
  only the leads of workspaces they belong to; someone in two workspaces sees
  both. Proven by tests on every surface: list, retrieve, update, custom
  actions (`convert` on another workspace's lead is a 404), search, export,
  and creating a lead in a workspace you do not belong to (refused).

## What Karni gave that the original wrote by hand

Each item was checked in the running rebuild, not read off the docs.

| Piece | Social Stats | Karni rebuild |
|---|---|---|
| Serializers (list and detail) | 35 lines | generated |
| URL routing | 2 lines | auto-router |
| Filters and search (`get_queryset` parsing 10 query parameters) | in the viewset | derived from the model; `search_fields` is one line |
| CSV export | `export_csv` and a streaming writer | `/export/?format=csv` and `xlsx`, row scope applied |
| CSV import | one-step `import_csv` + a modal | upload, mandatory dry-run preview, commit; `<ResourceImport/>` |
| Row scope on custom actions, export, import | the mixin, per viewset | applied by the access declaration everywhere |
| Admin | none for leads | list and change screens for all four models; history and import (checked on `Lead`) |
| Field-level change history | none (the pipeline actions write `LeadActivity` rows; the general action log is not called for leads) | every `Lead` field change with its author (`Karni.audit = True`) |
| OpenAPI schema and docs | none for this module | generated, with a snapshot test |
| List, detail and form screens | 835 lines of pages | 99 lines composing `ResourceTable`, `ResourceDetail`, `ResourceForm` |

Tests did **not** come for free here: Karni's generated tests cannot drive a
custom scope, so the module's 128 lines of tests were written by hand
([friction 3](#the-friction)).

## Adding one more entity afterwards

A `FollowUp` (lead, due date, done, note) was added to a copy of the finished
rebuild, the way an agent would. Machine time, measured with
`/usr/bin/time -p`:

| Step | Seconds |
|---|---:|
| `karni context` | 0.92 |
| `karni rules` | 0.17 |
| `karni make model FollowUp lead:fk:Lead due_at:datetime done:bool "note:text?" -a --access granted --app crm` | 0.20 |
| `karni make migration --app crm` | 1.04 |
| `karni migrate` | 1.13 |
| `karni test crm/tests/test_follow_up.py` | 3.11 |

The generator wrote 7 files, 92 added lines (`git diff --stat`): the model,
the viewset, three pages, three routes and a test. By hand: 1 changed line in
the workspace scope and a 10-line isolation test — without them every member got a 500 on the new
endpoint while the generated test passed ([friction 2 and 3](#the-friction)).

Tokens of the text an agent types and reads for that entity, counted with
tiktoken — this is the size of the inputs and outputs, **not** the tokens an
agent consumed:

| Text | cl100k | o200k |
|---|---:|---:|
| `karni context` output | 266 | 275 |
| `karni rules` output | 402 | 395 |
| The command | 33 | 31 |
| Generator and migration output | 185 | 178 |
| Test run output | 16 | 16 |
| Hand-written code (scope line + test) | 179 | 176 |
| **Sum** | **1,081** | **1,071** |
| The 92 generated lines, if the agent reads them back | 738 | 753 |

## Not measured

- **Tokens consumed doing the rebuild.** The rebuild ran inside one long
  agent session that also fixed Karni's CI and polished another repository;
  the session's counters cover all of it and there is no per-task split.
  To measure it, run the rebuild alone in a fresh Claude Code session and
  read `/cost` at the end.
- **Active build time.** The rebuild's files are timestamped from 02:12 to
  09:31 IST on 2026-10-20, but that span includes hours of unrelated work and
  idle time. It is not a build-time figure, and none is claimed.

## Honest caveats

- **A rebuild is always easier than the original.** The problem was already
  solved: the data model, the endpoints, the screens and the edge cases were
  read off working code. Social Stats' authors had to discover them. The line
  counts compare finished code, not effort.
- **The tenancy rule is simpler.** Social Stats resolves a user's clients
  through four paths (a superadmin's `?client_id=`, a staff member's assigned
  clients, an end user's own client, an agency's active client relations).
  The rebuild has two: staff see everything, members see their workspaces.
  The superadmin's per-request client switch is not reproduced.
- **Four foreign keys to other modules were dropped:** the source bot flow,
  bot conversation, post and WhatsApp campaign. So were the model's four
  database indexes. The detail page's Conversation tab (bot steps) is gone
  with them; `timeline` answers `bot_steps: []`.
- **AI scoring is a heuristic.** The original asks Anthropic's Claude for a
  0–100 score; the rebuild keeps the endpoint and its contract with a
  deterministic rule (budget, interest, email, spam), so it runs without an
  API key.
- **The API is not identical:**

  | Original | Rebuild |
  |---|---|
  | `GET /api/leads/export.csv/` | `GET /api/leads/export/?format=csv` |
  | `POST /api/leads/import_csv/` (one step) | `/api/leads/import/` (upload, preview, commit) |
  | `?q=`, `?min_score=`, `?from=`, `?to=` | `?search=`, `?quality_score__gte=`, `?created_at__gte=`, `?created_at__lte=` |
  | integer ids | UUIDs |

  An old `?q=` is ignored rather than refused, so it returns the whole list.
- **The screens match in function, not pixels.** Karni's components and
  tokens replace the original's inline styles; status and score colours are
  not reproduced.
- One machine, Python 3.12, SQLite, Karni 0.2.0 at `8333c9c`. On Python
  3.14 the admin crashes ([friction 14](#the-friction)).

## The friction

The full log, with what was wanted and what was done instead, is
[`examples/social-leads/FRICTION.md`](https://github.com/cbsshekhawat18-lab/karni/blob/main/examples/social-leads/FRICTION.md).
In order of severity:

| # | Finding | Severity |
|---|---|---|
| 2 | A custom scope names every model's path; a new model 500s for members and `karni check` says ok | high |
| 3 | Generated tests cannot drive a custom scope, and the generator drops the isolation test without a word | high |
| 14 | Python 3.14 installs, then every admin page 500s (Django 5.1) | high |
| 1 | No scope for membership through a many-to-many (`related:` takes one value) | medium |
| 6 | No filter for "this JSON list contains X" | medium |
| 7 | No way to attach a note to a change-history entry, so the timeline is project code | medium |
| 8 | Export, import and filter names differ from the original; unknown filters are ignored | medium |
| 10 | No documented way to refresh a resource after a custom action in the UI | medium |
| 11 | No board component | medium |
| 13 | A foreign key to the user model renders as "[object Object]" | medium |
| 4 | The field DSL has no defaults and no list-shaped JSON | low |
| 5 | No reverse name in the DSL | low |
| 9 | UUIDs are not JSON-serialisable inside JSON fields | low |
| 12 | No "only these columns" on `ResourceTable` | low |

And what Karni caught: `karni check` failed the build on a bulk
`.update()` of an audited model in a test, and the row scope reached the
custom actions, the export, the import and the admin without any code.
