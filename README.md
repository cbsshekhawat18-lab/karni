# Karni

Karni is a framework, not boilerplate: it stays a versioned dependency you
upgrade, and it is built so an AI coding agent extends it instead of
reinventing it. Declare models and access; the REST API, admin, permissions,
query optimisation, forms, tables, tests and seed data follow from those
declarations, and `karni upgrade` carries a project across releases.

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
`?expand=`, an N+1-free query plan, an OpenAPI document — plus an admin page,
a generated form and table in the React frontend, and a two-line test that
proves the whole surface and the isolation between owners.

**Documentation:** https://cbsshekhawat18-lab.github.io/karni/ — start with
the [quickstart](docs/quickstart.md), the [tutorial](docs/tutorial.md), or
[building with an AI agent](docs/guide/with-ai.md).

## What is measured

Numbers below come from commands in this repository; nothing is estimated.

| | Measured |
|---|---|
| The reference app, [EventHub](examples/eventhub/README.md): an event ticketing platform with payments, a Celery e-mail, an organizer dashboard with CSV export and four roles | **582 lines of project code** (models 83, viewsets 87, pages 291, other 121) — `python scripts/loc.py --pristine <karni new output>`; the first build was 656 lines, and the [friction it found](examples/eventhub/FRICTION.md) became framework fixes |
| EventHub's tests | 14 backend tests (`assert_crud`, `assert_isolated`, the book → pay → webhook → e-mail path) and 3 Playwright journeys against the running stack, in CI on every push |
| Karni's own suites | `karni` 1,101, `karni-cli` 371, `karni-payments` 127, `@karni/ui` 438, `@karni/payments-ui` 14 tests; ruff, mypy, ESLint and tsc clean |
| `karni rules` (the conventions an agent reads first) | 396 cl100k tokens for 32 rules |
| Token cost of building an app with an agent | not measured yet — this README states no figure until it is |

## Why not a boilerplate

A boilerplate is copied once and then owned forever: every project carries
its own serializers, permission classes, admin files and login pages, and
none of them gets the upstream fix. Karni keeps the generic code in the
`karni` package, `@karni/ui` and the `karni` command, enforces that it stays
there (every rule fails the build; every rule has a reasoned opt-out), and
records what is missing when a real app needs project code Karni should own.

Compared honestly with the common Django starting points:

| | Cookiecutter Django | SaaS Pegasus | A typical Django SaaS boilerplate | Karni |
|---|---|---|---|---|
| Delivery | a template you copy | a template you copy (commercial) | a repository you fork | a dependency you upgrade; `karni upgrade` applies codemods and lists the rest |
| Serializers, admin, permissions, forms | written per project | generated once, then yours | yours | generated from the model and the `access` declaration, every time |
| Permissions model | DRF's, per view | DRF's, per view, plus teams | varies | one declaration compiled into the request gate *and* the row filter |
| Frontend | templates or your SPA | React/Vue/HTMX + Tailwind, wired | varies | `@karni/ui`: schema-driven table, form, detail, auth; pages are compositions |
| Payments, teams, 2FA, social login | partly, as options | yes, mature and polished | often | payments as a module; 2FA and social login in accounts; no teams/tenancy yet |
| Conventions enforced | no | no | no | yes: `karni check`, ESLint preset, architecture tests |
| Built for AI agents | no | no | no | `karni context`, `karni rules`, `karni explain`, generated agent files, MCP |
| Maturity, community, deployments | large and battle-tested | large, actively supported, many features Karni lacks | varies | 0.1: one reference app, APIs still moving under the [stability promise](docs/stability.md) |

Cookiecutter Django and SaaS Pegasus are better choices today for a team that
wants a proven, complete starting point and will own the code. Karni is for
teams (and agents) that want the generic parts to stay upstream, and accept a
younger framework for it.

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

Python 3.12+, Django 5.1, Node 20+. Apache-2.0. See
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and the
[stability promise](docs/stability.md).
