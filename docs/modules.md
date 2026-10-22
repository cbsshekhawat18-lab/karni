---
description: "The Karni module contract: how an installable app plugs into a project with one command and one URL include, with karni-payments as the reference implementation."
---

# The Karni module contract

A Karni module is an installable Django app that plugs into a Karni project
with **one CLI command and at most one URL include**. There is no settings
editing and no serializer/router/admin boilerplate. `karni-payments`
(`modules/karni-payments/`) is the reference implementation. This page is
precise enough to build a module without reading Karni's source.
`karni make module <name>` writes the skeleton below (`modules/karni-<name>/`).

## Naming

| Thing | Name | Example |
| --- | --- | --- |
| PyPI distribution | `karni-<x>` | `karni-payments` |
| Django app module | `karni_<x>` (top-level, dot-free) | `karni_payments` |
| App label | `karni_<x>` (must equal the module name) | `karni_payments` |
| npm UI package | `@karni/<x>-ui` | `@karni/payments-ui` |

`karni add <x>` derives all of these from `<x>`, so the convention is what
makes the CLI work. A note for third parties: the `@karni` npm scope and the
`karni-` PyPI prefix belong to the Karni project. For first-party-style
wiring, your *distribution* must still be named `karni-<x>` and your app
`karni_<x>`. PyPI allows this, but squatting unrelated packages under the
prefix is not welcome. Any other npm name is fine for your UI package, since
the `@karni` scope convention is only a recommendation.

## Required contents

A module ships, at minimum:

```
karni-<x>/
  pyproject.toml           # dist name, karni pin, entry points, package data
  README.md                # settings table, wiring, escape hatches
  karni_<x>/
    __init__.py
    apps.py                # AppConfig, label karni_<x>
    conf.py                # DEFAULTS fragment + get() accessor
    models.py              # on karni.models.BaseModel / SoftDeleteModel
    viewsets.py            # on karni.api.BaseViewSet (auto-registered)
    migrations/            # real, committed migrations
    AGENTS.fragment.md     # agent guidance surfaced by `karni rules` + AGENTS.md
    urls.py                # OPTIONAL, only for non-API URLs (webhooks etc.)
  tests/                   # standalone suite with its own settings module
```

### 1. Models and viewsets on Karni bases

Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`) and declare
`APIMeta` for API exposure and `AdminMeta` for the derived admin. Viewsets
inherit `karni.api.BaseViewSet` and **must live in `karni_<x>/viewsets.py`**
(or `karni_<x>/api/viewsets.py`). That is where the auto-router's
`autodiscover()` looks, and a viewset defined elsewhere never registers.

State whether your module ships admin code. The default is **no
`admin.py`**, with the derived admin built from `AdminMeta` (karni-payments
does this). If you must ship explicit admin classes, say so in the README.
Explicit registrations always beat autodiscovery.

### 2. Committed migrations: append-only within a major

Generate migrations with a scratch settings module and commit them. Within a
major version, migrations are **append-only**. Never edit or re-number a
shipped migration, because projects have already applied it. Squash only
across a major release.

### 3. The settings fragment (`karni.settings` entry point)

This is how "apply a settings fragment" works without ever editing a
project's `settings.py`. The fragment ships *in* the module:

```toml
# pyproject.toml
[project.entry-points."karni.settings"]
payments = "karni_payments.conf:DEFAULTS"
```

```python
# karni_<x>/conf.py
import environ
from django.conf import settings

env = environ.Env()

DEFAULTS = {
    "KARNI_PAYMENTS_PROVIDER": env("KARNI_PAYMENTS_PROVIDER", default="stripe"),
    # ... every setting your module reads, env-driven where sensible
}

def get(name):
    return getattr(settings, name, DEFAULTS[name])
```

`karni_settings()` merges every installed fragment after BASE and the
profile overlay and **before** project overrides, so project settings always
win. Hard rules (violations raise `ImproperlyConfigured` naming your entry
point):

- **New top-level names only.** A key that collides with Karni's BASE, the
  profile overlay or another fragment is an error. There is no deep merge in
  v0.1. Fragments extend the settings vocabulary and never retune Karni.
  In particular, never put `INSTALLED_APPS` (or any Django builtin) in a
  fragment. App wiring is `karni add`'s job.
- **Import-light.** The fragment module must import without Django
  configured. It holds plain data + `django-environ` reads only, and it must
  **not touch `django.conf.settings` at import time**. Fragments are merged in
  entry-point-name order and each dict is deep-copied, so later mutation of
  project settings never corrupts your `DEFAULTS`.
- **Per-profile values**: fragments merge before the profile is observable
  through Django. If a default must differ between dev and prod, read
  `os.environ["DJANGO_ENV"]` inside the fragment (the documented hatch).
- **Read through your own accessor.** Module code reads settings via
  `conf.get(name)` → `getattr(settings, name, DEFAULTS[name])`, so the
  module also works in projects that configure Django without
  `karni_settings()`. The merge is a convenience. Correctness does not
  depend on it.
- Credentials default to `""` and are validated **lazily at use** (with a
  clear error naming the env var), never at boot.

### 4. The karni dependency MUST be range-pinned

```toml
dependencies = ["karni>=0.1,<0.2"]
```

Karni 0.x minors may break, so a module declares the minor it was built
against. When Karni reaches 1.0, the pin becomes `karni>=1,<2` and Karni's
public-API deprecation policy applies: **warn one minor, remove next
major**. Modules get a full minor release of warnings before an API they
use disappears, and they must follow the same policy toward their own users.

### 5. `AGENTS.fragment.md`: agent guidance that travels with the module

A ≤15-line Markdown fragment lives **inside the app package** (next to
`apps.py`), pinned as package data so it survives wheel builds:

```toml
[tool.hatch.build.targets.wheel]
packages = ["karni_<x>"]
artifacts = ["karni_<x>/AGENTS.fragment.md"]
```

Contents: what the module provides, the one `urls.py` include line (if any),
the env vars, and the module's hard rules (karni-payments: "never call
provider SDKs directly", "never trust client amounts"). `karni add <x>`
reads it through the **project's** interpreter
(`importlib.resources.files("karni_<x>")`) and records it in the project as
`.karni/modules/<x>.md` (committed). From there it reaches agents through
the CLI, where `karni rules` prints it under `[module:<x>]`. It also reaches
them through the generated adapters: `karni rules sync` renders it into
`AGENTS.md` (and `.junie/AGENTS.md`) between markers:

```
<!-- karni:module:<x> -->
...fragment...
<!-- /karni:module:<x> -->
```

Recording is idempotent (re-running `karni add` replaces the file). If the
module is not installed yet, `karni add` tells the user to run it again
after installing. See [Karni for AI agents](agents.md).

### 6. Optional `urls.py`: explicit include, documented

Viewsets ride the auto-router and need **no** URL wiring. Only raw
endpoints (webhooks, callbacks) go in a `karni_<x>/urls.py`, and the module
documents the single include line in its README **and** its
`AGENTS.fragment.md` (`karni add` prints it too):

```python
path("payments/", include("karni_payments.urls")),
```

### 7. Optional `karni.checks` hooks

A module may register build-failing checks that `manage.py karni_check`
runs:

```toml
[project.entry-points."karni.checks"]
payments = "karni_payments.checks:run_checks"   # () -> list[str] of failures
```

### 7b. Optional `karni.scopes`: model scopes

A module can add a **scope**, a named filter that every Karni default
manager applies (see [models.md](models.md#scopes-the-filters-every-default-manager-applies)).
Installing the module turns it on. No project code changes:

```toml
[project.entry-points."karni.scopes"]
tenant = "karni_tenancy.scopes:TenantScope"   # a karni.scopes.Scope subclass or instance
```

- `name` must be unique (core owns `soft_delete`). `order` places the scope
  in the pipeline (`soft_delete` is 10).
- `applies_to(model)` decides which models it covers. Honour a per-model
  opt-out read through `karni.scopes.scope_option(model, name)`, which reads
  `class ScopeMeta: <name> = ...` on the model.
- `filter(queryset)` runs when a queryset is *built*, which can be import
  time. Read request or task context when the SQL compiles, and raise
  `ScopeContextMissing(model, name, fix=...)` when none is bound. The scope
  fails closed.
- A load failure, a duplicate name or a bad attribute raises
  `ImproperlyConfigured` naming the entry point (system check `karni.E002`).
  Projects reorder or disable scopes with `KARNI_SCOPES`.

### 8. Tests: standalone, with fakes

`tests/` runs with `python -m pytest` inside the module, against the
module's own settings module (pytest ini in the module's `pyproject.toml`).
That means sqlite + locmem cache + `CELERY_TASK_ALWAYS_EAGER` +
`karni_settings()` + the app installed. Ship a **TestProvider-style fake**
for every external service you integrate (in-memory, deterministic ids, real
signature math) and document it, because projects use it in their own suites.
Cover your model constraints, services, API actions, permission gates and
owner scoping.

Modules must pass Karni's architecture rules in their own CI. Run the
enforcement suite against your app:

```bash
pytest --pyargs karni.testing.architecture
```

(The rules: models on `BaseModel`, viewsets on `BaseViewSet` with an `access`
declaration, no `filter_queryset_for_user` override without a reason, no raw SQL outside
`sql/`/`migrations/`, no direct HTTP clients outside `services/`/
`providers/`, no redundant serializers. Each rule has the documented
`# karni: allow(<rule>): <reason>` opt-out.)

### 9. README

Install line (with extras), the settings table (setting, env var, default,
meaning), the include line, security notes, and **every escape hatch**.
The repo rule applies to modules too: no abstraction without an override
path (settings-driven dotted paths, overridable methods, swappable
classes), each documented where the abstraction is.

## Frontend package (optional)

A module's UI package (`@karni/<x>-ui` or your own scope):

- **composes `@karni/ui`** primitives (`Button`, `useKarniClient`,
  `useResourceList`, …) and never builds a parallel table/form/query stack.
- peer-depends on `@karni/ui` (pin the 0.x minor, `"^0.2.0"`, because 0.x
  minors may break), react 18/19 and `@tanstack/react-query`.
- styles with **tokens only** (the `--karni-*` CSS variables), with no raw
  hex and no Tailwind palette imports.
- registers its components in the role registry
  (`registerComponentRole("checkout-button", …)`). Feature-detect and skip
  when the registry export is absent.
- passes the `@karni/eslint-config` preset.
- calls the API through the `KarniClient` from context
  (`useKarniClient().request(...)` against resource-relative paths like
  `/payments/checkout/`) and invalidates `karniKeys`-based query keys so
  resource views refresh.

## Wiring lifecycle (what `karni add <x>` does)

1. Adds `karni-<x>` to `[project].dependencies` in the project's
   `pyproject.toml` (idempotent, parsed, never string-matched).
2. Inserts `"karni_<x>"` into the `# karni:apps` marker block in
   `config/settings.py` (idempotent).
3. Records `AGENTS.fragment.md` as `.karni/modules/<x>.md` and refreshes the
   agent adapters, so `karni rules` and `AGENTS.md` carry the module's
   guidance. It reads the fragment through the project interpreter and
   prints "run again after installing" when the module is not importable yet.
4. Prints the `urls.py` include line and the install + `make migrate`
   reminder. `karni add` never touches the network. The user installs.

Settings then arrive via the entry-point fragment at the next process start,
and migrations apply with `make migrate`. Total project diff for a new module:
one dependency line, one `INSTALLED_APPS` entry, one optional include line.

## Patterns worth copying from karni-payments

- **Role-gated detail actions × owner scoping**: one `access` declaration.
  The acting role must be part of `read`, or role-gated detail actions can
  never reach other users' objects, because `get_object()` looks rows up
  through the read scope. The action gates itself with `@action(access=...)`:

  ```python
  class PaymentViewSet(BaseViewSet):
      model = Payment
      access = Access(read=Owned("user") | HasRole("payments-admin"), write=Owned("user"))

      @action(detail=True, methods=["post"], access=HasRole("payments-admin"))
      def refund(self, request, pk=None):
          payment = self.get_object()  # any payment for an admin, 403 for others
          ...
  ```

  A role-only resource is `access = Access(read=HasRole("x"), write=HasRole("x"))`.
  `HasRole` is both the gate (403) and the row policy (no rows), so it stays
  closed even if someone swaps the permission classes.

- **Read-only resources**: override `create`/`update`/`partial_update`/
  `destroy` to raise `MethodNotAllowed` instead of playing
  `http_method_names` games. Extra `@action` POST routes keep working.
- **Webhook pipeline**: verify signature → persist a dedupe row
  (`UniqueConstraint(provider, event_id)`) in the view's own
  `transaction.atomic` → `transaction.on_commit(lambda: task.delay(...))`
  → all state changes in a locked, idempotent Celery task. Nothing
  state-changing happens in the request cycle.
- **External SDKs**: imported lazily, behind an extra
  (`karni-payments[stripe]`), with the install hint in the error.

## Checklist

- [ ] dist `karni-<x>`, app `karni_<x>`, label `karni_<x>`
- [ ] `dependencies = ["karni>=0.1,<0.2"]` (range-pinned)
- [ ] models on `BaseModel`, `APIMeta` + `AdminMeta` declared, admin
      shipped as derived-only (or the README says otherwise)
- [ ] viewsets on `BaseViewSet`, in `viewsets.py`, auto-registered
- [ ] migrations generated, committed, append-only within a major
- [ ] `karni.settings` fragment: new names only, import-light, env-driven,
      read back through `conf.get()`
- [ ] `AGENTS.fragment.md` ≤15 lines, inside the package, pinned as
      package data
- [ ] optional `urls.py` with the include line documented in README +
      fragment
- [ ] standalone test suite (own settings, sqlite, eager Celery, service
      fakes) green with `python -m pytest`
- [ ] architecture rules pass (`pytest --pyargs karni.testing.architecture`)
- [ ] every abstraction has a documented escape hatch
- [ ] deprecations: warn one minor, remove next major

## Modules in this repository

| Module | What it adds | Install |
|---|---|---|
| `karni-payments` (`modules/karni-payments/`) | hosted checkout, refunds and signature-verified webhooks for Stripe and Razorpay, with a test provider. UI package: `@karni/payments-ui` | `pip install karni-payments && karni add payments` |
| `karni-approvals` (`modules/karni-approvals/`) | maker-checker approvals. A model opts in with `class Karni: requires_approval = [...]`, and a guarded change becomes a pending change that a second person applies or rejects. It comes with a queue in the admin, `/api/pending-changes/`, notifications, timeouts, and every decision in `karni.audit`. UI package: `@karni/approvals-ui` | `pip install karni-approvals && karni add approvals` |
| `karni-impersonation` (`modules/karni-impersonation/`) | "log in as user" for support, done safely: an explicit `impersonate` permission (never implied by staff), no privilege escalation, a banner naming both identities with a one-click exit, a session record, every write attributed to both identities in `karni.audit`, a time limit and a hard block on deleting, exporting and payment changes. The threat model is in its README. UI package: `@karni/impersonation-ui` | `pip install karni-impersonation && karni add impersonation` |

Each module's README is its reference (settings table, wiring, escape
hatches). `karni-approvals` is built on one core hook: every `BaseModel`
write sends [`karni.signals.pre_write`](models.md#write-interception), and a
receiver may defer it. Any module can use that hook the same way.
`karni-impersonation` is built on another, [`karni.vetoes`](api.md#vetoes).
That is a registry the API and admin gates consult after the access
declaration admitted an action. It also builds on `karni.audit`'s batches.
