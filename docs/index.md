---
description: "Karni is an open-source Django + React framework for building with AI coding agents. Your agent writes only your domain. The API, admin, permissions and React screens come from a package you upgrade, not code it rewrites in each project. One rule set covers every coding agent. The build fails when an agent hand-writes what Karni ships."
hide:
  - navigation
  - toc
---

<div class="karni-hero" markdown>

<div class="karni-eyebrow">Django + React framework · Apache-2.0</div>

# Karni

Karni is an open-source Django + React framework for building with AI coding
agents. Your agent writes only your domain. The API, admin, permissions and
React screens come from a package you upgrade, not code it rewrites in each
project. One rule set covers every coding agent. The build fails when an
agent hand-writes what Karni ships.

[Quickstart](quickstart.md){ .md-button .md-button--primary }
[Recipes](recipes/index.md){ .md-button }
[GitHub](https://github.com/cbsshekhawat18-lab/karni){ .md-button }

</div>

## Why Karni exists

Every web project starts with the same work: sign-in, a user model, the
admin, permissions, CRUD endpoints, tables, forms, Docker and Celery. Coding
agents write that setup faster, but they write it again in every project, a
little different each time, and every copy has to be maintained.

Karni ships that code as versioned packages: `karni` (Python), `@karni/ui`
(React) and the `karni` command. You declare a model and who may access it,
and Karni gives you the REST API, the admin, role-based access, the React
screens, the tests and the demo data. The agent writes only your domain, and
`karni check` fails the build when it hand-writes what Karni ships. Karni
grew out of the 34 projects we built before it.

## Build an app from one line

1. **Create a project** with `karni new "Yoga Studio"` and open it in your coding agent.
2. **Describe the app in one line** after `/new-app`. AGENTS.md tells the agent what that asks for.
3. **The agent writes `karni.yaml`** from the closest [recipe](recipes/index.md), and asks you only the questions `karni plan --questions` lists.
4. **`karni build` makes the app**: modules, Karni's code, migrations, the demo data the spec asks for, TypeScript types, the tests and `karni check`.
5. **The agent writes only the domain logic that is left**, in the project's own files. It is done when `karni check` and `karni test` pass.

```text
/new-app a booking app for a yoga studio, with online payments
```

What the agent runs, from a real session:

```text
$ karni recipes list --match "a booking app for a yoga studio, with online payments"
booking   4  Booking: Resources with time slots that members book and pay for, never over capacity. (matched: booking)
shop      3  Online shop: Products in categories, a cart, orders and checkout with online payments. (matched: online, payment)

$ karni build
plan        22 changes, 0 risky: modules 1, features 1, roles 3, apps 1, entities 3, access 3, pages 3, migrations 1, seed 3, tests 3 (--verbose lists each)
modules     karni add payments
migrations  bookings/migrations/0001_initial.py
migrate     applied 84 on default
seed        Resource 4, Slot 30, Booking 60 (demo login demo@example.com / karni-password)
types       frontend/src/api/types.ts and hooks.ts
test        7 passed in 2.88s, tests/openapi.snapshot.json updated (the API changed: commit it)
check       ok
Built: the project matches karni.yaml.
```

On a developer laptop, `karni new --recipe shop` builds the shop from
scratch on SQLite in 14.1 seconds, its tests and `karni check` included and
the frontend install left out ([how fast is it](recipes/index.md#how-fast-is-it)).
[The /new-app flow](agents.md#agents-the-new-app-flow) has every step.
Every step is also a command you can run without an agent
([building without one](guide/without-ai.md)).

![A terminal runs karni new, karni make model, migrate, seed and serve. Then the browser shows the welcome page, the admin listing the seeded events, and the React app's events table and detail view.](assets/karni-demo.gif){ loading=lazy }

## Coding-agent benchmark

A coding agent built three small apps five times each on plain Django + React, on the Karni 0.5.0 candidate, and on Karni again after work on its agent flow: 45 runs with the same model and agent version, prompt and API contract, where the harness's own acceptance tests decide success.

<!-- bench:home:start -->
| Task | Plain Django + React | Karni 0.5.0 candidate | Karni after the agent-flow work |
|---|---|---|---|
| Booking with payments | $0.19, 61.76 s, 5 of 5 passed, 5 tool calls | $0.45, 208 s, 3 of 5 passed, 26 tool calls | $0.33, 187 s, 5 of 5 passed, 20 tool calls |
| A CRM with three roles and import | $0.21, 70.51 s, 5 of 5 passed, 6 tool calls | $0.56, 278 s, 5 of 5 passed, 31 tool calls | $0.40, 236 s, 5 of 5 passed, 22 tool calls |
| A shop with orders and refunds | $0.23, 72.21 s, 5 of 5 passed, 7 tool calls | $0.62, 238 s, 4 of 5 passed, 29 tool calls | $0.44, 255 s, 4 of 5 passed, 24 tool calls |
| All three tasks | $0.63, 204 s, 15 of 15 passed, 18 tool calls | $1.63, 724 s, 12 of 15 passed, 86 tool calls | $1.17, 678 s, 14 of 15 passed, 66 tool calls |

Each cell: median cost in US dollars, median wall time, runs that passed every acceptance test, and median tool calls. In the last row the runs add up and the other figures are the sums of the task medians, as the [benchmark report](benchmarks/tokens.md) gives them.
<!-- bench:home:end -->

- **Plain Django + React was cheaper and faster on these three small apps.** Karni after the agent-flow work cost about 1.8 to 1.9 times as much per app (median) and took about 3 to 3.5 times as long.
- **The agent-flow work** cut the median cost by 27 to 30 percent and the context the agent read again by 30 to 43 percent, and raised the runs that passed every test from 12 of 15 to 14 of 15.
- **With Karni the agent wrote fewer lines of its own** (median 256 to 431 per app, against 438 to 554), and each Karni project ended with far more code in it (median about 11,500 to 20,000 lines, most of it generated by Karni, against about 440 to 570).
- **What these tasks measure** is the time and cost to meet a small API contract, not everything a finished app contains.

The [benchmark report](benchmarks/tokens.md) has every figure with its range, the method, the limits and the raw data.

## What you get

<div class="grid cards" markdown>

-   **Start fast**

    ---

    [`karni new`](quickstart.md), six [recipes](recipes/index.md), the
    [app spec](app-spec.md) with `karni plan` and `karni build`,
    [demo data](seeding.md) and [real content](content-loading.md), and a
    [public website](public-site.md) next to the app.

-   **Data and access**

    ---

    [`BaseModel`](models.md), [typed fields](fields.md),
    [states and capacity](lifecycle-and-capacity.md), [`BaseViewSet`](api.md)
    with a required `access` rule, [accounts and roles](accounts.md) and
    [change history](change-history.md).

-   **Large apps**

    ---

    [Aggregations](aggregations.md), [search across models](global-search.md),
    [navigation from data](navigation.md),
    [trees and taxonomies](models.md#tree-models),
    [import and export](import-export.md) and
    [tooling for 100 models or more](large-projects.md).

-   **Admin**

    ---

    [An admin for every model](admin.md) with no `admin.py`: derived columns,
    filters, pagination, bulk edit, [row scope](admin.md#row-scope) and a
    [permission matrix](admin.md#permission-matrix).

-   **UI**

    ---

    [`ResourceTable`, `ResourceForm`, `ResourceDetail`](ui.md) from the
    OpenAPI schema, sign-in pages, the app shell, and
    [your design system's look](theming.md).

-   **Modules**

    ---

    Payments, approvals, impersonation, a public site,
    [charts](charts.md), [PDF reports](reports.md),
    [extraction](ai-extraction.md) and [protected files](storage.md), each
    added with [one command](modules.md).

-   **Coding agents**

    ---

    [AGENTS.md](agents.md#agentsmd) from one rule set, `karni context`, the
    [MCP server](agents.md#mcp), [`karni check`](enforcement.md) and the
    [debugging commands](debugging/why.md).

-   **Production**

    ---

    [A production Docker Compose stack](deploy.md) with Caddy and TLS,
    [safe defaults](security.md), [one-line tests](testing.md) and
    [`karni upgrade`](stability.md).

</div>

[Every feature, with its status](features.md){ .md-button }

## Recipes and modules

| Recipe | What it gives | One command |
|---|---|---|
| [`shop`](recipes/shop.md) | Products in categories, a cart, orders, checkout with online payments | `karni new "Corner Shop" --recipe shop` |
| [`booking`](recipes/booking.md) | Resources with time slots that members book and pay for, never over capacity | `karni new "Yoga Studio" --recipe booking` |
| [`crm`](recipes/crm.md) | Companies, contacts and deals in a pipeline, with two-factor sign-in | `karni new "Sales Desk" --recipe crm` |
| [`lms`](recipes/lms.md) | Courses with lessons in order, enrolments and each student's progress | `karni new "Course Hub" --recipe lms` |
| [`marketplace`](recipes/marketplace.md) | Sellers, listings, orders and the payout after the fee | `karni new "Market Hall" --recipe marketplace` |
| [`data-portal`](recipes/data-portal.md) | Datasets and indicators by region and sector, with saved charts | `karni new "Data Portal" --recipe data-portal` |

| Module | What it gives | One command |
|---|---|---|
| `karni-payments` | Hosted checkout, refunds and signature-verified webhooks for Stripe and Razorpay, with a test provider for CI | `pip install karni-payments && karni add payments` |
| `karni-approvals` | A second person approves high-value changes before they are written, with a queue and an audit trail | `pip install karni-approvals && karni add approvals` |
| `karni-impersonation` | Safe "log in as user" for support staff: a banner, a time limit, both identities in the audit trail | `pip install karni-impersonation && karni add impersonation` |
| [`karni-site`](public-site.md) | A public website whose every text, image and menu is editable in the admin, with forms and redirects | `pip install "karni-site[images]" && karni add site` |
| [`karni-charts`](charts.md) | Charts defined and previewed in the admin, served under each resource's access | `pip install karni-charts && karni add charts` |
| [`karni-reports`](reports.md) | A row printed to PDF from an HTML template in the background, served only to users who may see the row | `pip install karni-reports && karni add reports` |
| [`karni-ai`](ai-extraction.md) | Rows for any resource read from text, a web page or a PDF by a language model, always through the import preview | `pip install "karni-ai[<provider>]" && karni add ai` |
| [`karni-storage`](storage.md) | Files a row owns, in S3 or an S3-compatible service, served only to whoever may read the row | `pip install "karni-storage[images]" && karni add storage` |

## Quickstart

You need Python 3.12 or later and Node 20.19 or later. This runs the shop
recipe on SQLite, with no Docker:

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install karni karni-cli karni-payments pytest pytest-django
karni new "Corner Shop" --recipe shop && cd corner_shop
printf 'DATABASE_URL=sqlite:///data/db.sqlite3\nKARNI_CACHE=locmem\n' > .env
karni build
karni serve --local
```

Then, in a second terminal: `cd corner_shop/frontend && npx --yes npm@11 install && npm run dev`.
The [quickstart guide](quickstart.md) does the same on PostgreSQL, Karni's
default database.

## How it works

```mermaid
flowchart LR
    spec["karni.yaml<br/>apps, entities, access,<br/>roles, modules, pages"]
    plan["karni plan<br/>what will change,<br/>risky changes first"]
    build["karni build<br/>migrate, seed, types,<br/>tests, karni check"]
    owned["Code Karni owns<br/>&lt;app&gt;/karni/, the karni:spec blocks<br/>rewritten on every build"]
    yours["Code you own<br/>&lt;app&gt;/models.py, viewsets.py,<br/>seeds.py, your pages and tests<br/>created once, never rewritten"]
    pkgs["Versioned packages<br/>karni, @karni/ui, karni-cli<br/>moved on by karni upgrade"]
    spec --> plan --> build
    build --> owned
    build --> yours
    yours -- "subclass" --> owned
    owned -- "extends" --> pkgs
```

The code you own subclasses what Karni writes. For one resource it is a model
and a viewset:

```python
class Venue(BaseModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    capacity = models.IntegerField()


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("organizer", "staff"))
    search_fields = ("name", "city")
```

From those two classes Karni derives the endpoints at `/api/venues/`, the
OpenAPI schema and a typed client, the admin screen, the permission checks
on every query, and a table, form and detail view in React
([what Karni owns, and what the project owns](app-spec.md#what-karni-owns-and-what-the-project-owns)).

## Questions

Karni is not production-ready yet: it has two reference applications and CI
on every push, but no known production deployment. The
[FAQ](faq.md) answers that and more, the [stability promise](stability.md)
says what an upgrade may change, and Karni is open source under the Apache
License 2.0.
