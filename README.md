<img src="assets/brand/karni-mark.svg" alt="" width="56" align="left" style="margin-right:12px">

# Karni

Karni is a Django + React framework for teams and AI coding agents that
want the generic parts of a web application — the REST API, admin,
permissions, forms, tables, tests and seed data — to come from an upgradable
package instead of being generated again in every project.

[![CI](https://github.com/cbsshekhawat18-lab/karni/actions/workflows/ci.yml/badge.svg)](https://github.com/cbsshekhawat18-lab/karni/actions/workflows/ci.yml)
[![Security scans](https://github.com/cbsshekhawat18-lab/karni/actions/workflows/security.yml/badge.svg)](https://github.com/cbsshekhawat18-lab/karni/actions/workflows/security.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](./LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/cbsshekhawat18-lab/karni)](https://github.com/cbsshekhawat18-lab/karni/commits/main)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

> **Status:** 0.1, pre-release. One reference application runs end to end
> (EventHub: payments, Celery, four roles, Playwright journeys); the public
> APIs still move under the [stability promise](docs/stability.md), and
> `karni upgrade` carries a project across each change.

## What is Karni

Most Django + React starting points are boilerplates: a template you copy
once (Cookiecutter Django, SaaS Pegasus, the many "django react boilerplate"
repositories) and then own forever, with your own serializers, permission
classes, admin files and login pages that never get the upstream fix. AI
coding agents make the copying faster and the duplication worse: every new
project gets a fresh paste of the same code, and five projects end up with
five slightly different versions of it.

Karni keeps that code in three versioned packages — `karni` (Python),
`@karni/ui` (React) and the `karni` command — and generates the rest from
two declarations: the model and its `access` policy.

```python
class Event(BaseModel):
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Owned("organizer"))
```

That is a complete REST resource — filtering, search, pagination,
`?expand=`, an N+1-free query plan, an OpenAPI document — plus an admin
page, a generated form and table in the React frontend, and a two-line test
that proves the whole surface and the isolation between owners. The
`access` declaration is one predicate compiled into both the request gate
and the row filter, so a row outside a user's scope is a 404, never a leak.

For AI agents, Karni ships what they need to extend it instead of
reinventing it: generated `AGENTS.md` / `CLAUDE.md` / Cursor / Copilot /
Windsurf / Cline / Aider adapters, `karni context` (the project in a few
hundred tokens), `karni rules` (32 conventions), `karni check` (fails the
build when generic code is written by hand) and `karni explain` (every
error names its fix). The same commands work by hand.

## Who it is for, and who it is not for

**For:** a team starting a Django + React product that wants an upgrade
path instead of a fork; a developer driving Claude Code, Cursor or Copilot
who is tired of reviewing the same serializer for the tenth time; anyone
who wants row-level permissions, isolation tests and query budgets to be
the default rather than something to remember.

**Not for:** an existing Django application — Karni has no retrofit path
yet, it scaffolds new projects; a product that needs teams, multi-tenancy
or subscription billing today — SaaS Pegasus ships those, Karni does not;
a stack that is not Django REST Framework + React; anyone who wants to own
and hand-edit every file, which is exactly what a boilerplate is for.

## What is measured

Numbers come from commands in this repository; nothing is estimated.

| | Measured |
|---|---|
| The reference app, [EventHub](examples/eventhub/README.md): an event ticketing platform with payments, a Celery e-mail, an organizer dashboard with CSV export and four roles | **593 lines of project code** (models 83, viewsets 87, pages 291, other 132) — `python examples/eventhub/scripts/loc.py --pristine <karni new output>`; the first build was 656 lines, and the [friction it found](examples/eventhub/FRICTION.md) became framework fixes |
| EventHub's tests | 14 backend tests (`assert_crud`, `assert_isolated`, the book → pay → webhook → e-mail path) and 3 Playwright journeys against the running stack, in CI on every push |
| Karni's own suites | `karni` 1,310, `karni-cli` 378, `karni-payments` 127, `karni-approvals` 28, `karni-impersonation` 22, `@karni/ui` 454, `@karni/payments-ui` 14, `@karni/approvals-ui` 7, `@karni/impersonation-ui` 5 tests; ruff, mypy, ESLint and tsc clean |
| `karni rules` (the conventions an agent reads first) | 402 cl100k tokens (395 o200k) for 33 rules |
| Token cost of building an app with an agent | not measured yet — this README states no figure until it is |

## How Karni compares

| | Plain Django + DRF | Cookiecutter Django | SaaS Pegasus | Karni |
|---|---|---|---|---|
| What you start with | an empty project | a template you copy, with Docker, Celery, allauth and deployment wired | a generated codebase you own (commercial), with teams, billing, CMS and a React/HTMX/Vue choice | a dependency you upgrade; `karni new` writes only settings, URLs, compose and app code |
| Serializers, viewsets, admin, permissions, forms | written per model | written per model | generated once by Pegasus, then yours | generated from the model and the `access` declaration, every time |
| Permissions | DRF's, per view | DRF's, per view | DRF's, per view, plus teams | one declaration compiled into the request gate *and* the row filter; roles as data |
| Frontend | your choice | templates or your SPA | React, Vue or HTMX with Tailwind, wired | `@karni/ui`: schema-driven table, form, detail and auth; pages are compositions |
| Teams, billing, 2FA, social login | none | partly, as options | yes, mature and polished | payments as a module; 2FA and social login in accounts; no teams or tenancy yet |
| Conventions enforced | no | no | no | `karni check`, an ESLint preset and architecture tests fail the build; every rule has a reasoned opt-out |
| Built for AI agents | no | no | no | adapters for seven tools, `karni context`, `karni rules`, `karni explain`, MCP |
| Upgrades | pip | none (it is your code) | diffs against a regenerated project | `karni upgrade` applies codemods and lists the manual steps |
| Maturity | the standard | large and battle-tested | large, actively supported, many features Karni lacks | 0.1: one reference app, APIs still moving under the stability promise |

Cookiecutter Django and SaaS Pegasus are the better choice today for a team
that wants a proven, complete starting point and will own the code. Karni is
for teams and agents that want the generic parts to stay upstream, and
accept a younger framework for it.

## Installation

```sh
pip install karni karni-cli
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env
docker compose up -d        # PostgreSQL, Redis, Django, Celery, the frontend
karni check                 # conventions and system checks
```

Python 3.12+, Django 5.1, Node 20+. The [quickstart](docs/quickstart.md)
walks through adding the first model; the
[tutorial](docs/tutorial.md) builds EventHub.

## Documentation

https://cbsshekhawat18-lab.github.io/karni/ — the [quickstart](docs/quickstart.md),
the [tutorial](docs/tutorial.md), [building with an AI agent](docs/guide/with-ai.md),
[building without one](docs/guide/without-ai.md), and the reference for the
[API](docs/api.md), [accounts](docs/accounts.md), [admin](docs/admin.md),
[testing](docs/testing.md), [the `karni` command](docs/cli.md),
[settings](docs/settings.md) and [error codes](docs/errors.md).

## Frequently asked questions

**How is this different from a Django boilerplate?**
A boilerplate is copied into your project once; from then on the
serializers, permission classes, admin files and login pages are yours to
maintain, and no upstream fix reaches them. Karni keeps that code in the
`karni` package and `@karni/ui`, generates per-model pieces from the model
and its `access` declaration at runtime, and ships `karni upgrade` to carry
a project across framework releases. Your project contains only the code
that is specific to it.

**Does it work with Cursor, Copilot and Claude Code?**
Yes. `karni new` and `karni rules sync` write the adapter files each tool
reads — `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md`,
Windsurf, Cline, Aider and Junie — all generated from one set of rules, so
they never drift apart. `karni context` gives an agent the project
inventory in a few hundred tokens, `karni check` tells it when it wrote
generic code by hand, and `karni explain <code>` turns every error into the
fix. An MCP server exposes the same commands as tools.

**Can I use it without AI tools?**
Yes; nothing in Karni calls a model. The agent adapters are plain files, and
every generator (`karni make model`, `karni make viewset`, `karni make
page`, …) is a command a person runs. The documentation has a guide for
building with an agent and one for building without.

**Why not just use Cookiecutter Django?**
Use Cookiecutter Django if you want a proven, complete Django starting point
and are happy to own the code it generates; it is more mature than Karni
and has a large community. Choose Karni if you want the generic code to
stay in an upgradable dependency, permissions compiled into the queryset
by default, a schema-driven React UI, and first-class support for driving
the project with an AI agent — and accept a younger framework for it.

**How much code do I actually write per model?**
The model, an `access` declaration, and whatever is specific to your domain.
The reference application, an event ticketing platform with payments, a
Celery e-mail, an organizer dashboard and four roles, is 593 lines of
project code in total (models 83, viewsets 87, pages 291, other 121);
everything else — serializers, permission checks, admin, forms, tables,
tests, seed data — comes from the framework.

**Is it production-ready?**
Not yet. Version 0.1 has one reference application and a test suite that
runs in CI, but the public APIs still change under the stability promise
and the packages are unpublished. Breaking changes ship with codemods and
migration notes, and `karni upgrade` applies them.

## Repository

| Path | What it is |
|---|---|
| `packages/karni/` | the Python package: models, scopes, `access`, API, accounts, admin, events, scheduling, testing, seeding, error codes |
| `packages/karni-ui/` | `@karni/ui` and its ESLint plugin |
| `packages/karni-cli/` | the `karni` command: `new`, `make`, runners, `upgrade`, `context`, `rules`, `explain` |
| `templates/project/` | the scaffold `karni new` renders |
| `modules/karni-payments/` | the payments module (Stripe, Razorpay, a test provider) |
| `examples/eventhub/` | the reference application and its friction log |
| `docs/` | the documentation site (Material for MkDocs) |
| `assets/brand/` | the Karni mark and its usage rules |

## Contributing

Pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) (the
rules every change follows, the development setup, what is generated) and
the [Code of Conduct](CODE_OF_CONDUCT.md). The most useful contributions
right now: a second reference application and its friction log, module
proposals under `modules/`, and anything that makes `karni check` catch a
mistake earlier. If Karni is useful to you, a star helps other people
building with agents find it.

## Author and credits

Karni is built and maintained by **Chandrabhan Shekhawat** — **Gigai Kripa
Services** (<https://gigaikripaservices.com/>).

## License

Released under the [Apache License 2.0](LICENSE) — free to use, modify and
self-host, for individuals and companies alike, with an explicit patent
grant. © 2026 Chandrabhan Shekhawat — Gigai Kripa Services.

## Security

For responsible disclosure see [SECURITY.md](SECURITY.md); please do not
open public issues for security reports.
