---
description: "The Karni app spec, karni.yaml (experimental): one small file that describes an app in the terms karni make, karni add and the settings use, with karni spec validate, karni spec export, karni plan and published JSON Schemas."
---

# The app spec: `karni.yaml`

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `karni.yaml` format, `karni spec validate`, `karni spec export`,
    `karni plan`, `manage.py karni_facts`, `manage.py karni_rows`,
    `karni.facts`, the `karni_cli.spec` package and both JSON Schemas. They
    may change in a minor release, and each change is in the CHANGELOG. The
    error codes keep their meaning.

A spec is one small file that describes a Karni app: its apps and entities,
roles, built-in features, modules and pages. An AI agent turns a one-line
request into a spec, and Karni turns the spec into code without a language
model. This release reads and checks a spec (`karni spec validate`),
writes the spec of an existing project (`karni spec export`) and shows
what would change to make the project match a spec ([`karni
plan`](#karni-plan)). `karni build`, which makes the change, comes next on
the [app-builder roadmap](roadmap/app-builder.md).

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

### `modules`

Each key is a module `karni add <name>` installs, one of the modules of
[the module catalog](modules.md#the-module-catalog) (`karni modules list`):
Karni's `approvals`, `impersonation`, `payments` and `site`, and any module
installed next to karni-cli that ships a manifest. The value is a mapping of
the module's options, or nothing. An option is one of the module's own
settings its manifest lists, lowercased and without its prefix, with the
type the manifest gives it: `payments: {provider: stripe}` is
`KARNI_PAYMENTS_PROVIDER = "stripe"`. Credentials such as
`STRIPE_SECRET_KEY` are never options: they stay in `.env`. A kind with a
site (`site`, `site+app`) has the `site` module without listing it. What a
listed module or feature requires must be listed too, and two that conflict
cannot both be (`C324`).

### `features`

The keys are the built-in features of the module catalog that karni.yaml
takes (`karni modules show <name>` prints each one's questions). Response
caching (`api_cache`) is in the catalog with no key here yet: set
`KARNI_API_CACHE` in the settings.

| Key | Takes | Setting |
|---|---|---|
| `two_factor` | `true` / `false` | `KARNI_2FA` (needs `karni[2fa]`) |
| `email_code_login` | `true` / `false` | `KARNI_EMAIL_OTP`, [sign-in with a code](accounts.md#sign-in-with-a-code-sent-by-email) |
| `social_login` | `google`, `microsoft`, `apple`, one or a list | `KARNI_SOCIAL_TOKEN_PROVIDERS`, [sign-in with an ID token](accounts.md#sign-in-with-an-id-token-google-microsoft-apple). The spec names the providers. Their client ids stay in settings or `.env` |
| `terms` | `{version, url}`, plus `required`, `paths`, `exempt` | `KARNI_TERMS`, [terms acceptance](accounts.md#terms-acceptance) |

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
| `search` | a field or a list | `karni make model --search` (the viewset's `search_fields`) |
| `owner` | a relation to the user, or a path (`workspace__members`) | `Karni.owner_field`, the `own` scope's field |
| `audit` | `true`, or a list of fields | `Karni.audit`, [change history](change-history.md) |
| `groups` | title to fields | the admin form's fieldsets (`AdminMeta.extra = {"fieldsets": ...}`) |
| `order` | a field or a list, `-` for descending | `karni make model --order` (`Meta.ordering`) |
| `scope_paths` | key to lookup path | `Karni.scope_paths`, for the `related:<key>` scope |
| `access` | `{read, write, create}`, or `code` | the viewset's `access` |
| `pk` | `uuid` or `bigint` | `karni make model --pk`: `BaseModel` or `BigIntBaseModel` (default: the project's `KARNI_PK`) |
| `external` | `true` / `false` | `karni make model --external`: `Meta.managed = False`, `Karni.external` |
| `table` | `table` or `schema.table` | `karni make model --table` (`Meta.db_table`), with `external` only |
| `writable` | `true` / `false` | `Karni.writable`, with `external` only |
| `database` | an alias of `DATABASES` | `Karni.database` (default: `default`) |
| `was` | the entity's old name | a rename that keeps the table and its rows (`karni plan`) |

Field types are exactly `karni make model`'s syntax, checked by its own
parser and renderer, so the spec and the generator can never disagree:
`str[:len]`, `text`, `int`, `float`, `decimal[:max:places]`, `bool`, `date`,
`datetime`, `url`, `file`, `image`, `uuid`, `choice:a|b`, `fk:Model`,
`m2m:Model`, `o2o:Model`, `money[:CUR]`, `percent[:min:max]`, `quantity`,
`email[:unique]`, `slug[:source]`, `phone`, `country`, `currency`,
`json[:queried]`, `array:str[:len]`, `state:<a>><b>|...` (a `StateField`,
written as `karni make form --states` takes it), `daterange`,
`datetimerange` and `capacity[:total]`, with a trailing `?` for optional.
See [the karni command](cli.md) for what each one generates.

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

`groups` become the admin change form's fieldsets today. Field groups in the
React forms and detail pages (item 12 of the
[large-apps roadmap](roadmap/large-apps.md)) will read the same key. A field
left out of every group goes in a last group without a title.

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
| `- home: dashboard` | the scaffold's home page at `/`, the staff dashboard |
| `- about: blank` | `karni make page about`: a bare page at `/about` |
| `- login: login` | `karni make page login --kind login` |

Two pages may not share a route (`C242`).

### `seed`

`seed` maps an entity to its demo rows per `karni seed` run (`karni make
seeder <Entity> --count <n>`, a Seeder's `Meta.count`). `0` skips it.

## Coming later

These keys are reserved for features on the roadmap. A spec that uses one
now is refused with `C224`, so a spec written today keeps its meaning when
they arrive:

| Key | Where | For |
|---|---|---|
| `tree: true`, `taxonomies:` | entity | hierarchies and taxonomies |
| `aggregate:` | entity | aggregation endpoints (large-apps item 8) |
| `search:` | top level | a search block across entities |
| `markdown` | field type | markdown fields (large-apps item 12) |

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
| [C324](errors.md#c324) | a module or feature without one it requires, or next to one it conflicts with |
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
- **key, owner, audit, scope_paths** come from `class Karni`, **order** from
  `Meta.ordering`, **groups** from `AdminMeta`'s fieldsets, **search** from
  the viewset's `search_fields`.
- **access** comes from the viewset when it is one of the shapes above, else
  it is `access: code`. A model without a viewset is `access: code` too.
- **roles** come from `KARNI_ROLES` (left out when it is Karni's default),
  with `KARNI_ACCOUNTS_DEFAULT_ROLES` as `default`. **features** come from
  their settings, **modules** from the installed modules and the settings that
  differ from each module's defaults, **seed** from the seeders' counts.
- **pages** are the routes whose page is a `karni make page` page at its
  default route: a resource list, detail or form, a login, a bare page, and
  the scaffold's dashboard.

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
entities with their fields and options (key, search, owner, audit, groups,
order, pk, external, table, writable, database), field changes of existing
entities, access, pages and navigation, the apps that get migrations, seed
counts, and the API tests `karni make test` writes for new entities. The
plan of the example above on a fresh project is about 400 tokens.

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
reason, rows}`, `action` one of `add`, `change`, `rename` and `remove`,
`rows` `null` when not counted, and `row_counts` is `{status, note}` with
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
