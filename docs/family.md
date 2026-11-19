---
description: "Several recipes in one Karni project (experimental): app.recipes, karni recipes add, remove and upgrade, how a part's karni.yaml is merged into the project's, what a part may and may not do, and the refusals C442 to C449."
---

# The family: several recipes in one project

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    `app.recipes`, `app.currency`, `apps.<label>.route`, `features.people`,
    `features.events`, `features.timeline`, `features.preferences`, the `requires`, `conflicts` and `version` keys of
    `recipe.toml`, `karni recipes add`, `remove` and `upgrade`, `karni new
    --recipe a --recipe b`, the `.karni/recipes/` record,
    `frontend/src/karni/parts.ts` and `karni_cli.recipes.compose`. The error
    codes keep their meaning.

A project may hold several recipes: a booking app and a CRM, a shop and a
course catalogue. Each recipe in a project is a **part**. A part is one Django
app, and its app label is its **prefix** (`bookings`, `crm`). Every part works
alone, and the parts installed together share one database, one sign-in, one
set of roles and one menu.

```sh
karni new "Studio" --recipe booking --recipe crm   # two parts from the start
karni recipes add crm                              # a part added to a built project
karni recipes remove crm --allow-destructive       # and taken out again
karni recipes upgrade                              # each part's newer files
```

## What `karni recipes add` does

1. It reads the recipe's `karni.yaml` (its **fragment**) and merges it into
   the project's karni.yaml by the rules below. A conflict stops it before
   anything is written, with a code from `C442` to `C447`.
2. It writes the merged karni.yaml, keeps the fragment as it was added in
   `.karni/recipes/<name>/karni.yaml`, and names the part in
   `.karni/build.json`.
3. It runs `karni build`, which writes the part's own files by the
   [stub rule](recipes/index.md#the-stub-rule), records the sha256 of each in
   `.karni/recipes/<name>/record.json`, migrates, seeds only the new tables,
   runs the tests and `karni check`.

`--no-build` stops after step 2. `karni build` then does step 3.

`karni recipes remove <name>` takes the part's apps, roles, pages, menu group
and seed counts out of karni.yaml, and its record out of `.karni/`. Dropping
its tables is a risky change, so the build that follows needs
`--allow-destructive` (`C270`). The part's files the project never changed
(their recorded sha256) are deleted, so its tests do not run against models
that are gone. The files you changed stay on disk, each one listed, for you to
delete. Adding the recipe again writes the deleted ones again.

## How a fragment is merged

| Key | Rule | On conflict |
|---|---|---|
| `version` | Must be equal. | `C214` |
| `app.name`, `app.kind` | The project's stay. A recipe is an app: a `kind: site` project refuses it. | `C440` |
| `app.recipes` | The part is appended. A part listed already is refused. | `C442` |
| `app.currency` | One currency for the project: its own, else the first part's. A part's `money:XYZ` fields are written as `money`, which reads `app.currency`, and the payments module's `currency` follows it. | none |
| `modules` | Union. An option the project wrote itself keeps its value. Two parts asking for different values of an option are refused. | `C445` |
| `features` | Union. `terms` keeps the project's version and unions `paths`. | none |
| `roles` | `admin` and `customer` are the family roles: their grants add up and the project's name stays. Every other role is `<prefix>-<role>`, is new to the project, holds no `"*"` and is not a default role. | `C443` |
| `apps` | The part's app label must be new. | `C442` |
| `apps.<label>.route` | Where the part's pages live: `/<label>` unless the recipe names another. It must be the part's own and not a family page's. | `C444` |
| `pages` | Appended. `home` belongs to the family: the build writes `home: dashboard`, and a part that lists it when the project has one is refused, as is a page at another family route. An entity name two apps define is written `app.Name`. A part's own code pages live under its route: `shop.reports: code` is the page at `/shop/reports`. | `C444` |
| `navigation` | A part's menu becomes one group, labelled with the recipe's title. A part installed alone keeps its entries flat. A menu may name a family page the project's modules and contracts provide without listing it in `pages`: `orders`, `cart` and `checkout` with commerce, `settings` with preferences, `people` with people, and `home`, `account` and `search` always. | none |
| `dashboard` | The part's home tiles are appended. A tile whose key the project has already (two parts that both show `commerce.revenue`) is kept once. `karni recipes remove` takes the part's own tiles out and keeps a contract's. | none |
| `seed` | Counts add up per entity. | none |

The family pages are `home` (`/`), `signin`, `account`, `search`, `inbox`,
`settings`, `people`, `cart`, `checkout` and `orders`. They come from Karni
and its contracts, never from a part.

## `recipe.toml`: `requires`, `conflicts` and `version`

```toml
name = "visits"
version = "1.0.0"
requires = ["people>=1", "events>=1", "storage"]
conflicts = ["another-recipe"]
```

`requires` names core contracts and modules, each with an optional version
range (`>=`, `>`, `<=`, `<`, `==`, `!=`, joined by commas). What a part
requires is installed with it:

| Requirement | What the merge does |
|---|---|
| `people` | `features.people: true`: `karni build` writes `KARNI_PEOPLE = True`, which installs `karni.people` ([people](people.md)), and `admin` gets the explicit grants `people.*:merge` and `people.person:erase` |
| `events` | `features.events: true`: `karni build` adds `karni.outbox` to `INSTALLED_APPS` ([family events](family-events.md)) |
| `timeline` | `features.timeline: true`, with `features.people` and `features.events`, which it needs: `karni build` adds `karni.timeline` after `karni.outbox` ([timeline](timeline.md)) |
| `preferences` | `features.preferences: true`: `karni build` adds `karni.preferences` to `INSTALLED_APPS` and writes `KARNI_PREFERENCES_DEFAULTS` with the project's name, and `KARNI_PREFERENCES_LOCKED` with its currency (every money field is in it, so Settings does not change it). The part declares its settings section and its connections ([preferences](preferences.md)) |
| `notify` | `features.notify: true`: `karni build` adds `karni.notify` to `INSTALLED_APPS`. The part declares its message kinds in its `messages.py`, and a role may grant `notify.emailtemplate` to whoever edits the emails ([notifications](notify.md)) |
| a module (`storage`, `payments`, `commerce`) | lists it under `modules`, so the build adds it, with the modules its manifest requires (`commerce` brings `payments`) |

A contract version the installed Karni does not have, or a name that is
neither a contract nor a module karni-cli knows, is refused (`C446`).
`conflicts` names recipes and modules a part cannot share a project with,
checked both ways (`C447`). `version` is the recipe's own version, recorded
when the part is added and compared by `karni recipes upgrade`.

## Routes and the frontend

A part's entity pages are mounted under its route: with `route: /bookings`
the resources list is `/bookings/resources` and a booking is
`/bookings/bookings/<id>`. `apps.<label>.route` in karni.yaml changes it.
A project without a route keeps its pages at `/<entity route>`, as before.

The build writes `frontend/src/karni/parts.ts`, which Karni owns. It imports
each part's `frontend/src/<prefix>/index.ts` when the part has one, and calls
its `register()` at startup, in the order of `app.recipes`. `routes.tsx`
imports it in the block Karni writes. A part registers its own screens,
sections and routes there. It never edits another part's.

## Upgrades

`karni recipes upgrade [name]` compares each part with the recipe karni-cli
has now:

- a file of the part's the project never changed (its sha256 is the recorded
  one) is replaced, and a new file is added.
- a file the project changed is kept, and the recipe's new version is written
  beside it as `<file>.recipe-<version>` for you to merge by hand.
- in karni.yaml, each of the part's entities and roles the project left as it
  was added is updated, and each one it changed is reported.

Then run `karni build`. Shared code (Karni, its contracts, the modules,
@karni/ui) is a versioned dependency and gets its fixes through `karni
upgrade`, never through a part.

## What a part may and may not do

A part may depend on Karni, its contracts, @karni/ui and the modules in its
`requires`. It may subscribe to any declared event by name.

A part must not:

- import another recipe's code, Python or TypeScript.
- point a relation at another recipe's model.
- add a column to a contract's table (it keeps a profile table of its own).
- name a role without its prefix, or hold `"*"`.
- own a family page or route.
- assume it is alone: no test that counts every row of a shared table.

## How the rules are kept

`karni check` enforces the rules above on the built project, not only when
`karni recipes add` merges a part. It reads `.karni/recipes/` (the fragment each
part was added with) and karni.yaml, so a project without parts is unaffected.
`pytest --pyargs karni.testing.architecture` runs the same rules.

| Rule | Code | What fails |
|---|---|---|
| `part-imports-part` | [K315](errors.md#k315) | a file of one part (its app folder or `frontend/src/<prefix>/`) imports another part or names its app label: `"crm.Deal"`, `"crm.deal:own"`, `"crm:deal-list"`, `"crm/x.html"`, `apps.get_model("crm", ...)`, a migration dependency, a template `include`, `extends` or `url`, a frontend import |
| `part-role-prefix` | [K315](errors.md#k315) | with two or more parts, a part after the first has a role that is not `<prefix>-<role>` and not `admin` or `customer` |
| `part-route` | [K315](errors.md#k315) | a part's base route is a family page's or another app's, or one of its generated pages in routes.tsx is outside its base |

The contracts are not parts, so `karni.people`, `karni.events`, `karni.timeline`,
`karni.preferences` and `karni_commerce` are always allowed. The first part keeps
its roles as its recipe wrote them, as the merge does. To join two parts on
purpose, put the reason in an allow marker on the line or the line above:
`# karni: allow(part-imports-part): <reason>` (`//` in TypeScript, `{# ... #}`
in a template).

## How the family is tested

- Each recipe's own tests run when its project is built alone.
- `tests/test_family_build.py` builds one part alone and two together, adds a
  third and removes it, on every push (the `family` job).
- `tests/test_family_rules.py` builds booking and crm together and breaks each
  rule in the built project (a bridge file, a role without its prefix, a route
  that is a family page's), and builds a deliberately bad test part that must
  fail `karni check`.
- `tests/test_family_pairs.py` builds every pair of the family's parts together:
  its tests and `karni check` must be green. The `pairs` job in
  `.github/workflows/family-pairs.yml` runs it nightly and on demand, not on
  every push. The list of parts (`PARTS`) grows with the family, and a test fails
  when a recipe with connections is missing from it.
- `tests/test_family_matrix.py` reads every recipe's `connections.py` and fails
  when a declared connection has no test with it on, no test with it off, or
  names another recipe in `needs`.

## Codes

| Code | When |
|---|---|
| [C442](errors.md#c442) | an app label or a recipe the project has already |
| [C443](errors.md#c443) | a role slug: without the prefix, taken, holding `"*"`, or a default role |
| [C444](errors.md#c444) | a route: two apps on one, a family route, or a page listed twice |
| [C445](errors.md#c445) | a module option two parts set differently |
| [C446](errors.md#c446) | a requirement the project cannot meet |
| [C447](errors.md#c447) | a recipe's `conflicts` |
| [C448](errors.md#c448) | `karni recipes remove` of a recipe the project does not hold |
| [C449](errors.md#c449) | `karni recipes upgrade` without the part's record |
| [K315](errors.md#k315) | a part naming another part, a role without its prefix, or a route outside its base |
| [K315](errors.md#k315) | a part's role without its prefix, or its route outside its base |
