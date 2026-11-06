---
description: "The Karni module contract: how an installable app plugs into a project with one command and one URL include, the module catalog every module and built-in feature describes itself in, and karni remove, with karni-payments as the reference implementation."
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
    karni.module.toml      # the catalog entry: what karni modules, add and remove read
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

Checks that are slow, or that need the database and content, go in the
`karni.checks.seo` group instead, the same kind of hook. They run only with
`karni check --seo` (karni-site's renders every page of the site):

```toml
[project.entry-points."karni.checks.seo"]
site = "karni_site.checks_seo:run_checks"       # () -> list[str] of failures
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

### 7c. Optional `karni.roles`: roles a module declares

A module whose admin pages or API a kind of person uses on their own can
declare that person's role, so a project does not write it. Installing the
module and running `karni sync-roles` (every `karni migrate` does) creates
it:

```toml
[project.entry-points."karni.roles"]
site = "karni_site.roles:declared"   # a dict shaped like KARNI_ROLES, or a callable returning one
```

- The value is `{slug: {"name", "description", "grants"}}`, like
  `KARNI_ROLES` ([roles as data](accounts.md#roles-as-data)). A callable is
  called each time the roles are read, so it can read the module's own
  settings, and returns `{}` while the module is not in `INSTALLED_APPS`.
- The project wins: a slug `KARNI_ROLES` also names is the project's role.
  Give the module a setting that names the slug or turns the role off
  (karni-site has `KARNI_SITE_EDITOR_ROLE`).
- A load failure or a value that is not a dict raises `ImproperlyConfigured`
  naming the entry point (`E205`).

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

`karni add` reads what to wire from the module's manifest
([the module catalog](#the-module-catalog)). A name that is neither in the
catalog nor a module installed in the project's interpreter (a distribution
with a `karni.module.toml`) is refused with `C840` and the closest names, and
nothing is written: wiring an app Python cannot import would stop every
Django command. Install a third-party module first, then add it.

1. Adds the distribution (`karni-<x>`) to `[project].dependencies` in the
   project's `pyproject.toml` (idempotent, parsed, never string-matched).
2. Inserts each of `wiring.apps` into the `# karni:apps` marker block in
   `config/settings.py` (idempotent).
3. Inserts each of `wiring.middleware` into the `# karni:middleware` block
   and each of `wiring.context_processors` into a `# karni:context_processors`
   block it appends once, unless the entry says `manual = true`, in which
   case it prints the entry for you to add. With `wiring.kind = "site"`, an
   app project becomes a site+app.
   When the module has a UI package (`provides.ui`) and the project has
   `frontend/package.json`, it also adds that package to `dependencies` at the
   release's range (`^0.5.0`) and says to run `npm install` in `frontend/`. A
   project without a frontend is left alone. `karni remove` takes the entry out
   again.
4. Records `AGENTS.fragment.md` as `.karni/modules/<x>.md` and refreshes the
   agent adapters, so `karni rules` and `AGENTS.md` carry the module's
   guidance. It reads the fragment through the project interpreter and
   prints "run again after installing" when the module is not importable yet.
5. Prints the `wiring.urls` include line, the extras, the services the
   module needs, anything it requires that the project lacks, and the
   install + `make migrate` reminder. `karni add` never touches the network.
   The user installs. It refuses (`C315`) a module that conflicts with one
   the project has.

Settings then arrive via the entry-point fragment at the next process start,
and migrations apply with `make migrate`. Total project diff for a new module:
one dependency line, one `INSTALLED_APPS` entry, one optional include line.

## Taking a module out (`karni remove <x>`)

!!! warning "Experimental"
    `karni remove` is [experimental](stability.md#experimental-names).

`karni remove <x> [--dry-run] [--keep-tables]` reverses `karni add`: the
dependency, the apps, the middleware and context processors (any entry
inside the module's package, so a hand-added one goes too), the context
processors block once it is empty, the module's UI package in
`frontend/package.json`, the module's include in config/urls.py,
the kind it gave the project (a site+app goes back to an app) and
`.karni/modules/<x>.md`, then it refreshes the agent files. Adding and
removing a module gives back the project's files byte for byte.

It refuses (`C316`) while another added module requires it. It never drops
data. It counts the rows of each of the module's tables through `manage.py
karni_rows`, before it unwires anything:

```text
Its tables (nothing is dropped):
  karni_payments_payment (karni_payments.Payment): 12 rows
  karni_payments_refund (karni_payments.Refund): 0 rows
```

Django can drop a module's tables only while the module is in
`INSTALLED_APPS`, so while a table exists `karni remove` stops (`C319`) and
prints the command that drops them, for you to run deliberately. It prints no
"Changes:" block then, since it changes nothing (`--dry-run` shows both):

```bash
karni migrate karni_payments zero   # deletes the tables and their rows
karni remove payments               # then take the module out
```

`--keep-tables` takes the module out and leaves the tables in the database.
When the database does not answer, it says so and goes on, since unwiring
drops nothing. Last, it names the files of your own that still mention the
module, the settings in config/settings.py that still set its options, and
the step that uninstalls the package (`uv pip uninstall karni-<x>`, or
`docker compose build`). Features are not removed (`C318`): their setting,
or their key under `features:` in karni.yaml, turns them off.

## The module catalog

!!! warning "Experimental"
    The manifest format, the `karni.modules` entry point group,
    `karni.catalog`, `karni.testing.assert_module_manifest`, `karni modules`
    and `karni remove` are [experimental](stability.md#experimental-names).

Every module, and every option Karni ships built in (a **feature**), has a
manifest: what it is for, what it provides, the questions to ask before
turning it on, what it requires or conflicts with, the services it needs
and, for a module, the wiring `karni add` performs. An agent reads the whole
catalog without searching:

- `karni context` prints a `CATALOG:` line per module and feature, with
  whether the project has it and its purpose.
- `karni modules list [--json]` prints every entry, added or not, with its
  status and its questions. `karni modules show <name> [--json]` prints one
  entry in full.
- The app spec reads its module names, module options, feature names and
  social sign-in providers from the catalog, and `karni spec validate`
  checks what the listed modules and features require and conflict with
  (`C324`).

A module is **added** when its app is in the `# karni:apps` block,
**installed** when the project's interpreter has it, and **available**
otherwise. karni-cli bundles a copy of each manifest in Karni's repository,
so a module shows before it is installed. A third-party module joins the
catalog with its own manifest and entry point.

### Where a manifest lives

A module ships `karni.module.toml` inside its Python package, pinned as
package data, and names the package in the `karni.modules` entry point
group. `karni make module` writes both:

```toml
# pyproject.toml
[project.entry-points."karni.modules"]
payments = "karni_payments"

[tool.hatch.build.targets.wheel]
artifacts = ["karni_payments/AGENTS.fragment.md", "karni_payments/karni.module.toml"]
```

Karni's features have theirs in `karni/catalog/features/<name>.toml`.
`python -m karni.catalog` prints the manifests of the modules installed in
an environment, which is how a CLI outside the project's environment sees
them.

### An example

```toml
name = "payments"
kind = "module"
title = "Payments"
purpose = "Hosted checkout, refunds and signed webhooks for Stripe and Razorpay."
status = "stable"
use_when = ["payments", "checkout", "refunds", "taking card payments", "Stripe", "Razorpay"]
services = ["a Celery worker: webhook state changes run as tasks"]

[provides]
models = ["Payment", "Refund", "WebhookEvent"]
endpoints = ["/api/payments/", "/api/payments/checkout/", "/payments/webhook/<provider>/"]
ui = "@karni/payments-ui"

[provides.settings]
KARNI_PAYMENTS_PROVIDER = "string"
KARNI_PAYMENTS_CURRENCY = "string"

[[asks]]
question = "Which payment provider: Stripe or Razorpay?"
setting = "KARNI_PAYMENTS_PROVIDER"
options = ["stripe", "razorpay", "test"]
default = "stripe"

[wiring]
apps = ["karni_payments"]
settings = "karni_payments.conf:DEFAULTS"
urls = 'path("payments/", include("karni_payments.urls"))'

[wiring.extras]
stripe = "the Stripe provider"
```

A feature has no `wiring`. It names the setting that turns it on and its
extra instead:

```toml
name = "two_factor"
kind = "feature"
title = "Two-factor sign-in"
purpose = "TOTP codes from an authenticator app as a second sign-in step."
status = "stable"
use_when = ["two-factor sign-in", "2FA", "TOTP"]
switch = "KARNI_2FA"
extra = "karni[2fa]"

[provides]
settings = { KARNI_2FA = "boolean" }
```

### Every key

Top level:

| Key | For | Required | Takes |
|---|---|---|---|
| `name` | both | yes | the name `karni add` takes (`payments`), or the feature's key under `features:` in karni.yaml. Lowercase letters, digits and `_` |
| `kind` | both | yes | `module` or `feature` |
| `title` | both | yes | a short human name |
| `purpose` | both | yes | one line, at most 80 characters (`karni context` prints it) |
| `status` | both | yes | `stable` or `experimental` |
| `use_when` | both | yes | plain phrases of what someone asks for, e.g. `["payments", "checkout"]` |
| `requires` | both | no | modules or features that must be there too. A feature requires features only: Karni's core never depends on a module |
| `conflicts` | both | no | modules or features that cannot be there too |
| `services` | both | no | what it needs to run, in plain words: a worker, Redis, a provider account |
| `docs` | both | no | where to read more: a docs page, a README path or a URL |
| `distribution` | module | no | the PyPI name, `karni-<name>` by default |
| `switch` | feature | yes | the setting that turns it on (on while it holds a value) |
| `extra` | feature | no | the karni extra it needs, e.g. `karni[2fa]` |
| `in_spec` | feature | no | `false` when karni.yaml has no key for it yet (every built-in feature has one) |

`[provides]`, what it adds:

| Key | Takes |
|---|---|
| `models` | model class names. The module's tests check them against the app's models |
| `endpoints` | URL paths |
| `pages` | admin pages, templates or screens, in plain words |
| `settings` | setting name to its JSON type (`string`, `integer`, `boolean`, `array`, `object`, `null`) or a list of types. A module's `KARNI_<NAME>_*` settings are its options in karni.yaml, lowercased without the prefix. Credentials may be listed and are never options |
| `ui` | the npm package of its React components |

`[[asks]]`, the questions to settle before adding it, one table each:

| Key | Required | Takes |
|---|---|---|
| `question` | yes | the question, in plain words |
| `setting` | yes | the setting the answer goes to, one of `provides.settings` (or the switch), with `.key` for a key of a dict setting (`KARNI_TERMS.version`) |
| `options` | no | the answers to choose from. None: a free value |
| `default` | no | the answer when nobody says otherwise, one of `options` |
| `multiple` | no | `true` when the answer is a list of options |

For a module or a feature listed in karni.yaml, each ask whose answer the
spec does not set is one of the [questions](app-spec.md#questions) `karni
plan --questions` lists, in the manifest's order. Order the asks by how much
the answer matters.

`[wiring]`, modules only, what `karni add` writes and `karni remove` takes out:

| Key | Required | Takes |
|---|---|---|
| `apps` | yes | the entries of the `# karni:apps` block, the module's app first |
| `settings` | no | the settings fragment, `module:DEFAULTS`, which `karni_settings()` merges (no edit) |
| `middleware` | no | entries of the `# karni:middleware` block: a dotted path, or a table with `path`, `why` (a few words, printed) and `manual` (`true`: `karni add` prints it for you to add) |
| `context_processors` | no | entries of the `# karni:context_processors` block, written like `middleware` |
| `urls` | no | the `path(..., include(...))` line `karni add` prints for config/urls.py |
| `kind` | no | `"site"`: an app project becomes a site+app |
| `extras` | no | extra name to what it is for (`stripe = "the Stripe provider"`) |

### Checking a manifest

`karni.catalog.parse_text` checks a manifest and raises `ManifestError`
with every problem, each naming its key. A module's own suite checks its
manifest against the module in one call:

```python
from karni.testing import assert_module_manifest


def test_the_manifest_matches_the_module() -> None:
    assert_module_manifest("karni_payments")
```

It checks the format, the `karni.modules` entry point (once the module is
installed), that every listed setting is in the `DEFAULTS` fragment and
every `KARNI_<NAME>_*` key of it is listed, and that `provides.models` are
the app's models, and fails with [`E310`](errors.md#e310) listing each
mismatch. `karni make module` writes this test. An invalid manifest
in the catalog is reported by `karni modules list` as `C314` and left out.

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
- [ ] `karni.module.toml` with its `karni.modules` entry point, pinned as
      package data, checked by `assert_module_manifest`
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
| `karni-site` (`modules/karni-site/`) | the runtime of a public website (a site app from `karni make site` or `karni import design`): everything the client sees edited in the admin, with the template's text as the default (`{% editable %}` and `{% editable_image %}` blocks with history, `{% get_menu %}` menus in the design's own markup, the site's name, logo and contact details as `site`, redirects, page titles and descriptions) and an `editor` role for it. `{% ifactive %}` marks the current page in a menu around whatever markup the design uses, `{% csp_hash %}` and `{% csp_allow %}` let a design's inline scripts and other origins pass the Content-Security-Policy for that response only, its error views render the site's own 404 and 500 pages with the request and fall back to a plain page when one fails, and `{% karni_form %}` renders a public form (`karni make form`) that posts to the form's viewset without JavaScript and in place with it, under the enforced policy, with `notify_recipients` for its email. `{% karni_seo %}` writes each page's title, description, canonical link, share tags and the site's JSON-LD, `{% image %}` serves uploads through WebP copies at the size the page shows them, and it answers robots.txt and sitemap.xml. `karni check` runs SITE001, SITE002, SITE004, SITE005, SITE008 and SITE020, and `karni check --seo` renders every page (SITE010 to SITE018). Pillow is its `images` extra. No UI package. | `pip install karni-site[images] && karni add site` (`karni make site` and `karni make form` do this for you) |
| `karni-charts` (`modules/karni-charts/`) | experimental: saved charts, defined and previewed in the admin (a source resource, its axes, the filters it applies and the ones a viewer may add), served at `/api/charts/<slug>/data/` through the source's [aggregate action](aggregations.md) as the viewer, so the access is the source's. UI package: `@karni/charts-ui` (`SavedChart`). See [saved charts](charts.md) | `pip install karni-charts && karni add charts` |
| `karni-ai` (`modules/karni-ai/`) | experimental. Rows for any resource read from text, a web page or a PDF by a language model (Anthropic, OpenAI, or a test provider), validated against the resource's own schema and always previewed by Karni's import before a user commits them. Every call logged with its tokens and cost, monthly token budgets, a per-user rate limit, and URL fetching that never reaches the server's own network. `karni check` runs AI001 to AI005. UI package: `@karni/ai-ui`. [AI extraction](ai-extraction.md) | `pip install "karni-ai[anthropic]" && karni add ai` |
| `karni-impersonation` (`modules/karni-impersonation/`) | "log in as user" for support, done safely: an explicit `impersonate` permission (never implied by staff), no privilege escalation, a banner naming both identities with a one-click exit, a session record, every write attributed to both identities in `karni.audit`, a time limit and a hard block on deleting, exporting and payment changes. The threat model is in its README. UI package: `@karni/impersonation-ui` | `pip install karni-impersonation && karni add impersonation` |
| `karni-reports` (`modules/karni-reports/`), experimental | PDF reports of a row. A report is declared in `<app>/reports.py` (`@register` on a `Report` naming the model, the template and `get_context(obj)`). A Celery task renders the template with WeasyPrint and stores the file through Django's storage, cached by the template and a hash of the context, so a changed row or template gives a new file and an unchanged one is served again. `POST /api/reports/<report>/<id>/`, its `status/` and its `download/` retrieve the row through its model's own viewset first, so another user's row is a 404. It comes with a base print template, `manage.py karni_pregenerate`, the Generated reports admin with Regenerate, and `karni check` for a report without a viewset or a template. It needs Pango, a system library. UI package: `@karni/reports-ui`. See [Reports (PDF)](reports.md) | `pip install karni-reports && karni add reports` |
| `karni-storage` (`modules/karni-storage/`), experimental | files a row owns, kept in a private S3-compatible bucket (or a private directory in development) and downloaded only through the row's own viewset. `ProtectedFileField` and `ProtectedImageField` give the file as `<resource>/<id>/files/<field>/`, which redirects to a short-lived signed URL or streams the file. One setting picks the service (`aws`, `r2`, `minio`, `spaces`, `b2`, `gcs-interop`) and configures core's S3 backend. Direct uploads answer a presigned POST or PUT, and a confirm step checks the object before a row points at it. Thumbnails are made by a Celery task with core's thumbnailer. `karni check` runs STORE001 to STORE006. UI package: `@karni/storage-ui`. See [Protected files](storage.md) | `pip install "karni-storage[images]" && karni add storage` |

Each module's README is its reference (settings table, wiring, escape
hatches). `karni-approvals` is built on one core hook: every `BaseModel`
write sends [`karni.signals.pre_write`](models.md#write-interception), and a
receiver may defer it. Any module can use that hook the same way.
`karni-impersonation` is built on another, [`karni.vetoes`](api.md#vetoes).
That is a registry the API and admin gates consult after the access
declaration admitted an action. It also builds on `karni.audit`'s batches.
`karni-site` builds on `karni.security.extend_request_csp`, which adds
sources to one response's Content-Security-Policy from code that runs while
the response is built ([security headers](security.md#security-headers)).
It declares its `editor` role through the `karni.roles` entry point
([7c](#7c-optional-karniroles-roles-a-module-declares)) and ships its own
`admin.py`, whose pages open for the roles' grants. Its forms save through the
form viewset's own `create`, so a form adds no second write path.
[Public server-rendered pages](public-site.md) says what it gives a site.
