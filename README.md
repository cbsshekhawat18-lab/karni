<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/cbsshekhawat18-lab/karni/main/assets/brand/karni-horizontal-dark.svg">
    <img alt="Karni" src="https://raw.githubusercontent.com/cbsshekhawat18-lab/karni/main/assets/brand/karni-horizontal.svg" width="280">
  </picture>
</p>

<p align="center">
Karni is a Django + React framework that replaces the Django React boilerplate: the REST API, admin, permissions, React screens and tests come from an upgradable package, so you and your AI coding agent (Claude Code, Cursor, Copilot) write only your domain code.
</p>

<p align="center">
  <a href="https://github.com/cbsshekhawat18-lab/karni/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cbsshekhawat18-lab/karni/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/cbsshekhawat18-lab/karni/releases"><img alt="Release" src="https://img.shields.io/github/v/release/cbsshekhawat18-lab/karni"></a>
  <a href="https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <a href="https://cbsshekhawat18-lab.github.io/karni/"><img alt="Docs" src="https://img.shields.io/badge/docs-online-blue"></a>
</p>

<p align="center">
  <img alt="A terminal runs karni new, karni make model, migrate, seed and serve; then the browser shows the welcome page, the admin listing the seeded events, and the React app's events table and detail view." src="https://raw.githubusercontent.com/cbsshekhawat18-lab/karni/main/docs/assets/karni-demo.gif" width="880">
</p>

## What is Karni

Most Django React boilerplates and starter templates are copied into your project once. After that, the serializers, permission classes, admin files and login pages are yours to maintain, and an upstream fix never reaches them. AI coding agents make the copying faster and the duplication worse: every new project gets a fresh copy of the same code.

Karni keeps that code in three versioned packages: `karni` (Python), `@karni/ui` (React) and the `karni` command. You declare a model and who may access it; Karni gives you the REST API, admin, permissions, React screens, tests and seed data. It is for teams that start a new full-stack Django + React product, with or without an AI agent.

## Show, don't tell

This is what a developer writes in the reference app, [EventHub](examples/eventhub/README.md) (`__str__` left out):

```python
class Venue(BaseModel):
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)
    capacity = models.IntegerField()


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("organizer", "staff"))
    search_fields = ("name", "city")
```

And this is the page `karni make page venues --resource venues` writes:

```tsx
import { Page, ResourceTable } from "@karni/ui";

export default function VenuesPage() {
    return (
        <Page title="Venues">
            <ResourceTable resource="venues" />
        </Page>
    );
}
```

What you get with no other code:

- REST endpoints at `/api/venues/`, with filters, search, ordering, pagination and `?expand=`
- the OpenAPI schema, Swagger UI and a typed TypeScript client
- an admin screen, with no `admin.py`
- a table with sorting, filters, pagination and CSV or XLSX export, plus a form and a detail view
- permissions: everyone reads, organizers and staff write
- a one-call test of the whole API (`assert_crud`) and realistic seed data

All of EventHub, with payments, e-mail and four roles, is 593 lines of project code. Rebuilding the leads module of Social Stats on Karni took it from 2,346 lines to 996 ([case study](docs/case-study-social-stats.md)).

## Why not just use Django or a boilerplate?

Karni stays a versioned dependency that you upgrade; a boilerplate is copied once and diverges forever. Plain Django gives you the parts, but every project writes the same serializers, permission classes, admin files and tests again. A boilerplate writes them for you once, and then a security fix upstream never reaches your copy. With Karni the generic code stays in the package, and `karni upgrade` applies the code changes each release needs.

## Quickstart

You need Python 3.12 or 3.13 and Node 20 or later. Version 0.2.0 is not on PyPI or npm yet, so these commands install it from the GitHub release.

```sh
python3.12 -m venv .venv && . .venv/bin/activate
R=https://github.com/cbsshekhawat18-lab/karni/releases/download/v0.2.0
pip install "$R/karni-0.2.0-py3-none-any.whl" "$R/karni_cli-0.2.0-py3-none-any.whl" pytest pytest-django
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env
printf 'DATABASE_URL=sqlite:///data/db.sqlite3\nKARNI_CACHE=locmem\nMEDIA_ROOT=data/media\nSTATIC_ROOT=data/static\n' >> .env
karni make app events
karni make model Event title:str:200 starts_at:datetime organizer:fk:User -a --access owned:organizer
karni make migration --app events && karni migrate
karni make page login --kind login
karni seed
karni serve --local
```

In a second terminal, in the same directory:

```sh
cd ticket_shop/frontend
npm install https://github.com/cbsshekhawat18-lab/karni/releases/download/v0.2.0/karni-ui-0.2.0.tgz
npm run dev
```

Open `http://127.0.0.1:8000/` for the welcome page and `/admin/` for the admin. Open `http://localhost:5173/login` for the React app. Sign in as `demo@example.com` with the password `karni-password`; `karni seed` created that user. The [quickstart guide](docs/quickstart.md) explains each step.

## Karni compared

| | Plain Django + DRF | Cookiecutter Django | SaaS Pegasus | Karni |
|---|---|---|---|---|
| What you start with | an empty project | a generated project you own | a generated codebase you own (paid, with an open-source edition) | a dependency you upgrade |
| Serializers, viewsets, admin, permissions per model | you write them | you write them | generated once, then yours | derived from the model and its `access` rule |
| An upstream fix reaches your code | only for Django itself | no | by regenerating and merging | through `karni upgrade` |
| Teams, subscriptions, multi-tenancy | no | no | yes, mature | no; payments only, as a module |
| Maturity | the standard | large community, many years in production | large, actively supported | version 0.2, two reference apps |
| Deployment | your choice | Docker and cloud guides, widely used | deploy guides for several platforms | a generated Docker Compose stack, not yet verified end to end |
| AI agent guidance in the project | none | none in the generated project | Cursor rules, CLAUDE.md and Claude Code skills | adapters for eight tools from one rule set, `karni context`, a build-failing `karni check`, an MCP server |

Choose Cookiecutter Django or SaaS Pegasus for a proven, complete starting point that you will own. Choose Karni to keep the generic code upstream, and accept a younger framework for it.

## How it works

**BaseModel.** Every model inherits a UUID key, timestamps, soft delete and who-created-it fields. Default managers apply named scopes, so a deleted row never appears in a query you forgot to filter. [Models](docs/models.md)

**BaseViewSet and generated serializers.** A viewset names a model and an `access` rule. Karni derives the serializer, filters, search, pagination, `?expand=` and an N+1-free query plan, and compiles `access` into both the permission check and the queryset, so a row outside your scope is a 404. [API](docs/api.md)

**An admin that registers itself.** Every model appears in a django-unfold admin with columns, filters and search from its fields. `AdminMeta` changes a detail; your own `ModelAdmin` replaces it. [Admin](docs/admin.md)

**Schema-driven components.** `@karni/ui` reads the OpenAPI document, so `ResourceTable`, `ResourceForm` and `ResourceDetail` need only a resource name to render the right columns, inputs and validation. [UI](docs/ui.md)

**The enforcement layer.** `karni check`, an ESLint preset and architecture tests fail the build when project code rebuilds what Karni ships, such as a copy of the generated serializer or a raw `<table>`. Every opt-out needs a written reason. [Enforcement](docs/enforcement.md)

## Cheat sheet

A model and its API, in two files:

```python
# events/models.py
from django.db import models
from karni.models import BaseModel

class Venue(BaseModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)

# events/viewsets.py
from karni.api import Access, BaseViewSet, HasRole, Public
from events.models import Venue

class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("organizer", "staff"))
```

A page, from `karni make page venues --resource venues`:

```tsx
import { Page, ResourceTable } from "@karni/ui";

export default function VenuesPage() {
    return (
        <Page title="Venues">
            <ResourceTable resource="venues" />
        </Page>
    );
}
```

The commands you use every day:

```sh
karni new "Shop"      # scaffold a project
karni add payments    # wire an installed module into settings and the agent files
karni types           # TypeScript types and hooks from the OpenAPI document
karni context         # the project inventory an agent reads first
karni seed            # realistic, connected demo data
karni check           # conventions and system checks; non-zero exit on a violation
```

The project's Makefile:

<!-- generated:make-targets -->
```sh
make up         # karni serve -d
make down       # docker compose down
make serve      # karni serve
make migrate    # karni make migration; karni migrate
make types      # karni types
make check      # karni check; karni rules sync --check
make rules      # karni rules
make agents     # karni rules sync
make context    # karni context
make test       # karni test
make shell      # karni shell
make routes     # karni routes
make schedules  # karni schedule list
make superuser  # karni createsuperuser
make logs       # docker compose logs -f django worker beat
```
<!-- /generated:make-targets -->

## Commands

Each command links to its full entry in the [reference](docs/REFERENCE.md#commands).

<details>
<summary><b>All karni commands</b></summary>

<!-- generated:commands -->
| Command | What it does |
|---|---|
| [`karni new`](docs/REFERENCE.md#karni-new) | Scaffold a project from templates/project |
| [`karni add`](docs/REFERENCE.md#karni-add) | Install an optional module and wire it into settings |
| [`karni upgrade`](docs/REFERENCE.md#karni-upgrade) | Upgrade across Karni versions: codemods, diff, manual-change report |
| [`karni doctor`](docs/REFERENCE.md#karni-doctor) | Report the environment: project, interpreter, Node, adapters, history |
| [`karni config`](docs/REFERENCE.md#karni-config) | Read and write Karni settings: project .karni/config.toml (committed) or --global ~/.config/karni/config.toml; the project wins: [get](docs/REFERENCE.md#karni-config-get), [set](docs/REFERENCE.md#karni-config-set), [list](docs/REFERENCE.md#karni-config-list) |
| [`karni context`](docs/REFERENCE.md#karni-context) | Print a compact machine-readable project inventory |
| [`karni rules`](docs/REFERENCE.md#karni-rules) | Karni's conventions for humans and AI agents (no Django needed): [sync](docs/REFERENCE.md#karni-rules-sync) |
| [`karni check`](docs/REFERENCE.md#karni-check) | Run architecture and system checks |
| [`karni explain`](docs/REFERENCE.md#karni-explain) | Explain an error code (E104, C101, PAY004, K106): why and the fix |
| [`karni types`](docs/REFERENCE.md#karni-types) | Generate TS types and typed hooks from the backend OpenAPI |
| [`karni mcp`](docs/REFERENCE.md#karni-mcp) | Serve context, rules and check as MCP tools (needs karni-cli[mcp]) |
| [`karni serve`](docs/REFERENCE.md#karni-serve) | Start the dev stack — wraps `docker compose up` (or `manage.py runserver` with --local) |
| [`karni migrate`](docs/REFERENCE.md#karni-migrate) | Apply migrations — wraps `manage.py migrate [ARGS]` |
| [`karni test`](docs/REFERENCE.md#karni-test) | Run the test suite — wraps `python -m pytest [ARGS]` |
| [`karni shell`](docs/REFERENCE.md#karni-shell) | Open a Django shell — wraps `manage.py shell [ARGS]` |
| [`karni routes`](docs/REFERENCE.md#karni-routes) | List every URL: methods, name, view, model, access — wraps `manage.py karni_routes` |
| [`karni worker`](docs/REFERENCE.md#karni-worker) | Run a Celery worker — wraps `python -m celery -A config worker -l info [ARGS]` |
| [`karni beat`](docs/REFERENCE.md#karni-beat) | Run Celery beat — wraps `python -m celery -A config beat -l info [ARGS]` |
| [`karni schedule`](docs/REFERENCE.md#karni-schedule) | Celery beat schedules — wraps `manage.py karni_schedules`: [list](docs/REFERENCE.md#karni-schedule-list), [run](docs/REFERENCE.md#karni-schedule-run) |
| [`karni seed`](docs/REFERENCE.md#karni-seed) | Fill every model with realistic demo data — wraps `manage.py karni_seed [ARGS]` |
| [`karni sync-roles`](docs/REFERENCE.md#karni-sync-roles) | Create or update the roles KARNI_ROLES declares — wraps `manage.py karni_sync_roles [ARGS]` |
| [`karni createsuperuser`](docs/REFERENCE.md#karni-createsuperuser) | Create an admin user — wraps `manage.py createsuperuser [ARGS]` |
| [`karni manage`](docs/REFERENCE.md#karni-manage) | Run any management command — wraps `manage.py ARGS` (raw passthrough) |
| [`karni make`](docs/REFERENCE.md#karni-make) | Generate project code: apps, models, viewsets, tasks, schedules, listeners, pages: [app](docs/REFERENCE.md#karni-make-app), [model](docs/REFERENCE.md#karni-make-model), [viewset](docs/REFERENCE.md#karni-make-viewset), [serializer](docs/REFERENCE.md#karni-make-serializer), [migration](docs/REFERENCE.md#karni-make-migration), [test](docs/REFERENCE.md#karni-make-test), [factory](docs/REFERENCE.md#karni-make-factory), [seeder](docs/REFERENCE.md#karni-make-seeder), [task](docs/REFERENCE.md#karni-make-task), [schedule](docs/REFERENCE.md#karni-make-schedule), [event](docs/REFERENCE.md#karni-make-event), [listener](docs/REFERENCE.md#karni-make-listener), [command](docs/REFERENCE.md#karni-make-command), [service](docs/REFERENCE.md#karni-make-service), [middleware](docs/REFERENCE.md#karni-make-middleware), [page](docs/REFERENCE.md#karni-make-page), [component](docs/REFERENCE.md#karni-make-component), [module](docs/REFERENCE.md#karni-make-module) |
<!-- /generated:commands -->

</details>

## Reference by area

`stable`: a reference application uses it. `experimental`: only Karni's own tests use it so far. `planned`: not built yet.

<details>
<summary><b>Models and the base classes</b></summary>

Project models inherit `karni.models.BaseModel`. Optional settings for Karni's layers go in a nested `class Karni`.

<!-- generated:models -->
- `stable` `BaseModel`: UUID key, created and updated timestamps, soft delete, `created_by` and `updated_by`
- `stable` Realistic, connected seed data (`karni seed`, `<app>/seeds.py`)
- `stable` Model events and listeners, optionally queued to Celery (`@on_updated`)
- `stable` Field-level change history (`class Karni: audit = True`)
- `experimental` Scheduled tasks (`<app>/schedules.py`, `karni schedule`)
- `planned` A tenant scope on every model (the `karni-tenancy` module)

Base classes: `AuditedModel`, `BaseModel`, `SoftDeleteModel`, `TimestampedModel`, `UUIDModel`.
<!-- /generated:models -->

Full reference: [base classes](docs/REFERENCE.md#base-classes) and [`class Karni` keys](docs/REFERENCE.md#model-metadata-class-karni).
</details>

<details>
<summary><b>API layer and what BaseViewSet provides</b></summary>

A viewset declares `model` and `access`; everything else has a default you can override.

<!-- generated:api -->
- `stable` `BaseViewSet`: CRUD, filters, search, ordering, pagination, `?expand=` and the OpenAPI document, with no serializer
- `stable` `access` declarations (`Public`, `Owned`, `HasRole`, `Where`, `Granted`) compiled into both the request gate and the row filter
- `stable` Query budgets: a list endpoint that runs more queries than declared fails its test
- `stable` CSV and XLSX export of any list (`/export/?format=`)
- `stable` Import from CSV or XLSX with a mandatory preview (`/import/`)
- `experimental` Response caching per viewset (`Cache`, `Uncached`)
- `stable` TypeScript types and typed hooks from the OpenAPI document (`karni types`)

Declarations: `Access`, `Authenticated`, `Budget`, `Cache`, `Can`, `Granted`, `HasRole`, `Owned`, `Public`, `Uncached`, `Unpaginated`, `Unscoped`, `Where`.
<!-- /generated:api -->

Full reference: [karni.api](docs/REFERENCE.md#karniapi).
</details>

<details>
<summary><b>Admin and what is configured for you</b></summary>

`karni.admin` registers every model on start-up. `AdminMeta` adjusts one model; a `ModelAdmin` of your own replaces it.

<!-- generated:admin -->
- `stable` Every model registered with derived columns, filters and search; no `admin.py`
- `experimental` Row scope from the roles' grants: a staff user sees and edits only the rows a grant allows
- `experimental` Field visibility, change history and the import and export screens
- `experimental` A permission matrix of every role against every model and action
<!-- /generated:admin -->

Full reference: [karni.admin](docs/REFERENCE.md#karniadmin).
</details>

<details>
<summary><b>UI components and hooks</b></summary>

`@karni/ui` renders from the OpenAPI schema, so a page names a resource instead of listing fields.

<!-- generated:ui -->
- `stable` `ResourceTable`, `ResourceForm` and `ResourceDetail` driven by the OpenAPI schema
- `stable` Sign-in, session restore and role checks (`AuthProvider`, `LoginForm`, `usePermission`)
- `stable` Data hooks with shared caching (`useResourceList`, `useResourceItem`)
- `stable` Import screen with column mapping and preview (`ResourceImport`)
- `stable` Page building blocks: `Page`, `Layout`, `Stat`, `Modal`, `Toaster`, `EmptyState`
- `experimental` `ChangeHistory`, `DataChart` and `FileUpload`

49 components and 12 hooks, among them `ResourceTable`, `ResourceForm`, `ResourceDetail`, `ResourceSelect`, `ResourceImport`, `AuthProvider`, `AuthGuard`, `LoginForm`, `Page`, `Layout`; hooks `useChangeHistory`, `useImportDescribe`, `useImportJob`, `useImportActions`, `useResourceList`, `useResourceItem`, `useResourceMutations`, `useKarniClient`, `useSchema`, `useAuth`, `usePermission`, `useToast`.
<!-- /generated:ui -->

Full reference: [components and hooks](docs/REFERENCE.md#components-and-hooks).
</details>

<details>
<summary><b>Permissions: roles, scopes, field visibility</b></summary>

All of this is built and tested, including row scope in the admin and import with preview. Parts that no reference application uses yet are marked `experimental`; tenancy is not built.

<!-- generated:permissions -->
- `stable` One `access` declaration per viewset: 404 outside the read scope, 403 for read-but-not-write
- `stable` Roles as data (`KARNI_ROLES`) with the `all` and `own` scopes
- `experimental` The `related:<key>` scope (`class Karni: scope_paths`) and `custom:` scopes
- `stable` Membership through a path: `owner_field = "workspace__members"`
- `stable` Scope paths that do not resolve fail `karni check` (`E214`) instead of answering 500
- `experimental` Field visibility per role (`class Karni: field_roles`)
- `experimental` Row scope in the admin, from the same grants as the API
- `stable` Change history: who changed which field, when, from what to what
- `experimental` Sensitive fields recorded in the history without their values
- `experimental` Maker-checker approvals and safe impersonation (the `approvals` and `impersonation` modules)
- `planned` Tenancy: a tenant scope applied to every model
<!-- /generated:permissions -->

Full reference: [capabilities](docs/REFERENCE.md#permissions) and [settings](docs/REFERENCE.md#accounts--auth).
</details>

<details>
<summary><b>Modules you add with karni add</b></summary>

A module is a separate package for anything with its own service or a real memory cost. Install it, then `karni add <name>` wires it in.

<!-- generated:modules -->
- `experimental` `karni add approvals`: A second person approves high-value changes before they are written, with a queue, an API, notifications and a full audit trail
- `experimental` `karni add impersonation`: 'Log in as user' for support, done safely — an explicit permission, no privilege escalation, a banner, a session record, both identities in the audit trail, blocked actions and a time limit
- `stable` `karni add payments`: Hosted checkout, refunds and signature-verified webhooks for Stripe and Razorpay, with a test provider for CI
- `planned` `karni-tenancy`
<!-- /generated:modules -->

Full reference: [modules](docs/REFERENCE.md#modules).
</details>

<details>
<summary><b>Agent integration: context, rules, adapters, MCP</b></summary>

The same rule set produces every adapter file, so the tools never disagree.

<!-- generated:agents -->
- `stable` `karni context`, `karni rules` and `karni check` in the project workflow
- `stable` Adapter files for every supported agent tool from one rule set (`karni rules sync`)
- `stable` Slash commands for the routine tasks (`/new-model`, `/new-page`, …)
- `experimental` `karni explain <code>`: why an error happens and the fix, offline
- `experimental` MCP server exposing `context`, `rules` and `check` as tools

Slash commands: `/new-model`, `/new-page`, `/add-module`, `/new-module`.
<!-- /generated:agents -->

Full reference: [slash commands](docs/REFERENCE.md#slash-commands) and [agent rules](docs/REFERENCE.md#agent-rules-k).
</details>

<details>
<summary><b>Testing utilities</b></summary>

`karni.testing` turns the usual hundred lines of API tests into a few calls.

<!-- generated:testing -->
- `stable` `assert_crud` and `assert_isolated`: the whole API surface and owner isolation in two calls
- `stable` Generated tests from `karni make model … --with test`
- `stable` OpenAPI snapshot test (`assert_schema_snapshot`)
- `stable` Clients per role (`client_as`)
- `experimental` `query_budget` and `user_with_roles` helpers
- `stable` Architecture rules that fail the build (`karni check`, the ESLint preset)

Helpers: `APITestCase`, `assert_crud`, `assert_isolated`, `assert_schema_snapshot`, `client_as`, `query_budget`, `user_with_roles`.
<!-- /generated:testing -->

Full reference: [karni.testing](docs/REFERENCE.md#karnitesting).
</details>

## Built for AI agents

An agent in a Karni project extends the framework instead of rewriting it:

- **`karni context`** prints the project in a few lines: apps, models, viewsets, roles, components, hooks and pages.
- **`karni rules`** prints the 33 conventions, each with a code, in 402 tokens (cl100k). `karni rules --check <file>` checks one file.
- **Adapter files.** `karni new` writes the file each tool reads, from one rule set: AGENTS.md, CLAUDE.md, Cursor, Copilot, Windsurf, Cline, Aider and Junie, plus slash commands such as `/new-model`.
- **An MCP server.** `karni mcp` serves `context`, `rules` and `check` as tools.

When an agent writes a serializer or a raw `<table>` by hand, `karni check` fails the build and names the component to use. The first prompt, as a new project's welcome page shows it:

```text
You are working in the Karni project `ticket_shop`. Run `karni context` and
`karni rules` first and follow them. Then add an Event model (title, starts_at)
with its viewset and test using `karni make`, run `make migrate && karni types`,
and run `karni check`. Never write serializers, routers, admin classes or
permission checks by hand: Karni derives them.
```

Karni works the same without any AI tool: nothing in it calls a language model, and every generator is a command you run. See [building with an agent](docs/guide/with-ai.md) and [without one](docs/guide/without-ai.md).

## Frequently asked questions

**How is this different from a Django boilerplate?**
A boilerplate is copied into your project once, and its serializers, permission classes and admin files then become yours to maintain. Karni keeps that code in versioned packages, derives the per-model parts from your model, and moves your project to each new release with `karni upgrade`.

**Does it work with Cursor, Copilot and Claude Code?**
Yes. A new Karni project contains the instruction files each of them reads, generated from one rule set, plus slash commands for routine tasks. `karni mcp` offers the same commands as MCP tools.

**Can I use it without AI tools?**
Yes. Nothing in Karni calls a language model, and every generator, such as `karni make model`, is a command you run yourself.

**How much code do I write per model?**
The model, an `access` rule and whatever is specific to your domain. In the reference app EventHub, the `Venue` resource is a five-line model and a four-line viewset.

**Is it production-ready?**
Not yet. Version 0.2.0 has two reference applications and CI on every push, but no known production deployment, no PyPI or npm release, and a Docker path that has not been tested end to end.

**What happens when Karni releases a breaking change?**
A public name keeps working for at least one minor release, with a `KarniDeprecationWarning` that names the release that removes it. `karni upgrade --to <version>` applies the mechanical changes and lists, by file and line, what it could not change ([stability promise](docs/stability.md)).

## Who should not use Karni

- **You have an existing Django application.** Karni scaffolds new projects and has no path to adopt an existing one.
- **You need teams, subscription billing or multi-tenancy now.** SaaS Pegasus ships them; Karni does not yet.
- **Your stack is not Django REST Framework with React.**
- **You want to own and edit every line of the generic code.** That is what a boilerplate is for.

## Status and roadmap

Version 0.2.0 was released on 2026-10-20. Each capability's status is in the [reference](docs/REFERENCE.md#capabilities-and-status).

- **Stable:** models, the API with `access`, roles with the `all` and `own` scopes, the admin, the schema-driven components, change history, import and export, the testing helpers and the agent tooling.
- **Built, not yet used by a reference app:** the `related:` and `custom:` scopes, field visibility per role, row scope in the admin, and the approvals and impersonation modules.
- **Next release, already on `main`:** Django 5.2 LTS, Python 3.14, and a check that fails when a role's scope path does not resolve.
- **Not done:** PyPI and npm releases, an end-to-end test of the Docker stack, the tenancy module.

## Documentation, contributing, security, license

- **Documentation:** <https://cbsshekhawat18-lab.github.io/karni/>, with the [quickstart](docs/quickstart.md), the [tutorial](docs/tutorial.md) and the [reference](docs/REFERENCE.md).
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). A second reference application with its friction log helps most.
- **Security:** report problems privately, as [SECURITY.md](SECURITY.md) describes.
- **License:** [Apache License 2.0](LICENSE).
- **Credits:** built and maintained by Chandrabhan Shekhawat, Gigai Kripa Services (<https://gigaikripaservices.com/>).
