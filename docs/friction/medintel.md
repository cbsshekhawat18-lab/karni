---
description: "The friction log of Medintel, Karni's large-app reference: every opt-out, workaround and missing feature met while building it from karni.yaml, each with the file and line, the reason and the roadmap item or issue it belongs to."
---

# Friction log: Medintel

[Medintel](https://github.com/cbsshekhawat18-lab/karni/tree/main/examples/medintel)
is the reference app for the [large-app roadmap](../roadmap/large-apps.md):
trees, per-user grants, taxonomies, aggregates, saved charts, cross-model
search, both sign-in methods, the terms gate, markdown fields, navigation
from data, import and export, on synthetic data. It was built from
`karni.yaml` with `karni build`, and the project wrote only what the spec
could not say. Each entry below is a place where it had to opt out, work
around Karni or do without a feature. The file and line are in the example
at the commit that adds this page. This log is the input for the next
roadmap.

Fixed while building (each has its own commit):

- `karni seed --reset` failed on a tree, because `parent` protects its
  children. It now deletes a tree leaves first (`e033766e`).
- `assert_crud`'s list check looked at the first page only, so the generated
  tests failed on a seeded table. It now follows the pages (`a9f53cec`).

Open entries:

## The spec cannot say what the model needs

1. **`on_delete` has no spec key.** `karni.yaml` writes every `fk:` as
   `CASCADE`, and `karni check` then warns `W965` for an audited or financial
   model. The project declares `class Karni: cascade = {...}` with a reason
   for Trial.sponsor, Deal.acquirer and Deal.seller
   (`intel/models.py:45`, `intel/models.py:59`). Why: the spec maps to `karni
   make model`, which has no flag for it. Belongs to the app spec (not a
   large-apps item). New issue: add `on_delete: protect|set_null|cascade` to a
   relation's mapping form (`{type: fk:Company, on_delete: protect}`), and
   make `karni build` write the `cascade` reason for a deliberate cascade.
2. **`key` sets the import key, not the natural key.** An export names a
   relation by the target's natural key, which is only a unique slug, char or
   email field. Company, Brand, Condition and Intervention have `key:` but no
   unique column, so exports and imports named them by UUID. The project
   sets `natural_key` by hand (`intel/models.py:12`, `:23`, `:34`, `:52`).
   The spec also has no way to say a text field is unique, so the key is not
   a constraint (`karni.yaml:23`, `:31`, `:43`, `:98`). Belongs to the app
   spec and [import and export](../import-export.md). New issue: `key` also
   writes `natural_key`, and a field type takes `:unique` for text as it does
   for `email`.
3. **No label for a row.** The generated `__str__` is the first field. For a
   tree whose first field is a code, facet counts and tree labels showed
   `C6.1.1`. The project overrides `__str__` (`intel/models.py:15`, `:26`).
   Belongs to the app spec. New issue: `label: name` on an entity, written
   as `__str__` and used for the natural label in the UI.
4. **No index key for a searched field.** `search: [name, title]` on Person
   raised `W967` (no index covers `title`). The project dropped `title` from
   `search` (`karni.yaml:61`). Belongs to the app spec. New issue: an
   `index` list on an entity, or `search` adding the index itself.

## The scaffold and the build leave manual steps

5. **`karni new` writes an absolute path for `@karni/ui`** in
   `frontend/package.json` when run from a checkout, so the lockfile is
   not portable. The project changed it to `file:../../../packages/karni-ui`
   (`frontend/package.json:19`). Belongs to the scaffold. New issue: write a
   path relative to the project when the checkout is reachable from it.
6. **`karni add charts` does not add `@karni/charts-ui`.** The page that draws
   a saved chart needs it, and `karni build` printed no step for it. Added by
   hand (`frontend/package.json:20`). Belongs to the modules
   ([saved charts](../charts.md)). New issue: a module that ships a UI package
   adds it to `frontend/package.json` and says so.
7. **The menu from data needs a hand edit of the layout.** `navigation:` in
   the spec writes `KARNI_NAVIGATION`, but `frontend/src/layout.tsx` still
   renders the static routes until `navSource="server"` is added
   (`frontend/src/layout.tsx:38`). Belongs to large-apps item 13
   ([navigation](../navigation.md)). New issue: `karni build` (or the
   scaffold when `navigation` is set) writes the prop.
8. **A `code` page needs a hand-written route.** The spec lists `insights`,
   `players`, `deals-chart`, `search` and `login` as `code`, so the menu
   links to them, and `karni check` fails with `E533` until the routes exist.
   They are written by hand (`frontend/src/routes.tsx:69` to `:73`). Belongs
   to the app spec. New issue: `karni build` writes a route and an empty
   page file for a `code` page, and leaves it alone afterwards.
9. **A navigation entry for a `code` page requires only sign-in** with
   `navigation: true`, so a customer with no deal grant saw the deals chart
   link. The project lists the entries with `requires`
   (`karni.yaml:142` to `:144`). Belongs to large-apps item 13. New issue: a
   `code` page takes `requires` in `pages`, so `navigation: true` is enough.
10. **The Google client id has no default.** The settings block reads
    `env.list("KARNI_SOCIAL_GOOGLE_CLIENT_IDS")`, so every command, `karni
    check` and the first `karni build` included, fails until it is in `.env`
    (`config/settings.py:41`). The project put a placeholder in `.env.example`
    and the CI job. Belongs to large-apps item 1a. New issue: write
    `default=[]` and let startup validation report an empty list as a
    problem only when a request needs it, or have `karni build` add the line
    to `.env.example`.
11. **The deprecated cache header warns in a fresh app.** A project with
    `api_cache` on gets the `X-Karni-Cache` deprecation warning in its first
    test run. The project sets `KARNI_API_CACHE_LEGACY_HEADER=False`
    (`.env.example:156`). Belongs to large-apps item 9. New issue: the
    scaffold writes that line, since a new project reads no old header.

## Seeding and tests

12. **Seeding a tree needs hand-written code.** The seeder plants a fixed
    nested tree with short codes (`intel/seeds.py:64`). The generated seeders
    infer random rows, which would give a flat or random hierarchy. Belongs to
    large-apps item 14 ([seeding](../seeding.md)). New issue: a `seed:` form
    for a tree entity that takes a nested outline.
13. **Grants cannot be seeded from the spec.** `KARNI_SEED_LOGINS` creates
    users with roles only, so the per-user grants of the demo customers are a
    seeder of `UserGrant` (`intel/seeds.py:145`). Belongs to large-apps item 6.
    New issue: `KARNI_SEED_LOGINS` takes grants, or `karni.yaml` takes a
    `seed_grants` list.
14. **`--reset` does not wipe a module's table or `UserGrant`.** A second
    `karni seed --reset` failed on the saved chart's unique slug and doubled
    the grants, so both seeders clean up after themselves
    (`intel/seeds.py:153`, `:167`). Belongs to large-apps item 14. New issue:
    `--reset` wipes every model a seeder names.
15. **No test helper for ID tokens.** The tests need a signing key and a
    fake key-set fetcher, and Karni's own copy lives in its test tree
    (`tests/idtokens.py`, 33 lines here). Belongs to large-apps item 1a. New
    issue: `karni.testing.id_tokens` with `mint()` and the fetcher.
16. **Reading a sign-in code in a test takes three settings and a fixture.**
    The in-memory backend, the on-commit capture and a lookup in its outbox
    (`tests/test_sign_in.py:32`). Belongs to large-apps item 1b. New issue: a
    `karni.testing.last_login_code(email)` helper.
17. **Importing 300 unchanged rows took 16 seconds** (PostgreSQL, a busy
    laptop), with markdown columns and two tags per row
    (`tests/test_transfer.py:57`). A preview and a commit each validate every
    row through the serializer. Belongs to [import and
    export](../import-export.md). New issue: measure the import per row on a
    model with taxonomies, and skip the second validation when the preview's
    rows are stored.

21. **The settings block breaks the project's own lint.** `karni build` writes
    `from karni.conf import env` in the middle of `config/settings.py`, so
    ruff reports `E402` there (`config/settings.py:31`). The block is
    Karni-owned, so the project cannot add a `noqa`. Belongs to the app spec.
    New issue: write the import above the block, or a `# noqa: E402`.
22. **`karni plan` always reports a navigation change.** After a successful
    `karni build`, `karni build --dry-run` still lists `~ navigation: home,
    Trial, ...` as a change, with a grouped menu that has `requires` entries
    (`karni.yaml:137` to `:146`). Nothing is written, so it is noise, but it
    hides a real change. The cause was not tracked down. Belongs to large-apps
    item 13. New issue: make the plan compare the menu it would write with
    the menu in the settings.

## Missing features

18. **A tree cannot be scoped to its granted subtree.** A customer sees every
    node of Condition and Intervention (their read is `authenticated`), and
    only the rows under their nodes. `tree:<path>` needs a relation, so a
    tree has no scope over itself. `TreeView`'s `access` greys the other
    nodes in the UI, but the API lists them (`karni.yaml:27`, `:35`).
    Belongs to large-apps item 5. New issue: a `tree:self` scope that reads a
    tree's own rows under the granted nodes plus their ancestors.
19. **No Google sign-in helper in `@karni/ui`.** `SocialButton` takes
    `getIdToken`, and each app writes the script loader and the One Tap call
    (`frontend/src/google.ts`, 38 lines). Belongs to large-apps item 1a. New
    issue: `loadGoogleIdToken(clientId)` in `@karni/ui`, which loads no SDK
    until it is called.
20. **A grant on one tree and a grant on another are a union.** An analyst
    granted Oncology and Biologics sees a trial in either, which is what the
    customer asked for, but the spec cannot say "both". Documented in the
    README and tested (`tests/test_grants.py`). Belongs to large-apps item 7.
    New issue: an `all_of` form for tree grants if a project needs it.
