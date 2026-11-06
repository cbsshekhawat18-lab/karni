---
description: "The Karni app spec, karni.yaml (experimental): one small file that describes an app in the terms karni make, karni add and the settings use, with karni spec validate, karni spec export, karni plan and its questions, karni build, recipes, the MCP tools and published JSON Schemas."
---

# The app spec: `karni.yaml`

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.yaml` format, `karni spec validate`, `karni spec export`,
    `karni plan`, `karni plan --questions`, `karni spec answer`, `karni
    build`, `manage.py karni_facts`, `manage.py karni_rows`, `manage.py
    karni_makemigrations`, `karni.facts`, the `karni_cli.spec` and
    `karni_cli.builder` packages, `.karni/build.json`, [recipes](#recipes)
    (`karni recipes`, the recipe format, the `karni.recipes` entry points,
    `karni_cli.recipes`, the [built-in recipes](recipes/index.md) and `karni
    new --recipe`), [the MCP tools](#mcp-tools) of the flow
    (`karni_cli.agent_tools`) and the seven JSON Schemas. They may change in
    a minor release, and each change is in the CHANGELOG. The error codes
    keep their meaning.

A spec is one small file that describes a Karni app: its apps and entities,
roles, built-in features, modules, pages and menu. An AI agent turns a one-line
request into a spec, and Karni turns the spec into code without a language
model. This release reads and checks a spec (`karni spec validate`),
writes the spec of an existing project (`karni spec export`), shows what
would change to make the project match a spec ([`karni
plan`](#karni-plan)), lists the few [questions](#questions) to ask the user
first, and makes the change ([`karni build`](#karni-build)), without
touching the code written by hand. A spec starts from a [recipe](#recipes)
or from the blank start, and an agent runs the whole flow through `/new-app`
([the /new-app flow](agents.md#agents-the-new-app-flow)) or [the MCP
tools](#mcp-tools).

The spec describes only what `karni make`, `karni add` and the settings can
already do. Each key maps to one of them. Anything it cannot express stays
in the project's own code.

```yaml
# yaml-language-server: $schema=https://cbsshekhawat18-lab.github.io/karni/assets/karni-spec.schema.json
version: 1
app:
  name: Harbour Yoga
  kind: site+app
  recipe: booking
modules:
  payments:
    provider: stripe
features:
  two_factor: true
  email_code_login: true
  social_login: [google, apple]
  terms: {version: "2026-11", url: /terms/}
roles:
  staff: {name: Staff, system: true, grants: {"*": all}}
  instructor:
    name: Instructor
    grants:
      classes.session: own:instructor
      classes.booking: custom:taught_by
  member: {name: Member, default: true, grants: {classes.booking: own}}
apps:
  classes:
    entities:
      Studio:
        fields: {name: "str:120", slug: "slug:name", address: "text?"}
        key: slug
        search: [name]
        access: {read: public, write: "role:staff"}
      Session:
        fields:
          studio: fk:Studio
          instructor: fk:User
          title: "str:200"
          starts_at: datetime
          capacity: int
          price: "money:EUR"
        owner: instructor
        order: starts_at
        audit: true
        access: {read: public, write: ["role:staff", "owned:instructor"]}
      Booking:
        fields:
          session: fk:Session
          member: fk:User
          status: "state:pending>paid|pending>cancelled|paid>refunded"
          note: "text?"
        owner: member
        audit: true
        groups: {Booking: [session, member, status], Notes: [note]}
        access:
          read: ["owned:member", "owned:session__instructor", "role:staff"]
          write: owned:member
pages:
  - home: dashboard
  - Session: [list, detail, form]
  - Booking: [list, detail]
seed: {Studio: 3, Session: 40, Booking: 200}
x-notes: kept and ignored
```

Validate it:

```sh
karni spec validate                 # karni.yaml in the project root (or here)
karni spec validate --spec other.yaml --json
```

## Editors and agents: the JSON Schema

The format is published as a JSON Schema, generated from the code:
[`karni-spec.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-spec.schema.json)
(in the repository, `docs/assets/karni-spec.schema.json`). An editor with
the YAML language server (VS Code's YAML extension, and editors built on it)
completes and checks keys as you type when the file starts with this line,
which `karni spec export` writes:

```yaml
# yaml-language-server: $schema=https://cbsshekhawat18-lab.github.io/karni/assets/karni-spec.schema.json
```

An agent can read the schema to know every key and its type. The schema
checks the shape (keys, types, required keys). `karni spec validate`
checks the same shape and also what the values mean (field types, names,
references), so run it before you trust a spec. A test fails when the
published file differs from the code: regenerate it with
`python -m karni_cli.spec.schema > docs/assets/karni-spec.schema.json`.

## Rules of the format

- `version: 1` is required. The version moves only for a breaking change of
  the format, and a new optional key never changes what an old file means.
- Unknown keys are errors (`C212`). A key that starts with `x-` is allowed at
  every level, kept in the file and ignored: use it for notes of your own.
- Values are never coerced. A list where a text is expected is an error.
  Quote a value YAML would read as a date, a number or `true`, and inside
  `{...}` or `[...]` quote every value that holds a colon: `{name: "str:120"}`.

## Every key

### `app`

| Key | Takes | Maps to |
|---|---|---|
| `name` | text, required | `karni new "<name>"` |
| `kind` | `site`, `app` (default) or `site+app` | `karni new --kind` |
| `recipe` | text | the recipe the spec started from, for the record only |
| `api_version` | a version name such as `v1` (lower case letters, digits and `-`, at most 16 characters). Experimental | `KARNI_API_VERSION`: the API is mounted at `/api/v1/`, with a document and a client per version ([API versions](api.md#api-versions)) |

### `modules`

Each key is a module `karni add <name>` installs, one of the modules of
[the module catalog](modules.md#the-module-catalog) (`karni modules list`):
Karni's `ai`, `approvals`, `charts`, `impersonation`, `payments`, `reports`, `site` and
`storage`, and any module installed next to karni-cli that ships a manifest. The value is a
mapping of
the module's options, or nothing. An option is one of the module's own
settings its manifest lists, lowercased and without its prefix, with the
type the manifest gives it: `payments: {provider: stripe}` is
`KARNI_PAYMENTS_PROVIDER = "stripe"`. Credentials such as
`STRIPE_SECRET_KEY` are never options: they stay in `.env`, and so do
`ai`'s key and model name (`ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`, or the
`OPENAI_*` pair). A kind with a site (`site`, `site+app`) has the `site`
module without listing it. What a
listed module or feature requires must be listed too, and two that conflict
cannot both be (`C324`).

### `features`

The keys are the built-in features of the module catalog that karni.yaml
takes (`karni modules show <name>` prints each one's questions).

| Key | Takes | Setting |
|---|---|---|
| `two_factor` | `true` / `false` | `KARNI_2FA` (needs `karni[2fa]`) |
| `email_code_login` | `true` / `false` | `KARNI_EMAIL_OTP`, [sign-in with a code](accounts.md#sign-in-with-a-code-sent-by-email) |
| `social_login` | `google`, `microsoft`, `apple`, one or a list | `KARNI_SOCIAL_TOKEN_PROVIDERS`, [sign-in with an ID token](accounts.md#sign-in-with-an-id-token-google-microsoft-apple). The spec names the providers. Their client ids stay in settings or `.env` |
| `terms` | `{version, url}`, plus `required`, `paths`, `exempt` | `KARNI_TERMS`, [terms acceptance](accounts.md#terms-acceptance) |
| `user_grants` | `true` / `false` | `KARNI_USER_GRANTS`, [per-user grants](accounts.md#per-user-grants). The grants themselves are data, written in the admin or the API |
| `api_cache` | `true` / `false`, or `{ttl: <seconds>}` | `KARNI_API_CACHE`, and `KARNI_API_CACHE_TTL` with a `ttl`, [response caching](api.md#response-caching). `true` keeps the default lifetime (300 seconds) |

`api_cache` left out (or `false`) writes no line in the settings block, so
`KARNI_API_CACHE` follows the environment: a project may cache in production
only, with `KARNI_API_CACHE=true` in its `.env`. An entity's `cache:` applies
whenever caching is on, from the spec or from the environment.

### `roles`

`roles` is `KARNI_ROLES` ([roles as data](accounts.md#roles-as-data)). A
spec without `roles` has Karni's shipped roles: `staff`, `user` and
`customer`.

| Key | Takes | Maps to |
|---|---|---|
| `name` | text | the role's name (default: from the slug) |
| `description` | text | the role's description |
| `system` | `true` / `false` | a system role |
| `default` | `true` / `false` | listed in `KARNI_ACCOUNTS_DEFAULT_ROLES`: every self-registered user gets it |
| `grants` | pattern to scope | the role's grants |

A grant pattern is `"*"`, `app.entity` (every action), or
`app.entity:action` with `view`, `add`, `change` or `delete`, with `*` for a
part (`classes.*`). The entity part is matched without regard to case, so
`classes.session` and `classes.Session` agree. A pattern may also name a
model of a module the spec adds (`karni_payments.payment:view`).

The scopes are Karni's own:

| Scope | Rows |
|---|---|
| `all` | every row |
| `own` | rows whose owner field (the entity's `owner`, else `created_by`) is the user |
| `own:<field>` | the same as `own`, written with the owner field it uses. The field must be the entity's `owner` (`C234`) |
| `related:<key>` | rows whose scope path `<key>` (the entity's `scope_paths`) equals the user's attribute `<key>` |
| `custom:<name>` | the rows a scope registered with `register_scope(name, fn)` returns |
| `tree:<path>` | rows whose `<path>` is a node the user holds or a node below it ([the tree scope](accounts.md#the-tree-scope), experimental). The path follows the entity's relation fields to an entity with `tree: true` or `tree: ordered` (`C620`) |

`related:` takes a scope path key, not a path. For rows reached through a
relation to the user (the bookings of an instructor's sessions), name the
path in the entity's access: `owned:session__instructor`.

### `apps` and their entities

`apps` maps an app label (snake_case) to its `entities`. An entity is a
model on `BaseModel` (PascalCase), with its viewset.

| Key | Takes | Maps to |
|---|---|---|
| `fields` | name to type, or to `{type, was}` | `karni make model <Entity> name:type ...` |
| `key` | a field | `karni make model --key` (`Karni.import_key`) |
| `help` | a sentence | `Karni.help`: the line the admin shows at the top of the model's list and form. `karni plan` shows it and `karni spec export` reads it back |
| `search` | a field or a list | `karni make model --search` (the viewset's `search_fields`). `karni build` also writes `search = SearchField(sources=[...])` when every name is a field of the entity, so `?search=` reads an index (`karni.W967`) |
| `global_search` | `true`, or `{fields, title, subtitle, weight}` | `Karni.search`, [search across models](global-search.md) (experimental). `fields` defaults to `search` |
| `owner` | a relation to the user, or a path (`workspace__members`) | `Karni.owner_field`, the `own` scope's field |
| `audit` | `true`, or a list of fields | `Karni.audit`, [change history](change-history.md). `karni build` writes a required fk of an audited or financial entity (one with money) as `on_delete=models.PROTECT` (`karni.W965`) |
| `groups` | title to fields | `Karni.field_groups`: sections of the React form and detail page, fieldsets of the admin (experimental) |
| `column_sets` | name to fields | `Karni.column_sets`: column presets of the React table (experimental) |
| `order` | a field or a list, `-` for descending | `karni make model --order` (`Meta.ordering`) |
| `scope_paths` | key to lookup path | `Karni.scope_paths`, for the `related:<key>` scope |
| `access` | `{read, write, create}`, or `code` | the viewset's `access` |
| `pk` | `uuid` or `bigint` | `karni make model --pk`: `BaseModel` or `BigIntBaseModel` (default: the project's `KARNI_PK`) |
| `external` | `true` / `false` | `karni make model --external`: `Meta.managed = False`, `Karni.external` |
| `table` | `table` or `schema.table` | `karni make model --table` (`Meta.db_table`), with `external` only |
| `writable` | `true` / `false` | `Karni.writable`, with `external` only |
| `database` | an alias of `DATABASES` | `Karni.database` (default: `default`) |
| `tree` | `true`, `ordered` or `false` | a [tree model](models.md#tree-models): `TreeModel` (`true`) or `OrderedTreeModel` (`ordered`), listed before the base |
| `taxonomies` | key to a tree entity | `Karni.taxonomies`, [taxonomy tagging](models.md#taxonomies): a many-to-many per key, its filters, facets and the `tree:<key>` scope |
| `aggregate` | `{group_by, values, metrics}` | `Karni.aggregate`, the [aggregate action](aggregations.md) (experimental) |
| `cache` | seconds, or `false` | the viewset's [response caching](api.md#response-caching): `cache = Cache(ttl=<seconds>)`, or `cache = Uncached(reason="spec")` for `false` (default: `KARNI_API_CACHE_TTL`) |
| `was` | the entity's old name | a rename that keeps the table and its rows (`karni plan`) |

Field types are exactly `karni make model`'s syntax, checked by its own
parser and renderer, so the spec and the generator can never disagree:
`str[:len]`, `text`, `int`, `float`, `decimal[:max:places]`, `bool`, `date`,
`datetime`, `url`, `file`, `image`, `uuid`, `choice:a|b`, `fk:Model`,
`m2m:Model`, `o2o:Model`, `money[:CUR]`, `percent[:min:max]`, `quantity`,
`email[:unique]`, `slug[:source]`, `phone`, `country`, `currency`,
`markdown` (a `MarkdownField`, experimental),
`json[:queried]`, `array:str[:len]`, `state:<a>><b>|...` (a `StateField`,
written as `karni make form --states` takes it), `daterange`,
`datetimerange` and `capacity[:total]`, with a trailing `?` for optional.
See [the karni command](cli.md) for what each one generates.
`file:protected` and `image:protected` are a file only the row's readers may
download ([protected files](storage.md)): they need `modules: {storage: ...}`
(`C720`).

A relation points at an entity of the same app (`fk:Studio`), of another app
(`fk:shop.Product`), at the user (`fk:User`), at itself (`fk:self`), or at a
model of a module the spec adds (`fk:karni_payments.Payment`). A model of the
project outside the spec cannot be named.

A field written as a mapping says what it was called before:
`title: {type: "str:200", was: name}` is the field `title`, renamed from
`name`, and its column keeps its values. The short form `title: "str:200"`
and the mapping form without `was` mean the same.

`pk`, `external`, `table`, `writable` and `database` are the
[key type](models.md#choosing-the-key-type) and the
[external tables and second databases](models.md#external-tables-views-and-a-second-database)
of the models page. An external entity needs `table`, takes no `pk` (the
table's own primary key column is the key) and no seed count (`C251`).
`database` must be an alias of the project's `DATABASES` (`C252`, which
`karni plan` checks: `karni spec validate` cannot read the settings), and a
relation between entities on different databases is refused (`C253`): the
user and the modules' models are on `default`. A managed entity on another
database is built without the audit users, whose relations would point at
`default`.

`cache` takes how many seconds a cached response of the entity lives
(`cache: 60`), or `false` to never cache it (`C520` for any other value).
Karni clears a cached response when it sees a write to a table the response
reads, and it never sees the writes another system makes. So with
`api_cache` on, an entity that reads an external table, a table on another
database, or an external entity it can reach through `?expand=` (two levels
deep) needs a `cache` of its own, which says how stale a response may be
(`C521`). `karni check` refuses the same viewset in the project.

`aggregate` says what [`GET <resource>/aggregate/`](aggregations.md)
(experimental) may group by and sum, and `karni build` writes it as `class
Karni: aggregate` in the entity's Karni-owned base:

```yaml
Session:
  fields: {studio: fk:Studio, starts_at: datetime, price: "money:EUR"}
  aggregate:
    group_by: [studio, studio__name, "starts_at:month"]
    values: [price]
    metrics: [count, sum, avg]
```

`group_by` takes fields and paths through relations, with `:year`,
`:quarter` or `:month` after a date or datetime field, `values` the fields a
metric reads, and `metrics` defaults to all six. Changing it needs no
migration. Expressions such as `TextNumber` stay in the project's own code:
`karni spec export` leaves out an aggregate that has them and says so.

### Trees

!!! warning "Experimental"
    The `tree` key is experimental, like the
    [tree models](models.md#tree-models) it builds.

`tree: true` makes the entity a hierarchy: `karni build` writes its model
base as `class Region(TreeModel, BaseModel)`, which adds a `parent` field,
the tree queries and the tree endpoints of the API. `tree: ordered` writes
`OrderedTreeModel` instead, which also adds `position`, the order of a
node among its siblings. The entity does not declare `parent` or
`position` itself (`C460`), and an external entity cannot be a tree,
because Karni never adds a column to a table another system owns (`C460`).
`order`, `search`, `key`, `audit` and `groups` may name `parent`, and
`position` on an ordered tree:

```yaml
Region: {fields: {name: str}, tree: true, search: name}
Category:
  fields: {name: str}
  tree: ordered
  order: [position]
```

A relation to a tree is an ordinary field (`fk:Region`, `m2m:Category`).
`karni spec export` writes `tree` for a model on `TreeModel` or
`OrderedTreeModel`. In `karni plan`, making an entity a tree or flat again is
a risky change, and so is `ordered` back to `true`, which drops `position`.

`groups` and `column_sets` are experimental. `karni build` writes `groups`
as the model's `Karni.field_groups`: sections of ResourceForm and
ResourceDetail and fieldsets of the admin, in the order written, and a field
left out of every group goes in a last group, Other. `column_sets` become
`Karni.column_sets`: the presets of ResourceTable's column set menu, where the
set named `default` shows first. A group names fields of the entity, each
field in one group (`C237`). A set names fields of the entity or `id`,
`created_at` and `updated_at`, each once (`C680`), under a snake_case name
(`C681`). Both lay out a model with many fields
([field groups and column sets](ui.md#field-groups-and-column-sets-experimental)):

```yaml
      Product:
        fields:
          name: "str:200"
          summary: "markdown?"
          price: "money:EUR"
          cost: "money:EUR"
        groups: {Overview: [name, summary], Financials: [price, cost]}
        column_sets: {default: [name, price], financial: [name, price, cost]}
```

To show the groups as tabs, set `field_group_layout = "tabs"` in the
project's subclass: `class Karni(karni.Product.Karni)`.

### Taxonomies

!!! warning "Experimental"
    The `taxonomies` key is experimental, like the
    [taxonomies](models.md#taxonomies) it builds.

`taxonomies` tags an entity to tree entities: each key becomes a
many-to-many of that name, with the list filters `?<key>=` and
`?<key>_descendants=`, the `facets/` counts and the `tree:<key>` scope.
`karni build` writes `class Karni: taxonomies` into the entity's model base,
each target as `app_label.Name`, and the field comes from it:

```yaml
Region: {fields: {name: str}, tree: true}
Category: {fields: {name: str}, tree: ordered}
Product:
  fields: {name: str}
  taxonomies: {region: Region, category: Category}
```

Each target is a tree entity of the spec, by name or `app.Name` (`C701`). A
key is a field name the entity can take (`C700`). A field of the same name
is adopted only when it is an `m2m` to the same tree (`C702`), and an
external entity takes no taxonomies (`C703`). A role grant's `tree:<path>`
may follow a taxonomy key (`tree:region`). `karni spec export` writes the
taxonomies back from the model facts. In `karni plan` a taxonomy added writes
a migration, and a taxonomy removed or pointed at another tree is a risky
change: its tags go with its table.

### Access

`access` maps onto Karni's [`Access`](api.md#access-control). `read`,
`write` and `create` each take one of these, or a list of them, any of which
admits:

| In the spec | In the viewset |
|---|---|
| `public` | `Public()` |
| `authenticated` | `Authenticated()` |
| `granted` | `Granted()`: what the roles' grants allow |
| `role:<slug>` | `HasRole("<slug>")`, a role the spec declares (`C232`) |
| `owned:<field>` | `Owned("<field>")`, a relation or a path that ends at the user (`C240`) |
| a list | the items joined with `\|` |

`read` and `write` default to `granted`, and `create` to `write`. An entity
without `access` has `Granted()`, the default of `karni make viewset`. The
shapes the `--access` presets make:

| `--access` | In the spec |
|---|---|
| `granted` (the default) | no `access` |
| `authenticated` | `{read: authenticated, write: authenticated}` |
| `public-read[:<role>]` | `{read: public, write: "role:<role>"}` (`staff` by default) |
| `public-create[:<role>]` | `{read: "role:<role>", write: "role:<role>", create: public}` |
| `owned:<field>` | `{read: "owned:<field>", write: "owned:<field>"}` |
| `staff`, `role:<name>` | `{read: "role:<name>", write: "role:<name>"}` |

`access: code` is the escape hatch: Karni writes no access line, and the
project declares its own `Access(...)` with `Where`, `Can`, `&` or a
computed `get_access()`.

### `pages`

`pages` lists `karni make page` in navigation order. Each entry is one key:

| Entry | Pages |
|---|---|
| `- Session: [list, detail, form]` | the entity's list at `/sessions`, detail at `/sessions/$id`, form at `/sessions/new` and `/sessions/$id/edit` |
| `- Session: [list, {detail: {related: [Booking]}}]` | the same, with a related tab on the detail page (below) |
| `- home: dashboard` | the scaffold's home page at `/`, the staff dashboard |
| `- overview: dashboard` | `karni make page overview --kind dashboard`: a page of charts at `/overview` (below) |
| `- about: blank` | `karni make page about`: a bare page at `/about` |
| `- login: login` | `karni make page login --kind login` |
| `- reports: code` | a page of the project's own at `/reports`: `karni build` leaves it alone |

Two pages may not share a route (`C242`).

### `navigation`

!!! warning "Experimental"
    The `navigation` key is experimental, like the
    [navigation from data](navigation.md) it writes.

`navigation` is the menu: `karni build` writes it to `KARNI_NAVIGATION` in
the settings block, and `GET /api/navigation/` gives each user the entries
their grants open. Without it, the spec writes no menu.

`navigation: true` lists every page of `pages` that has a route of its own,
in the order of `pages`: an entity's list page, the dashboard and each named
page. A sign-in page and an entity without a `list` page are left out. A
list says the order and the groups:

```yaml
navigation:
  - home                                   # a page of pages, by its key
  - Catalog: [Product, Category]           # a group: a label and its entries
  - Region: {icon: map}                    # a page with its options
  - Admin: {icon: settings, items: [reports], requires: "shop.*:change"}
```

| Entry | Means |
|---|---|
| `- <page>` | the page whose key in `pages` is `<page>` (`Product`, `shop.Product`, `home`) |
| `- <page>: {label, icon, requires}` | the page, with its label, icon or requirement replaced |
| `- <label>: [entries]` | a group: a label that names no page, and its entries |
| `- <label>: {items, icon, requires}` | a group with an icon or a requirement |

Each page's requirement comes from its access, the way the API reads it:

| The entity's `read` | The entry requires |
|---|---|
| `public` among them | `public` |
| `authenticated` or `owned:<field>` among them | `authenticated` |
| `granted`, `role:<slug>`, or `access: code` | the entity's view permission, `shop.product:view` |

A role opens the entry through its grants, as it opens the API: give the role
the view grant, or write `requires`. A named page requires `authenticated`,
and a sign-in page `public`. A group requires `public` when one of its
entries does, else `authenticated`. Labels come from the page: `Products` for
`Product`'s list, `Home` for `home`.

| Code | Problem |
|---|---|
| [C640](errors.md#c640) | an entry names a page `pages` does not have, or an entity without a list page |
| [C641](errors.md#c641) | an entry that is not valid: a page listed twice, a group without entries, an icon that is not a name |
| [C642](errors.md#c642) | a `requires` that is not valid, or names an entity the spec does not have |

`karni plan` shows the menu in the pages area as the setting it writes,
`+ KARNI_NAVIGATION: Home /, Catalog (Products /products, Categories /categories)`,
and `karni spec export` writes `navigation` from a `KARNI_NAVIGATION` list,
each item as the page whose route it links to. A menu the spec cannot say (a
route no page has, `KARNI_NAVIGATION = "db"`) is listed and stays in the
settings.

#### Related tabs and dashboard pages

!!! warning "Experimental"
    A detail page's `related` and a dashboard page other than `home` are
    [experimental](stability.md#experimental-names), like the
    [page blocks](ui.md#page-blocks-experimental) they compose.

A detail page written as `{detail: {related: [...]}}` shows a tab per
related entity, each a table of that entity's rows filtered to the record
(ResourceDetail's `related`, `karni make page --kind detail --related`):

```yaml
pages:
  - Session:
      - list
      - detail: {related: [Booking]}
      - form
```

Each name is an entity with a fk to the page's entity. When it has two
(`Swap: {fields: {given: fk:Product, taken: fk:Product}}`), name the field:
`Swap.given`. A many-to-many or one-to-one field cannot back a tab: the
entity's list filters only by its fks.

A page named anything but `home` with the kind `dashboard` is a page of
charts at `/<name>`: a `DashboardGrid` with a `ChartCard` of the rows of every
entity of the spec, each counted with one list request (`useResourceCounts`),
under the user's access. `- home: dashboard` stays the scaffold's own home
page, which `karni build` leaves to the project.

### `seed`

`seed` maps an entity to its demo rows per `karni seed` run (`karni make
seeder <Entity> --count <n>`, a Seeder's `Meta.count`). `0` skips it.

A large count (experimental) is seeded in bulk: from the project's
`KARNI_SEED_BULK_THRESHOLD` (default 1000) rows, `karni seed` writes the
entity's rows in batches, relation targets first and foreign keys drawn from
existing rows ([volume seeding](seeding.md#volume-seeding)). `karni plan`
shows the volume and the expected time class on the change (`seconds`,
`about a minute`, `minutes`, `an hour or more`):

```text
seed
  + Booking: 200000, 200,000 rows in bulk, about a minute
```

## Coming later

These keys are reserved for features on the roadmap. A spec that uses one
now is refused with `C224`, so a spec written today keeps its meaning when
they arrive:

| Key | Where | For |
|---|---|---|
| `search:` | top level | a search block across entities |

## Validation

`karni spec validate` reports every problem it finds, each with its code,
the line (from the YAML parser), the key's path, what is wrong and the fix:

```text
karni.yaml:22: C230: Order.buyer points at Customer, but no app of the spec has an entity named Customer. Fix: Add the entity Customer (or fix the name). ...
karni.yaml: 1 problem.
```

`--json` prints `{file, valid, issues: [{code, line, path, message, fix}]}`.
The exit status is 1 when there is a problem. It reads the YAML first, then
the shape of every key, then, once the shape is right, what each value
means. `karni explain <code>` prints any code's entry.

| Code | Problem |
|---|---|
| [C210](errors.md#c210) | no spec file |
| [C211](errors.md#c211) | not valid YAML |
| [C212](errors.md#c212) | an unknown key |
| [C213](errors.md#c213) | a value of the wrong type, or a required key missing |
| [C214](errors.md#c214) | an unknown version |
| [C215](errors.md#c215) | a name that is not valid (app, entity, role, page) |
| [C216](errors.md#c216) | a field type that is not valid (the generator's own message) |
| [C217](errors.md#c217) | an access rule that is not valid |
| [C218](errors.md#c218) | a grant pattern or scope that is not valid |
| [C219](errors.md#c219) | a feature value that is not valid |
| [C220](errors.md#c220) | a page entry that is not valid |
| [C221](errors.md#c221) | a module option that is not valid |
| [C222](errors.md#c222) | a key written twice |
| [C223](errors.md#c223) | a seed count that is not valid |
| [C224](errors.md#c224) | a key reserved for a later release |
| [C225](errors.md#c225) | the kind and the modules disagree |
| [C230](errors.md#c230) | a relation to an entity that does not exist |
| [C231](errors.md#c231) | a relation name two apps define |
| [C232](errors.md#c232) | access names a role the spec does not declare |
| [C233](errors.md#c233) | a grant names an entity the spec does not have |
| [C234](errors.md#c234) | a grant's scope does not fit the entity |
| [C235](errors.md#c235) | a page names an entity that does not exist |
| [C236](errors.md#c236) | a module Karni does not know |
| [C237](errors.md#c237) | a field group names a field the entity does not have |
| [C238](errors.md#c238) | key, search, order, audit or scope_paths names a field the entity does not have |
| [C239](errors.md#c239) | owner does not lead to the user |
| [C240](errors.md#c240) | `owned:<path>` does not lead to the user |
| [C241](errors.md#c241) | seed names an entity that does not exist |
| [C242](errors.md#c242) | two pages share a route |
| [C251](errors.md#c251) | an external entity's keys do not fit (`table`, `writable`, `pk`, seed) |
| [C252](errors.md#c252) | `database` names an alias the project does not have |
| [C253](errors.md#c253) | a relation joins two databases |
| [C254](errors.md#c254) | a rename (`was`) that is not valid |
| [C460](errors.md#c460) | a tree entity's keys do not fit (`external`, a `parent` or `position` field) |
| [C620](errors.md#c620) | a role grant's `tree:<path>` does not lead to a tree entity |
| [C640](errors.md#c640) | `navigation` names a page the spec does not have |
| [C641](errors.md#c641) | a `navigation` entry that is not valid |
| [C642](errors.md#c642) | a `navigation` requirement that is not valid |
| [C540](errors.md#c540) | `global_search` searches a field that is not a text field of the entity |
| [C541](errors.md#c541) | `global_search` has no fields (none given and `search` is empty) |
| [C542](errors.md#c542) | `global_search`'s `title` or `subtitle` is not a field of the entity |
| [C560](errors.md#c560) | a related tab names no entity |
| [C561](errors.md#c561) | a related tab names an entity with no fk to the page's |
| [C562](errors.md#c562) | a related tab could be either of two fks |
| [C563](errors.md#c563) | a related tab listed twice |
| [C680](errors.md#c680) | a column set names a field the entity does not have, or one twice |
| [C681](errors.md#c681) | a column set with no columns, or a name that is not snake_case |
| [C740](errors.md#c740) | `app.api_version` is not a version name |
| [C324](errors.md#c324) | a module or feature without one it requires, or next to one it conflicts with |
| [C500](errors.md#c500) | `aggregate` names a field or path the entity does not have |
| [C501](errors.md#c501) | `aggregate` names a metric that is not one |
| [C502](errors.md#c502) | a date bucket in `aggregate` that does not fit |
| [C520](errors.md#c520) | an entity's `cache` is not seconds above 0 or `false` |
| [C521](errors.md#c521) | with `api_cache` on, an entity reads an external table or one on another database and has no `cache` |
| [C720](errors.md#c720) | `file:protected` or `image:protected` without the storage module |
| [C245](errors.md#c245) | `karni spec export` cannot read the project |
| [C246](errors.md#c246) | the export's output file exists |

## Export

`karni spec export` writes the spec of an existing project, whether it was
built with `karni make` or by hand. It prints the spec, or writes it with
`-o karni.yaml` (`--force` replaces a file). It reads the backend through
`manage.py karni_facts`, run by the project's interpreter, and the pages from
`frontend/src/routes.tsx`:

- **Entities** are the models on `BaseModel` in the project's own apps.
  A field is written in the field syntax when its type makes the same
  column: the same class, length, digits, null, choices, states, target and
  uniqueness. An argument the syntax does not carry that changes only
  behaviour (a `default`, an `on_delete`, a `related_name`) keeps the field
  and is listed. A field whose column no type makes (a `SearchField`,
  Django's own `EmailField`, a `MoneyField` with other digits) is left out.
- **pk** is written when the model's key type differs from the project's
  `KARNI_PK`. An external model (`Karni.external`) is an entity too, with
  `external`, `table` (from `Meta.db_table`), `writable` and `database`,
  and so is a model Karni manages on another database (`Karni.database`)
  on `UUIDModel` or `IntegerKeyModel`.
- **tree** is `true` for a model on `TreeModel` and `ordered` for one on
  `OrderedTreeModel`. Their `parent` and `position` fields are not written
  under `fields`.
- **key, owner, audit, scope_paths** come from `class Karni`, **groups** and
  **column_sets** from its `field_groups` and `column_sets` (groups from
  `AdminMeta`'s fieldsets when it has no `field_groups`), **order** from
  `Meta.ordering`, **search** from the viewset's `search_fields`,
  **global_search** from `Karni.search` (`true` when it is the defaults).
- **access** comes from the viewset when it is one of the shapes above, else
  it is `access: code`. A model without a viewset is `access: code` too.
- **navigation** comes from a `KARNI_NAVIGATION` list: each item is the
  page whose route it links to.
- **roles** come from `KARNI_ROLES` (left out when it is Karni's default),
  with `KARNI_ACCOUNTS_DEFAULT_ROLES` as `default`. **features** come from
  their settings, **modules** from the installed modules and the settings that
  differ from each module's defaults, **seed** from the seeders' counts.
- **pages** are the routes whose page is a `karni make page` page at its
  default route: a resource list, detail or form, a login, a bare page, and
  the scaffold's dashboard. Any other page at `/<name>` is the project's
  own: `- <name>: code`.

What the spec cannot express is listed on the terminal and as comments at
the top of the file: other `class Karni` options (`dashboard`,
`field_roles`, `actions`, ...), `APIMeta`, other `AdminMeta` options,
access built from `Where`, `Can` or `&`, hand-written pages, grants on
custom actions or on models outside the spec, and the fields above. It stays
in the code, unchanged. The exported spec always passes
`karni spec validate`.

To compare two specs by what they mean, `karni_cli.spec.normal.normalise`
gives one canonical form: defaults written out, `str:255` as `str`,
`choice:a,b` as `choice:a|b`, a lifecycle as its explicit moves,
`own:<field>` as `own`, the key type written out, and access rules sorted.
`was` is left out: it says how the project gets to the spec, not what the
spec describes.

## `karni plan`

!!! warning "Experimental"
    `karni plan`, its output, `--json` and its schema, `manage.py
    karni_rows` and `karni.facts.count_rows` are experimental.

`karni plan` compares `karni.yaml` with the project and prints what
`karni build` would change. It writes nothing: no file, no row.

```sh
karni plan                        # karni.yaml in the project root
karni plan --spec other.yaml --json
karni plan --offline              # no row counts: the database is not opened
```

It validates the spec first (the codes above, exit status 1 on a problem),
reads the project the way `karni spec export` does, compares both in the
normal form, and prints one line per change, grouped by area: `+` add, `~`
change or rename, `-` remove, and `!` in front of a risky change. A fresh
`karni new` project plans everything:

```text
modules
  + payments: provider stripe
  + site
roles
  + instructor: grants classes.booking custom:taught_by, classes.session own
  - customer
entities
  + classes.Studio: (name str:120, slug slug:name, address text?) key slug, search name
...
27 changes, 0 risky.
```

The areas, in order: the app (kind, name), modules to add or remove,
features with the setting each one sets, roles and their grants, apps,
entities with their fields and options (key, search, owner, audit,
global_search, groups, column_sets, order, pk, external, table, writable,
database, tree, aggregate, cache), field changes of existing
entities, access, pages and navigation (the page order, and the menu as
`KARNI_NAVIGATION`), the apps that get migrations, seed
counts, and the API tests `karni make test` writes for new entities. The
plan of the example above on a fresh project is about 400 tokens.

A detail page's related tabs show as `app.Entity.field`, and a dashboard page
what its chart counts:

```text
pages
  ~ Session: list, detail, form -> list, detail (related classes.Booking.session), form
  + overview: dashboard (rows per entity: Booking, Session, Studio)
```

### Risky changes

A change is risky when it can lose data or open it to more people.
`karni build` refuses risky changes without `--allow-destructive`. Each one
says what happens and, when the database answers, how many rows it
affects:

```text
fields
! - classes.Session.title: str:200, its values are lost (40 rows)
! ~ classes.Studio.name: str:120 -> str:60, values longer than 60 do not fit (2 rows)
2 changes, 2 risky.
karni build refuses the risky (!) changes without --allow-destructive.
```

| Risky change | Rows counted |
|---|---|
| a field removed | rows whose field holds a value (a many-to-many: its links) |
| a field whose type changes to another kind (`str` to `text` is safe) | rows whose field holds a value |
| a shorter length (`str`, `url`, `slug`) | rows whose value is longer than the new length |
| a field that becomes required | rows whose field is empty |
| a choice or a state dropped | rows that hold one of the dropped values |
| fewer digits, another currency, other array items, a field that becomes unique | rows whose field holds a value |
| a relation pointed at another entity | rows whose relation is set |
| an entity removed | its rows |
| a module removed | the rows of its models |
| a key type switched (`pk`) on an existing entity | its rows. Switching it is out of scope: `karni build` does not apply it ([why](models.md#choosing-the-key-type)) |
| an entity moved to another database | its rows, which stay where they are |
| an entity made a tree (`tree: true` or `ordered`) | its rows, which all become roots |
| an entity made flat again (`tree` removed) | rows whose `parent` is set |
| `tree: ordered` back to `true` (drops `position`) | the entity's rows |
| a taxonomy removed or pointed at another tree (its tags are dropped) | the entity's rows |
| access widened: reads to `public`, writes or creates from a role to `authenticated` or `public` | the entity's rows (none for creates) |
| a grant's scope widened to `all` | the rows of the entity the grant names (none for a pattern with `*`) |

An external table is never altered or dropped, so removing an external
entity or one of its fields is not risky. An entity or a field the project
already has in a form the spec cannot express (a model not on `BaseModel`,
a field `karni spec export` leaves out) is marked risky too: `karni build`
does not replace code it does not own.

The counts come from `manage.py karni_rows`, which runs only `SELECT COUNT`
queries through each model's base manager (soft-deleted rows count) on the
database the router reads it from. A SQLite file that does not exist is not
created. With `--offline`, or when a database does not answer, the plan says
so on its last lines and shows no counts.

### Renames

`was: <old name>` on a field or an entity makes a rename explicit, and the
data stays:

```yaml
Lesson:
  was: Session
  fields:
    title: {type: "str:200", was: name}
```

```text
entities
  ~ classes.Lesson: from Session, rows kept
fields
  ~ classes.Lesson.title: from name
```

Relations, pages and seed counts that name the old entity follow the
rename. Without `was`, a field removed and a field of the same type added
to one entity are a removal (risky) and an addition, and the removal says
it is probably a rename and how to write `was`. Once the rename is done,
`was` changes nothing and may be removed.

### `--json`

`--json` prints `{version, file, valid, issues, changes, summary,
row_counts}`: each change is `{area, action, target, detail, risky,
reason, rows, managed}`, `action` one of `add`, `change`, `rename` and
`remove`, `rows` `null` when not counted, `managed` `false` for a change in
the project's own code ([what karni build manages](#what-karni-build-manages)),
`summary` is `{changes, risky, not_managed}`, and `row_counts` is `{status, note}` with
`status` one of `counted`, `offline`, `unreachable` and `not needed`. A spec
with problems gives `valid: false` and its `issues`, as
`karni spec validate --json` reports them. The schema is published as
[`karni-plan.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-plan.schema.json)
(in the repository, `docs/assets/karni-plan.schema.json`, regenerated with
`python -m karni_cli.spec.plan > docs/assets/karni-plan.schema.json`).
`version` moves only for a breaking change of the output.

| Code | Problem |
|---|---|
| [C210](errors.md#c210) | no spec file |
| [C250](errors.md#c250) | `karni plan` cannot read the project (`manage.py karni_facts` failed) |

## Questions

!!! warning "Experimental"
    `karni plan --questions`, its `--json` output and schema, `karni spec
    answer`, the question ids and the rules that choose the questions are
    experimental.

Before `karni build`, the agent asks the user only what the spec leaves
open and what matters. Karni decides which questions, with fixed rules over
`karni.yaml` and the manifests of [the module
catalog](modules.md#the-module-catalog). No language model is involved, and
the same spec gives the same questions in the same order.

```sh
karni plan --questions                 # at most 5, most impact first
karni plan --questions --max 0         # all of them (--max N: at most N)
karni plan --questions --json
karni spec answer classes.Booking.owner member
```

It reads only the spec. The project and its database are not opened, so it
works before the project exists. The example at the top of this page,
without these keys:

- `kind: site+app` of `app`
- `provider: stripe` of the payments module
- `access: {read: public, write: "role:staff"}` of Studio
- `owner: member` of Booking
- `default: true` of the member role

gives:

```text
5 of 7 questions for the user before karni build, most impact first:
1. classes.Booking.owner: Who owns a Booking: the member?
   - member: the member (fk:User) (default)
   - created_by: whoever created it
2. classes.Studio.access: Who may see and change studios?
   - granted: what each role's grants allow (default)
   - authenticated: any signed-in user
   - public-read: anyone sees them, only staff change them
   - public-create: anyone creates them (a public form), only staff see and change them
   - staff: only staff
3. roles.default: Which role does someone who signs up get: instructor, member or none?
   - instructor: Instructor, grants classes.session own:instructor, classes.booking custom:taught_by
   - member: Member, grants classes.booking own (default)
   - none: no role, staff give each account its role
4. app.kind: What kind of project is it: an app, a public site or both?
   - app: React screens behind sign-in (default)
   - site: public pages the server renders
   - site+app: both, a public site and an app
5. modules.payments.provider: Which payment provider: Stripe or Razorpay?
   - stripe (default)
   - razorpay
   - test
next: ask the user only these, then karni spec answer <id> <value> for each (or edit karni.yaml), and karni plan --questions again.
```

### What makes a question

A question is a gap: a key the spec does not write, where the answer changes
who sees what or how a module works. The kinds of gap, in the order of
their impact:

| Area | The gap | The options |
|---|---|---|
| `owner` | an entity with a relation to the user (`fk:User`, `o2o:User`, `m2m:User`) and no `owner` | each of those fields (the default is the one the entity's access names in `owned:`, else the first), and `created_by`, whoever created the row, which the own scope uses without an owner. An external entity, or one on another database, has no `created_by` |
| `access` | an entity without `access` | the [`--access` presets](#access) that fit it: `granted` (the default, what no `access` means), `owned:<field>` for its owner and each relation to the user, `authenticated`, and `public-read`, `public-create` and `staff` when the spec has the `staff` role (with another system role: `public-read:<role>`, `public-create:<role>` and `role:<role>`) |
| `roles` | roles declared and none with `default` | each role that is not a system role, and `none`. The default is the role that grants least. Sign-up is open in every project a spec describes (`KARNI_ACCOUNTS_REGISTRATION`), and an account without a role is granted nothing. A spec without `roles` has Karni's shipped roles and no such question |
| `app` | no `app.kind` | `app` (the default), `site` and `site+app` |
| `modules` | an ask of a listed module's manifest whose option the spec does not set. The site module counts when the kind has a site | the manifest's options and default, or any value of the option's type |
| `features` | an ask of a feature the spec turns on, when karni.yaml has a key for it (`terms.required`) | the manifest's options and default |

The data model and access come first, then the kind and the modules, then
the features. Within an area the order is the spec's (apps, entities,
modules), then the manifest's order of its asks. An ask whose setting
karni.yaml has no key for (how long a sign-in code lives, who may sign up
with a code) is never a question: `karni modules show <name>` prints it,
and its setting goes in the settings. Nothing cosmetic is ever asked:
names, labels, colours, page titles, field groups, pages and seed counts
are the agent's to choose.

A key written in the file settles its question, even when it holds the
default: `owner: created_by`, `access: {read: granted, write: granted}`,
`default: false` on the roles. A key that starts with `x-` settles nothing.

Each question has an `id`, the same for the same gap whatever else the spec
says (`classes.Booking.owner`, `classes.Studio.access`, `roles.default`,
`app.kind`, `modules.payments.provider`, `features.terms.required`), one
sentence to ask, its options with what each means, its default, and the
dotted `key` of karni.yaml the answer sets.

### Answers

`karni spec answer <id> <value>` writes the answer into karni.yaml, and the
question is gone:

```text
$ karni spec answer classes.Booking.owner member
karni.yaml: apps.classes.entities.Booking.owner set (classes.Booking.owner answered).
next: karni plan --questions (6 questions open)
```

Only that key changes. The comments, the order and the layout of every
other line stay as they are: a new key goes at the end of its mapping (`,
key: value` before the `}` of a flow mapping), and an empty module
(`payments:`) takes its options on its own line. An access answer is
written in the preset's shape (`owned:member` is `access: {read:
"owned:member", write: "owned:member"}`), and the sign-up role as `default:
true` on that role (`none`: `default: false` on each role that is not a
system role). Editing the file by hand settles a question the same way.

| Code | Problem |
|---|---|
| [C400](errors.md#c400) | the id is not an open question: mistyped, or settled already |
| [C401](errors.md#c401) | the value is not one of the options, or not of the question's type |
| [C402](errors.md#c402) | the answer cannot be written without changing anything else (an anchor shares the key), or it would make the spec invalid. Nothing is written |

### `--json` of the questions

`--json` prints `{version, file, valid, issues, questions, total, max}`.
Each question is `{id, area, question, options: [{value, label}], default,
multiple, types, key}`, `total` counts every open question, and `max` is
the cap (`null` with `--max 0`). A spec with problems gives `valid: false`,
its `issues` and no questions. The schema is published as
[`karni-questions.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-questions.schema.json)
(in the repository, `docs/assets/karni-questions.schema.json`, regenerated
with `python -m karni_cli.spec.questions >
docs/assets/karni-questions.schema.json`). `version` moves only for a
breaking change of the output.

## `karni build`

!!! warning "Experimental"
    `karni build`, its output, `--json` and its schema, the layout of the
    files it writes, `.karni/build.json` and `manage.py
    karni_makemigrations` are experimental.

`karni build` makes the project match `karni.yaml`. It applies the plan
`karni plan` prints, in one command, and a second run with no change in the
spec writes nothing.

```sh
karni build                          # karni.yaml in the project root
karni build --dry-run                # the plan and the files it would write
karni build --allow-destructive      # apply the risky (!) changes too
karni build --force                  # replace Karni-owned files edited by hand
karni build --adopt classes/karni/api.py
karni build --json
```

From an empty `karni new` project and the spec at the top of this page, it
prints the plan, then one line per step:

```text
...
25 changes, 0 risky.
modules     karni add payments
files       23 written: 15 Karni's, 8 the project's (pyproject.toml, classes/__init__.py, ...)
migrations  classes/migrations/0001_initial.py
migrate     applied 84 on default
seed        Studio 3, Session 40, Booking 200 (demo login demo@example.com / karni-password)
types       frontend/src/api/types.ts and hooks.ts
test        6 passed in 3.36s, tests/openapi.snapshot.json updated (the API changed: commit it)
check       ok
Built: the project matches karni.yaml.
```

Run again, it prints one line: `Nothing to build: the project matches
karni.yaml.`

### What Karni owns, and what the project owns

Karni's code and the project's code live in separate files. Karni rewrites
its own files on every build. It creates the project's files once, adds a
missing class to them, and never rewrites what is in them.

| What | Karni owns (rewritten every build) | The project owns (created once) |
|---|---|---|
| models | `<app>/karni/models.py`: each entity as an abstract class on `BaseModel` or `BigIntBaseModel` (or the external declaration), with its fields, `Meta`, `class Karni` and `AdminMeta` | `<app>/models.py`: `class Session(karni.Session):` and the project's methods |
| API | `<app>/karni/api.py`: each viewset's model, access, search and cache, as a base class | `<app>/viewsets.py`: `class SessionViewSet(karni.SessionViewSet):` and custom actions |
| seed counts | `<app>/karni/seeds.py`: a `Seeder` per entity with a `seed` count | `<app>/seeds.py`: the subclass, where a field's demo values are steered |
| tests | `<app>/tests/karni/test_<entity>.py`: `assert_crud`, and `assert_isolated` when reads are owned | every other test |
| settings | the block between `# karni:spec start` and `# karni:spec end` in `config/settings.py`: roles, features and module options | everything else in `config/settings.py` |
| pages | `frontend/src/pages/karni/*.tsx`, and the blocks between `// karni:spec imports` and `// karni:spec routes` markers in `routes.tsx` | every other page and route |

For one entity, `Session` in the app `classes`, that is:

```python
# classes/karni/models.py (Karni's)
class Session(BaseModel):
    studio = models.ForeignKey("Studio", on_delete=models.PROTECT)  # audited: W965
    title = models.CharField(max_length=200)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["starts_at"]

    class Karni:
        owner_field = "instructor"


# classes/models.py (the project's)
from classes.karni import models as karni


class Session(karni.Session):
    def is_full(self) -> bool:
        return self.booking_set.count() >= self.capacity
```

Django sees one model, `classes.Session`: a field changed in Karni's abstract
class is a normal migration of the project's concrete model. The viewset the
router serves is the project's subclass, and it inherits the access Karni
declares, so every [architecture rule](enforcement.md) passes without an
opt-out. A subclass overrides anything of its base: a method, `access`, or
one option with `class Karni(karni.Session.Karni)`. The models pass Karni's
checks too: a required fk of an audited or financial entity is `PROTECT`
(`karni.W965`), and the fields `search` names get a `SearchField`
(`karni.W967`). To cascade on purpose, declare the field again in the
project's subclass with `on_delete=models.CASCADE` and say why in
`class Karni(karni.Session.Karni): cascade = {"studio": "<why>"}`.

The settings block sits right above `karni_settings(globals())`, where every
setting takes effect, `KARNI_2FA` included. It sets every feature of the
spec (`KARNI_2FA`, `KARNI_EMAIL_OTP`, `KARNI_SOCIAL_TOKEN_PROVIDERS`,
`KARNI_TERMS`, and `KARNI_API_CACHE` with `KARNI_API_CACHE_TTL` while
`api_cache` is on), `KARNI_API_VERSION` when the spec has `app.api_version`,
`KARNI_ROLES` and `KARNI_ACCOUNTS_DEFAULT_ROLES` when the spec has roles,
`KARNI_NAVIGATION` when it has `navigation`, and each module option. A social
provider's client ids come
from the environment: `KARNI_SOCIAL_GOOGLE_CLIENT_IDS` (comma-separated) for
`google`, and so on. A setting assigned again below the call wins over the
block, so leave the spec's settings to the spec.

### A hand edit in a Karni-owned file

`karni build` records a sha256 of every Karni-owned file and block in
`.karni/build.json`. Commit it. Before it writes anything, it checks every
hash. A Karni-owned file edited by hand stops the build (`C273`), nothing is
written, and the message names the file and the changed lines:

```text
classes/karni/api.py: edited by hand (line 14)
    -    search_fields = ("name",)
    +    search_fields = ("name", "address")
error C273: classes/karni/api.py was edited by hand, so karni build wrote nothing.
next: three ways on: 1. move the change into classes/viewsets.py (the subclass of each viewset), or karni.yaml, then karni build. 2. karni build --force replaces it (your copy is kept as classes/karni/api.py.orig). 3. karni build --adopt classes/karni/api.py makes it the project's: karni build stops managing it.
```

The three ways on:

1. **Move the change** into the project's file the message names (the
   subclass of the class), or into `karni.yaml`, then run `karni build`.
2. **`--force`** replaces the file and keeps the edited copy next to it as
   `<file>.orig` (`.orig.1` when one exists).
3. **`--adopt <file>`** hands the file to the project. `karni build` stops
   managing it, records that, and says so on every later run. A change of
   the plan that lands in an adopted file is then marked not managed.
   `--adopt config/settings.py` and `--adopt frontend/src/routes.tsx` adopt
   their blocks.

A Karni-owned file that is missing is written again. One that exists but
was never written by `karni build` stops the build the same way, until it
is forced or adopted.

### The escape hatches

- `access: code` on an entity: Karni's base class declares no access, and
  the project's viewset does. `karni build` creates it once with `access =
  Granted()` as a start. Any access the project declares there matches the
  spec.
- `- <name>: code` in `pages`: the page at `/<name>` is the project's, and
  `karni build` leaves it alone. `karni spec export` writes a page of the
  project's this way.
- Every subclass in the project's files overrides its Karni base.

### The steps, in order

The build validates the spec and computes `karni plan`'s change list with
what `.karni/build.json` records. The plan decides everything after it: the
modules to add, the entities and fields renamed, the tables created and
removed. Nothing is written when the plan asks for what the build does not
do, or for a risky change without `--allow-destructive` (each named with its
rows). Then the hash check, then the steps:

1. **modules**: `karni add` for each module the plan adds. A module removed
   from the spec is refused (`C271`): `karni remove` comes with the module
   catalog.
2. **files**: the Karni-owned files and blocks, the project's files once
   (an app the spec adds gets its skeleton as `karni make app` writes it).
   After `karni new --recipe`, `.karni/build.json` names the recipe, and
   this step also writes the recipe's own files over the stubs (experimental,
   [the stub rule](recipes/index.md#the-stub-rule)).
3. **migrations**: `manage.py karni_makemigrations`, which writes the
   renames (`was:`) as `RenameModel` and `RenameField` first, so the data
   stays even when the type changes too, then runs Django's
   `makemigrations` without questions. A required field added to an empty
   table needs no value. On a table with rows it stops (`C277`): add it as
   optional first, fill it, then make it required.
4. **migrate**: on `default` and on every alias an entity names.
5. **seed**: only the tables this build created, only while they hold no
   row, with the spec's `seed` counts. Demo rows never mix with real data.
   A count at the bulk threshold is inserted in bulk, and the step says so
   with its time (`Booking 200000 in bulk (61.2s)`, experimental).
6. **types**: `karni types`, when the project has a frontend.
7. **test**: the project's own tests (`karni test`). The API changed on
   purpose, so the contract snapshot (`tests/openapi.snapshot.json`)
   follows it, and the step says so: commit it.
8. **check**: `karni check`.

The build stops at the first failure with its code, what was done and what
to do next. The steps not run yet are remembered on this machine
(`.karni/local/state.json`), and the next `karni build` continues from
there.

### What karni build manages

On a project built by hand (`karni make`, or code written without Karni),
`karni spec export -o karni.yaml` then `karni build` manages only what is
new: new entities, the settings block and new pages. The models and
viewsets the project already has stay the project's, and `karni plan` marks
a change to them `(not managed)`:

```text
fields
  + shop.Product.color: str:30? (not managed)
entities
  + shop.Invoice: (product fk:Product, total money:EUR)
2 changes, 0 risky, 1 not managed.
karni build leaves the changes marked not managed to the project's own code.
```

Converting a hand-written model or viewset into a Karni-owned base is a
later step of the [app-builder roadmap](roadmap/app-builder.md), not part of
this release.

### `--json`

`--json` prints `{version, file, valid, issues, status, code, message,
plan, files, hand_edits, adopted, steps, next}`. `status` is one of `built`,
`nothing to build`, `dry run`, `refused`, `failed` and `invalid`, `plan` is
exactly what `karni plan --json` prints, each file is `{path, action,
owner}`, each step `{name, status, summary}` with `status` one of `done`,
`skipped`, `failed` and `pending`. The schema is published as
[`karni-build.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-build.schema.json)
(in the repository, `docs/assets/karni-build.schema.json`, regenerated with
`python -m karni_cli.builder.output > docs/assets/karni-build.schema.json`).
`version` moves only for a breaking change of the output.

| Code | Problem |
|---|---|
| [C270](errors.md#c270) | a risky change without `--allow-destructive` |
| [C271](errors.md#c271) | a module removal |
| [C272](errors.md#c272) | a key type switch |
| [C273](errors.md#c273) | a Karni-owned file was edited by hand |
| [C274](errors.md#c274) | `--adopt` names a file karni build does not own |
| [C275](errors.md#c275) | the project's code is in the way (a model, a class, a route) |
| [C276](errors.md#c276) | a module karni build added is not installed |
| [C277](errors.md#c277) | makemigrations failed |
| [C278](errors.md#c278) | migrate failed |
| [C279](errors.md#c279) | seeding failed |
| [C280](errors.md#c280) | karni types failed |
| [C281](errors.md#c281) | the project's tests fail |
| [C282](errors.md#c282) | karni check fails |
| [C283](errors.md#c283) | a project class karni build must remove has code of its own |
| [C284](errors.md#c284) | a marker karni build writes at is missing |
| [C285](errors.md#c285) | `.karni/build.json` cannot be read |
| [E304](errors.md#e304) | `manage.py karni_makemigrations --renames` is not a rename list |
| [E305](errors.md#e305) | an app has two latest migrations, so the renames have no place (`makemigrations --merge` first) |

## Recipes

!!! warning "Experimental"
    `karni recipes`, its `--json` output and schema, the recipe format and
    its schema, the `karni.recipes` entry point group, the blank start and
    the ranking of `--match` are experimental.

A recipe is a ready-made `karni.yaml` for a kind of app that many people
ask for. A new app starts from the closest recipe, or from the blank start
when none fits, and the agent changes what the request asks for.

Karni ships six: `shop`, `booking`, `crm`, `lms`, `marketplace` and `data-portal`
([recipes](recipes/index.md) has a page for each). `karni new "<Name>"
--recipe <name>` makes a new project from one: the recipe's `karni.yaml`
with the project's name, then `karni build`, which also writes the recipe's
own domain code, seeds and tests over its stubs and runs the tests and
`karni check`.

```sh
karni recipes list                                  # every recipe, and the blank start
karni recipes list --match "a booking app for a yoga studio"
karni recipes show <name>                           # its spec, what people usually change
karni recipes show blank                            # the blank start
karni recipes list --json                           # also --match and show
```

### The format

A recipe is a folder:

```text
<name>/
  recipe.toml   what it is and when it fits
  karni.yaml    the spec, with app.recipe naming the recipe
  files/        optional: the recipe's own domain code, seeds and tests, each at the
                path it takes in the project (files/shop/models.py is shop/models.py)
```

The files under `files/` go where the project owns the code: the methods of
`<app>/models.py`, the actions of `<app>/viewsets.py`, `<app>/seeds.py` and
tests of its own ([what Karni owns](#what-karni-owns-and-what-the-project-owns)).
The first `karni build` after `karni new --recipe` writes them over its own
stubs, only while each is still exactly what it wrote ([the stub
rule](recipes/index.md#the-stub-rule)).

`recipe.toml`, every key:

| Key | Required | Takes |
|---|---|---|
| `name` | yes | the recipe's name: its folder's name, or its entry point's. Lowercase letters, digits, `-` and `_`. `blank` is taken by the blank start |
| `title` | yes | a short human name, e.g. `Online shop` |
| `purpose` | yes | what the app does, in one line of at most 80 characters |
| `use_when` | yes | plain phrases of what someone asks for when the recipe fits, e.g. `["online shop", "sell products", "checkout"]`. `--match` ranks by them |
| `usually_changed` | no | what people usually change in the spec after starting from it, in plain words, e.g. `["the product fields", "the currency"]` |

An example:

```toml
name = "helpdesk"
title = "Helpdesk"
purpose = "Tickets that customers open and staff answer and close."
use_when = ["helpdesk", "support tickets", "customer support", "ticketing"]
usually_changed = ["the ticket fields", "who may see which tickets"]
```

Unknown keys are errors. The schema is published as
[`karni-recipe.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-recipe.schema.json)
(in the repository, `docs/assets/karni-recipe.schema.json`, regenerated with
`python -m karni_cli.recipes > docs/assets/karni-recipe.schema.json`).

### Where recipes come from

1. **Built in**: the folders of `karni_cli/recipes/<name>/`, package data of
   karni-cli. A recipe of Karni's is a folder added there, nothing else.
2. **Installed**: the `karni.recipes` entry point group of the environment
   karni-cli runs in. The entry point's name is the recipe's name, and its
   value is the package that is the recipe's folder.

```toml
# pyproject.toml
[project.entry-points."karni.recipes"]
helpdesk = "acme_recipes.helpdesk"
```

A built-in recipe wins over an installed one of the same name. A recipe
that cannot be used (a `recipe.toml` that breaks the format, a name that is
not its folder's, no `karni.yaml`, a name taken already) is left out, and
`karni recipes` reports it as `C421`.

### `--match`

`--match` ranks the recipes for a one-line request by plain word overlap,
with no language model, so the same request always gives the same ranking:

1. The request, each `use_when` phrase and the purpose become words:
   lowercase, letters and digits only, plurals made singular (`bookings` is
   `booking`, `categories` is `category`), and the words that name no app
   left out (`a`, `the`, `app`, `with`, `for`, `want` ...).
2. Each word of the request scores 2 when one of the recipe's `use_when`
   phrases has it, else 1 when its purpose has it.
3. The recipes that score 2 or more come back, the highest first, then by
   name, at most 3, each with its score and the words that scored.

When none scores 2, `karni recipes list --match` says so and prints the
blank start.

### The blank start

The blank start is where an app starts when no recipe fits: a `karni.yaml`
with the version and the app's name (the project's, inside a project), and
nothing else. `karni recipes show blank` prints it:

```yaml
# yaml-language-server: $schema=https://cbsshekhawat18-lab.github.io/karni/assets/karni-spec.schema.json
version: 1
app:
  name: Reading Log
```

### `--json` of the recipes

`--json` prints `{version, request, threshold, recipes, blank, next,
problems}`. Each recipe is `{name, title, purpose, use_when,
usually_changed, source, files, spec, score, matched}`: `spec` is its
`karni.yaml` with `show` and `null` in a list, and `score` and `matched` come
with `--match`. `blank` is `{name: "blank", spec}`, and `problems` lists the
recipes left out. The schema is published as
[`karni-recipes.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-recipes.schema.json)
(in the repository, `docs/assets/karni-recipes.schema.json`, regenerated
with `python -m karni_cli.recipes.output >
docs/assets/karni-recipes.schema.json`). `version` moves only for a breaking
change of the output.

| Code | Problem |
|---|---|
| [C420](errors.md#c420) | no recipe of that name (the message names the closest) |
| [C421](errors.md#c421) | a recipe cannot be used: the list leaves it out, and `show` names its problem. A file of the recipe at a path karni build writes is one |
| [C440](errors.md#c440) | `karni new --recipe` with `--design`, `--kind site` or `--no-staff-app` |
| [C441](errors.md#c441) | a recipe's file would replace code of the project's ([the stub rule](recipes/index.md#the-stub-rule)) |

## MCP tools

!!! warning "Experimental"
    These tools, their parameters and their results are experimental.

`karni mcp` serves the flow from a one-line request to a running app as
tools, beside `context`, `rules` and `check` ([MCP](agents.md#mcp)). Each
does what its command does and returns JSON. Karni never calls a language
model here: the agent reads the results and decides.

| Tool | The command | Returns |
|---|---|---|
| `recipes(match="", name="")` | `karni recipes list --match`, `show` | [`karni-recipes.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-recipes.schema.json) |
| `spec_validate(path="")` | `karni spec validate --json` | `{file, valid, issues}` |
| `questions(spec="", max=5)` | `karni plan --questions --json` (`max` 0: all) | [`karni-questions.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-questions.schema.json) |
| `answer(id, value, spec="")` | `karni spec answer` | `{version, file, valid, issues, id, keys, open, next}` |
| `plan(spec="")` | `karni plan --json` | [`karni-plan.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-plan.schema.json) |
| `build(spec="", dry_run=False, allow_destructive=False)` | `karni build --json` | [`karni-build.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-build.schema.json) |
| `modules(name="")` | `karni modules list`, `show --json` | `{version, modules, problems}`, a line per module and feature, or `{version, module, problems}` with the entry in full |

`spec` and `path` are the spec file, relative to the project (`karni.yaml`
when empty). A failure the command reports as an error comes back as
`{"error": {"code": "C210", "message": "..."}}`, and nothing is written.

`build` never takes `--force` or `--adopt`. A Karni-owned file edited by hand
stops it with `C273`, its changed lines and the three ways on, and `next`
starts with "ask the user which of the three ways on to take": forcing or
adopting is the user's call, made with `karni build` itself.

What `recipes(match=...)` returns when no recipe fits:

```json
{
  "version": 1,
  "request": "a reading log where each reader tracks the novels they finished",
  "threshold": 2,
  "recipes": [],
  "blank": {
    "name": "blank",
    "spec": "# yaml-language-server: $schema=...\nversion: 1\napp:\n  name: Reading Log\n"
  },
  "next": "no recipe matches: start karni.yaml from the blank start (karni recipes show blank) and write in it what the request asks for",
  "problems": []
}
```

Every result follows `$defs/<tool>` of
[`karni-mcp.schema.json`](https://cbsshekhawat18-lab.github.io/karni/assets/karni-mcp.schema.json)
(in the repository, `docs/assets/karni-mcp.schema.json`, regenerated with
`python -m karni_cli.agent_tools > docs/assets/karni-mcp.schema.json`),
which points at the other schemas for the results that are a command's
`--json` output.
