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

The rebuild found 14 friction points. The three high-severity ones were fixed
in Karni the same day, and the example was moved onto the fixes, so this page
reports two states of the rebuild: **as built** on Karni 0.2.0, and **after
the fixes**.

## The result

| Category | Before (Social Stats) | As built (Karni 0.2.0) | After the fixes |
|---|---:|---:|---:|
| Models | 108 | 65 | 70 |
| Serializers | 70 | 0 | 0 |
| Views / viewsets | 423 | 140 | 140 |
| Pipeline services | (inside the views) | 93 | 93 |
| Module-specific permission code | 0 (shared mixin) | 12 | 0 |
| URLs | 2 | 0 | 0 |
| Admin | 0 (no admin for leads) | 0 (4 generated screens) | 0 (4 generated screens) |
| Settings | 0 | 5 | 5 |
| Frontend pages | 1,715 | 152 | 152 |
| Frontend components, hooks, API client | 23 | 294 | 294 |
| Frontend routes and navigation | 5 | 26 | 26 |
| Tests dedicated to the module | 0 | 226 | 216 |
| **Total** | **2,346** | **1,013** | **996** |
| Total without tests | 2,346 | 787 | 780 |

Lines are non-blank, non-comment lines, counted after formatting both sides
alike: `ruff format` (88 columns) for Python and Prettier (80 columns) for
JavaScript and TypeScript, both with their defaults. Social Stats is styled by
hand and the rebuild is not, so counting each as written compares formatting
habits, not code. Migrations, lockfiles, generated API types and the
untouched `karni new` scaffold are left out; a scaffold file the rebuild
edited counts only the lines it added. Reproduce with:

```sh
cd examples/social-leads
PRETTIER=<path to prettier> python scripts/measure.py --normalise \
    --before <social-stats checkout at 6e9308b> \
    --pristine <a fresh `karni new "Social Leads"`>
```

The backend went from 603 lines to 308; the frontend from 1,743 to 472.
"After the fixes" moves workspace membership from a custom scope onto
`own` with an owner path (the scope file goes; three `owner_field` lines
join the models) and replaces hand-written isolation tests with Karni's
generated ones. Both rebuild totals *include* tests the original never had.

**Correction, 2026-10-20.** The first version of this page reported
1,311 → 697. It counted both code bases as written: Social Stats' long,
hand-aligned lines and the rebuild's then-unformatted Python. Both
understated their side, and not by the same amount. The table above
replaces those figures.

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
  (for `Client`) and `Contact` (for `WhatsAppContact`), 12 lines as built and
  16 after the fixes, outside the totals.
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
  both. After the fixes it is `own` with an owner path through the
  membership many-to-many (`owner_field = "workspace__members"`), and Karni's
  `assert_crud` and `assert_isolated` prove it for all four models; four
  hand-written tests cover what they do not reach: custom actions
  (`convert` on another workspace's lead is a 404), a member of two
  workspaces, staff, and creating a lead in someone else's workspace
  (refused).

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
| List, detail and form screens | 1,715 lines of pages | 152 lines composing `ResourceTable`, `ResourceDetail`, `ResourceForm` |
| CRUD and isolation tests | none | after the fixes, generated: `assert_crud` + `assert_isolated` per model |

As built on 0.2.0, tests did **not** come for free: the custom scope the
rebuild used could not be driven by Karni's generated tests, so every test
was written by hand ([friction 3](#the-friction)). After the fixes the
generated tests cover CRUD and isolation for all four models.

## Adding one more entity afterwards

A `FollowUp` (lead, due date, done, note) was added to a copy of the finished
rebuild the way an agent would, once on each state. Machine time, measured
with `/usr/bin/time -p`:

| Step | As built | After the fixes |
|---|---:|---:|
| `karni context` | 0.92 s | 0.95 s |
| `karni rules` | 0.17 s | 0.19 s |
| `karni make model FollowUp lead:fk:Lead due_at:datetime done:bool "note:text?" -a --access granted --app crm` | 0.20 s | 0.19 s |
| `karni make migration --app crm` | 1.04 s | 1.06 s |
| `karni migrate` | 1.13 s | 1.15 s |
| `karni test crm/tests/test_follow_up.py` | 3.11 s | 3.41 s |
| **Total** | **6.57 s** | **6.95 s** |

| | As built | After the fixes |
|---|---|---|
| Generated (`git diff --stat`) | 7 files, 92 lines | 7 files, 95 lines |
| The generated test | CRUD as `staff`, no isolation, no word about it | CRUD and isolation as `member` |
| By hand | 1 line in the custom scope + a 10-line isolation test | 2 lines: `class Karni: owner_field = "lead__workspace__members"` |
| What a member got before the hand edit | **500** on `/api/follow-ups/`, generated test green | only the follow-ups they created (the `created_by` default owner), generated tests green — the hand line is what makes it the workspace's |

Tokens of the text an agent types and reads for that entity, counted with
tiktoken — this is the size of the inputs and outputs, **not** the tokens an
agent consumed:

| Text (cl100k / o200k) | As built | After the fixes |
|---|---:|---:|
| `karni context` output | 266 / 275 | 264 / 273 |
| `karni rules` output | 402 / 395 | 402 / 395 |
| The command | 33 / 31 | 32 / 30 |
| Generator and migration output | 185 / 178 | 189 / 182 |
| Test run output | 16 / 16 | 16 / 16 |
| Hand-written code | 179 / 176 | 15 / 15 |
| **Sum** | **1,081 / 1,071** | **918 / 911** |
| The generated lines, if the agent reads them back | 738 / 753 | 772 / 788 |

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
- **Line counts follow formatting.** The same files count very differently
  at different widths: the rebuild's hand-written lead tests are 128 lines as
  written and 226 after `ruff format` at 88 columns. The table formats both
  sides alike, but any line count is a proxy.
- One machine, SQLite. As built: Karni 0.2.0 at `8333c9c`, Python 3.12
  (on Python 3.14 its admin crashed, [friction 14](#the-friction)). After the
  fixes: Karni `main` on Django 5.2 LTS, Python 3.12, with the admin also
  checked on Python 3.14.4.

## The friction

The full log, with what was wanted and what was done instead, is
[`examples/social-leads/FRICTION.md`](https://github.com/cbsshekhawat18-lab/karni/blob/main/examples/social-leads/FRICTION.md).
In order of severity:

| # | Finding | Severity | Status |
|---|---|---|---|
| 2 | A custom scope names every model's path; a new model 500s for members and `karni check` says ok | high | **fixed**: `karni check` resolves every scope path ([`E214`](errors.md#e214)) |
| 3 | Generated tests cannot drive a custom scope, and the generator drops the isolation test without a word | high | **fixed**: membership as `own` with an owner path is driven by `assert_isolated` (a factory bug fixed); the generator now says why it leaves isolation out |
| 14 | Python 3.14 installs, then every admin page 500s (Django 5.1) | high | **fixed**: Django 5.2 LTS, Python 3.14 in CI |
| 1 | No scope for membership through a many-to-many | medium | **was possible, now documented**: `own` with `owner_field = "workspace__members"` ([accounts](accounts.md#membership-workspaces-teams-client-accounts)) |
| 6 | No filter for "this JSON list contains X" | medium | open |
| 7 | No way to attach a note to a change-history entry, so the timeline is project code | medium | open |
| 8 | Export, import and filter names differ from the original; unknown filters are ignored | medium | open |
| 10 | No documented way to refresh a resource after a custom action in the UI | medium | open |
| 11 | No board component | medium | open |
| 13 | A foreign key to the user model renders as "[object Object]" | medium | open |
| 4 | The field DSL has no defaults and no list-shaped JSON | low | open |
| 5 | No reverse name in the DSL | low | open |
| 9 | UUIDs are not JSON-serialisable inside JSON fields | low | open |
| 12 | No "only these columns" on `ResourceTable` | low | open |

And what Karni caught: `karni check` failed the build on a bulk
`.update()` of an audited model in a test, and the row scope reached the
custom actions, the export, the import and the admin without any code.
