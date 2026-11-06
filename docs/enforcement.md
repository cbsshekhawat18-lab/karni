---
description: The rules Karni enforces at build time for backend and frontend code, the code each one carries, and the inline opt-out with a reason that each one accepts.
---

# Enforcement

Every rule fails a build. Nothing warns. Every rule has an explicit, inline
opt-out that requires a reason, because rules without escape hatches cause
forks, and a fork is worse than a duplicate.

Each enforced rule also has a stable agent-facing code (`K101`…`K205`) in
Karni's rule registry: `karni rules` lists them, `karni rules --explain
<code>` gives the rationale and fix, and `karni rules --check <file>` runs a
fast single-file subset of these checks. See [Karni for AI agents](agents.md).

## Backend rules (karni.testing)

Run in CI as `pytest --pyargs karni.testing.architecture`, and on every
`karni check` via the `karni.checks` entry points (`architecture`,
`duplication`). Only project code is scanned, meaning apps whose source lives
under the project root (`BASE_DIR` when the settings define it, else the parent
of the settings package, which is where a Karni scaffold keeps `config/`).
Installed packages (including Karni modules) are never scanned and must
pass these rules in their own CI. `query-scaling` needs a database,
so it runs only under pytest, never in `karni check`. The architecture suite
carries it, and `pytest
--pyargs karni.testing.performance` runs it alone.

| Rule id | Fails when | Fix |
|---|---|---|
| `model-base` | a concrete model inherits `django.db.models.Model` directly | inherit `karni.models.BaseModel` (or `BigIntBaseModel`, or compose the mixins) |
| `viewset-base` | a GenericViewSet subclass bypasses `BaseViewSet` | inherit `karni.api.BaseViewSet` |
| `viewset-access` | a `BaseViewSet` serving a model (`model`/`queryset` set, or routed) has no `access` (inherited declarations and an overridden `get_access()` count) | add `access = Access(read=..., write=...)`, or `Unscoped(reason=...)` |
| `access-override` | a class overrides `filter_queryset_for_user` | express the row rule in `access` (`Where(...)`), or opt out with the reason |
| `unpaginated-action` | an `@action` (or a view's `list`) serialises `many=True` (without `data=`) and never calls `paginate_queryset` / `paginated_response` / `get_paginated_response` | `return self.paginated_response(queryset)` |
| `query-scaling` | a routed project `BaseViewSet`'s `list`, `retrieve` or `aggregate` (with an [aggregation](aggregations.md), experimental) runs more queries with 12 rows than with 2 (an N+1). Needs a test database | let the serializer show the relation, or hint it with `select_related` / `prefetch_related` |
| `admin-convention` | a registered admin for a project model isn't a `KarniModelAdmin` | use `AdminMeta` on the model, or subclass `KarniModelAdmin` |
| `raw-sql` | `.raw()`, `cursor.execute()`, `RawSQL` outside `sql_allowed` dirs | move it under `*/sql/*`, or opt out |
| `http-client` | `requests`/`httpx`/`urllib.request` imported outside `http_allowed` | call providers from a `*/services/*` module |
| `redundant-serializer` | a Meta-only ModelSerializer identical to the generated one | delete it, since `BaseViewSet(model=X)` generates it |
| `audited-bulk-write` | `<AuditedModel>.objects…update()` or `.bulk_update()` in project code. Signals do not fire, so no change-history entry is written | save the instances, or opt out with the reason |
| `hand-written-tree` (experimental) | a project model has a `parent` (or `parent_*`) foreign key to itself and is not a `TreeModel` | inherit `karni.models.TreeModel` first and drop the field (see [tree models](models.md#tree-models)), or opt out with the reason |
| `duplicate` | ≥ `min_statements` structurally identical statements in two places | reuse the named Karni API, or extract one implementation |
| `opt-out-reason` | any opt-out marker without a reason | write the reason |

`model-base` and `query-scaling` (experimental) leave out a model over a
table or view another system owns: `class Karni: external = True` together
with `Meta.managed = False` on a plain `models.Model`. Without
`managed = False` the model still fails `model-base`, and `karni.E270` says
why. See [external tables, views and a second
database](models.md#external-tables-views-and-a-second-database).

Opt-out goes on the same line, the line above a class or method, or the line
above its first decorator. `opt-out-reason` itself cannot be suppressed:

```python
# karni: allow(raw-sql): aggregation too complex for the ORM, reviewed 2026-10
```

```python
class InvoiceViewSet(BaseViewSet):
    model = Invoice
    access = Access(read=Authenticated(), write=HasRole("billing"))

    # karni: allow(access-override): rows come from the subscription service
    def filter_queryset_for_user(self, queryset):
        return queryset.filter(account__in=subscriptions.visible_accounts(self.request.user))
```

The two access rules guard ADR 0001 Decision 2. `viewset-access` makes a
forgotten declaration a build failure. At runtime such a viewset already
denies every request, and opting out of the rule does not change that.
`access-override` makes widening the row policy visible: the hook receives
the access-scoped queryset, and only replacing it can widen it. An
overridden `get_queryset` needs no marker. It is wrapped, so the read scope
still applies to whatever it returns.

The two performance rules guard ADR 0001 Decision 3. `unpaginated-action` is
static (AST): a list-returning action must go through pagination, and
`self.paginated_response(qs)` is the one-line way. `many=True` with `data=` is
bulk *input* validation and is not flagged.

```python
@action(detail=False)
def recent(self, request):
    # karni: allow(unpaginated-action): at most 12 fixed rows, the UI needs one call
    return Response(BadgeSerializer(Badge.objects.featured()[:12], many=True).data)
```

`query-scaling` is the N+1 detector: for every routed project viewset it
seeds 2 then 12 rows with the automatic factories (an explicit
`<app>/factories.py` factory wins), as a requester holding every role and
owning every `Owned` path of the `read` predicate, and requires the same
query count (see [testing](testing.md#3-the-scaling-check)). Its opt-out goes
above the viewset class, like the other class rules:

```python
# karni: allow(query-scaling): one signed S3 URL per row, measured and bounded by the page
class AttachmentViewSet(BaseViewSet):
    ...
```

A viewset whose seeded rows the generated requester cannot see (a `Where`
rule, a traversal `Owned` path) is skipped with that reason, not passed.
Give the model an explicit factory that produces readable rows. Absolute
per-action query budgets (`raise` in tests) are not an architecture rule.
See [api](api.md#query-budgets).

Configuration is `KARNI_ARCHITECTURE` in settings (all keys optional):

```python
KARNI_ARCHITECTURE = {
    "skip_apps": [],                      # extra app labels to exclude
    "sql_allowed": ["*/sql/*", "*/migrations/*"],
    "http_allowed": ["*/services/*", "*/providers/*", "*/tests/*", "conftest.py"],
    "dup": {"min_statements": 8, "exclude": ["*/migrations/*"]},
}
```

## The check cache

!!! warning "Experimental"
    The check cache, `karni check --changed` and `--no-cache`, `manage.py
    karni_check --changed` and `--no-cache`, `.karni/local/check-cache.json`,
    `karni.testing.checkcache` and the setting `KARNI_CHECK_CACHE` are
    [experimental](stability.md#experimental-names).

On a large project `karni check` would read every file on every run. It keeps
the results of the checks that read files one by one in
`.karni/local/check-cache.json` (machine-local, ignored by git), under each
file's content hash, so an unchanged file is not read again. These checks use
it: the rules that parse the source (`raw-sql`, `http-client`,
`access-override`, `unpaginated-action`, `audited-bulk-write`) and the
duplication check's fingerprints, of the project and of Karni's own source.
ESLint keeps its own cache in `.karni/local/eslintcache`. The checks that read
the whole project always run: Django's system checks (the models, the
migrations, the URL routing), the external tables, the rules that inspect
classes, jscpd and every `karni.checks` hook of a module.

```sh
karni check                    # an unchanged file comes from the cache
karni check --changed          # only the files git reports as changed
karni check --changed main     # the files changed since main
karni check --no-cache         # read every file again
```

The backend says how much it reused: `check cache: 1459 of 1459 file results
reused`. The cache is ignored whole when another Karni, Django or Python
version wrote it, or other settings did (every `KARNI_*` setting,
`INSTALLED_APPS` and the installed check hooks are part of its fingerprint).
A rule whose other inputs changed (the audited models of `audited-bulk-write`)
drops its own entries.

`--changed` asks git for the files changed in the working tree and the index
against `HEAD` (against `REF` with `--changed REF`), plus the untracked files
git does not ignore. The file checks and ESLint read only those, and every
check reports only their findings, while the whole-project checks still run
in full. Outside a git repository, or with a ref git does not know, it stops
with [C581](errors.md#c581). A project whose karni predates the cache says so
with [C582](errors.md#c582).

`KARNI_CHECK_CACHE = False` turns the cache off, and a path (relative to the
project root) moves the file. A module's own `karni.checks` hook can cache
its per-file work too: `karni.testing.checkcache.active().per_file(name,
path, compute)`.

## Integer keys on a public resource

!!! warning "Experimental"
    `karni.W530` belongs to [integer keys](models.md#choosing-the-key-type),
    which are [experimental](stability.md#experimental-names).

`karni check` (and every `manage.py check`) warns with `karni.W530` for a
routed `BaseViewSet` whose model has an integer primary key
(`BigIntBaseModel`, an `AutoField`), whose detail route looks rows up by that
key, and whose `read` access lets anonymous callers in (`Public()`, alone or
in an `|`). Integer ids are sequential, so a visitor learns how many rows
there are and can walk `/readings/1/`, `/readings/2/`, ..., including rows no
list links to. It is a warning: `karni check` prints it and passes, and
`karni check --deploy` fails on it.

The fix is a UUID key (`BaseModel`) or a slug lookup
(`lookup_field = "slug"`). When the ids may be public, say why above the
viewset class, with the same marker as the rules above:

```python
# karni: allow(public-integer-key): order numbers are printed on every receipt
class OrderViewSet(BaseViewSet):
    model = Order
    access = Access(read=Public(), write=HasRole("staff"))
```

A marker without a reason does not silence it. `'karni.W530'` in
`SILENCED_SYSTEM_CHECKS` silences it for the whole project.

## Suggestions

Experimental. Rules fail a build. Suggestions never do. `karni check`,
`karni doctor` and `karni suggest` end with a compact block of what Karni
could do that the project does by hand, each with its file and line and the
exact command or change. A suggestion never changes an exit code.

```text
suggestions (2), they never fail the run:
  [SUG002] shop/models.py:14: Article.body_markdown is a TextField that holds markdown: the API publishes it as plain text, so @karni/ui shows the raw markup.
      fix: use karni.fields.MarkdownField: body_markdown = MarkdownField(...), then karni makemigrations (no data changes, it is a TextField in the database).
  [SUG005] config/settings.py:41: the module charts is added, and nothing in the project imports it, renders its templates, includes its URLs beyond `karni add` or changes one of its settings.
      fix: take it out with karni remove charts (it never drops data: see `karni remove --help`), or silence this with `# karni: allow(suggest-unused-module): <reason>` on its line in config/settings.py.
  Silence one with `# karni: allow(<rule>): <reason>`, see `karni explain <code>`.
```

Every suggestion has a stable code in the `SUG` series. The prefix has three
letters because a single letter is the registry's error or warning.
`karni explain SUG001` prints the entry offline, and the
[error codes](errors.md#suggestions-sug) list them all.

| Code | Silencing rule | What it points out | The fix |
|---|---|---|---|
| `SUG001` | `suggest-tree-model` | a model has a foreign key to itself named like a parent (`category_parent`) and is not a `TreeModel`. The `hand-written-tree` rule already fails on `parent` and `parent_*`, so this covers the other names | inherit `karni.models.TreeModel` first and drop the field (see [tree models](models.md#tree-models)) |
| `SUG002` | `suggest-markdown` | a `TextField` named `*_markdown` or `*_md`, or whose help text says markdown | use `karni.fields.MarkdownField` (see [fields](fields.md#markdownfield)) and run `karni makemigrations`. No data changes |
| `SUG003` | `suggest-aggregate` | two or more raw SQL queries with `GROUP BY` that opt out of the `raw-sql` rule | declare `class Karni: aggregate = {...}` on the model (see [aggregations](aggregations.md)) |
| `SUG004` | `suggest-taxonomy` | three or more models have a many-to-many to the same tree model and declare no taxonomy for it | declare `class Karni: taxonomies = {"region": "geo.Region"}` on each (see [taxonomies](models.md#taxonomies)) |
| `SUG005` | `suggest-unused-module` | an added module that no project file imports or renders, whose URLs only `karni add` wrote and none of whose settings differs from its default. A module another added module requires is left out | `karni remove <name>`. It never drops data |
| `SUG006` | `suggest-add-module` | a phrase of a module's `use_when` list appears in `karni.yaml` or the README while the module is not added (not in `config/settings.py` or `pyproject.toml`) and `karni.yaml` does not list it. In the README only a phrase of two words or more counts, and a line that already says `karni add <name>` or names `karni-<name>` is left out | `karni modules show <name>`, then `karni add <name>` |
| `SUG007` | `suggest-sync-spec` | `karni plan` is not empty: the project drifted from `karni.yaml` | `karni build` to bring the project to the spec, or `karni spec export -o karni.yaml --force` to take the code's side |

Thresholds: SUG003 needs two queries, SUG004 three models. A suggestion that
fires too early is silenced, not tuned.

**Silencing.** The comment form of the rules above, with the rule name from
the table and a reason, on the line, the line above or (for a model) the
class line:

```python
class Region(BaseModel):
    # karni: allow(suggest-tree-model): the rows are a flat list, the parent is a label
    category_parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
```

SUG005 is silenced on the module's line in the `karni:apps` block of
`config/settings.py`, SUG007 on the first line of `karni.yaml`, SUG006 on the
matching line of `karni.yaml` or the README (in a README as
`<!-- karni: allow(suggest-add-module): <reason> -->`). For SUG003 and SUG004
a marker on one query or model leaves that one out of the count. A marker
without a reason does not silence a suggestion, and never fails the run:
the suggestion stays and says so. A line may carry several markers, each
read (`# karni: allow(raw-sql): ... # karni: allow(suggest-aggregate): ...`).

**Off for a project.** `KARNI_SUGGESTIONS = False` in `config/settings.py`
turns every suggestion off. `karni check` and `karni doctor` then print
nothing about them. The CLI reads that plain line without starting Django.

**For agents.** `karni suggest --json` prints `{version, enabled,
suggestions: [{code, rule, file, line, message, fix, command}], problems}`.
`problems` lists why the project's own suggestions are missing (its
`manage.py karni_suggest` could not run, C781): when it is not empty, an empty
`suggestions` is not a clean project. `command`
is the exact command when the fix is one, else `null`, and `line` is `null`
for a whole file. The shape is versioned (`version: 1`) and published as
[`karni-suggestions.schema.json`](assets/karni-suggestions.schema.json),
generated by `python -m karni_cli.suggest`, with a test that fails when it
is stale. The agent rule K004 tells an agent to read the suggestions that
`karni check` ends with.

`karni check` merges two sources into one block: the project's own detectors
(SUG001 to SUG005, `manage.py karni_check`, which write their findings to
`.karni/local/suggestions.json` for the CLI) and the ones that read
`karni.yaml` and the README (SUG006 and SUG007). `manage.py karni_check`
alone prints the first group. When the project runs in a docker compose
service the CLI cannot hand the file over, so the backend prints its block
and the CLI prints the rest as a second one.

## Frontend rules

`karni check` also runs the frontend's ESLint (the scaffold's
`eslint.config.js` with the `@karni/ui` preset below, warnings counted as
failures) and jscpd (pinned in the scaffold's frontend devDependencies,
configured by `frontend/.jscpd.json`). Duplication above the threshold
fails with the full clone report. Opt-out:
`// jscpd:ignore-start -- <reason>` … `// jscpd:ignore-end`. A bare
`ignore-start` without a reason fails. jscpd compares the project's files
with each other: a `@karni/ui` component copied into the project is not a
clone of anything in `src/`, so it is the ESLint rules (`no-raw-elements`,
`no-deep-imports`) that catch it, and a reasoned disable directive is the
deliberate way past them. Review those directives, not the clone report.

The `@karni/ui` ESLint plugin (`@karni/ui/eslint-plugin`, flat config only,
ESLint >= 9, via `configs.recommended`) ships four rules, all `"error"`:

| Rule | Fails when | Fix |
|---|---|---|
| `karni/no-raw-elements` | raw `<table>/<form>/<input>/<select>/<textarea>/<details>` JSX outside the UI package | compose `ResourceTable` (a resource) or `DataTable` / `ComparisonTable` (computed rows), `Accordion` for `<details>`, `ResourceForm`/`Input`/… |
| `karni/max-page-lines` | a file under `**/pages/**` exceeds 50 physical lines (option `maxLines`) | use the components' props (on a dashboard the [page blocks](ui.md#page-blocks-experimental)), and move logic into hooks |
| `karni/no-deep-imports` | any import from `@karni/ui/dist/*` or `@karni/ui/src/*` | import the public barrel `@karni/ui` |
| `karni/no-direct-http` | `fetch`/`axios`/`XMLHttpRequest`/`new WebSocket` outside `allowPatterns` (default `**/api/**`) | use the generated typed hooks / `KarniClient` |

The preset also turns `karni/no-direct-http` off for `**/*.test.*`,
`**/mocks/**` and vitest setup files, sets
`linterOptions.reportUnusedDisableDirectives: "error"`, and requires a
description on every disable comment
(`@eslint-community/eslint-comments/require-description`). Opt-out is
ESLint's own, with the reason mandatory:
`// eslint-disable-next-line karni/no-direct-http -- <reason>`. A bare
disable, or an unused one, is itself an error.

Component roles: every top-level component claims a semantic role via
`registerComponentRole(role, name)`. The `role` argument must be a string
literal, because `generate-manifest.mjs` statically scans the call sites,
fails the build on duplicate roles (and on non-literal roles), and emits the
`"roles"` map into `dist/manifest.json`. At runtime, re-registering the same
role + name is idempotent. A different name throws at import time (vitest and
prod builds fail), except under the Vite dev server's HMR, where it replaces
and logs a `console.error` instead of killing the app. Replacing on purpose:
`registerComponentRole(role, name, { replace: true, reason: "..." })`. An
empty reason throws. The registry (`getRoleRegistry()`) reflects imported
modules only.
