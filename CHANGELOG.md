# Changelog

Every package in this repository (`karni`, `karni-cli`, `karni-payments`,
`@karni/ui`, `@karni/payments-ui`) is released at one version, in lockstep;
see [docs/releasing.md](docs/releasing.md).

Breaking changes and deprecations are recorded in machine-readable form in
`packages/karni/karni/changelog/<version>.toml` — that is what `karni upgrade`
reads to apply codemods and list the manual steps — and explained in
`docs/migrations/<version>.md`. This file is the human summary.

## Unreleased

- **Fixed: exporting a nested relation crashed.** A serializer that nests
  related rows (`many=True`, or `?expand=`) made CSV and XLSX exports fail
  with `TypeError: unhashable type: 'dict'`. Nested rows now export by the
  related model's natural key, the same as a plain relation.
- **Fixed: restoring a deleted row skipped its listeners.** New
  `karni.events.on_restored`, the counterpart of `on_deleted`. It runs inside
  the restore's transaction, so a listener that raises undoes the restore.
  `SoftDeleteModel.delete()` and `restore()` now run in a transaction with
  their listeners. The admin's delete and restore actions now go row by row,
  so `on_deleted` and `on_restored` run there too (they used one bulk
  `UPDATE` and fired nothing). A row a listener refuses is reported and the
  rest are restored. EventHub uses this to take a restored booking's seats
  again. A sold-out tier refuses the restore with E985.
- **Fixed: duplicate OpenAPI operation IDs.** `GET <resource>/import/` and
  `GET <resource>/import/{job}/` shared one ID, and so did the two
  effective-permissions routes, so generated clients got `_retrieve_2`
  names. A route that ends in a path parameter now gets `_by_<param>`, for
  example `events_import_by_job_retrieve`. Clients generated from the schema
  rename those two functions. The standard detail IDs do not change.
- **Fixed: booking one slot at the same moment could fail with a 500.**
  PostgreSQL sometimes settled several concurrent writes against a
  `no_overlap` constraint with a deadlock instead of the overlap error.
  Writes to one resource (one room, say) now take turns through a
  transaction-scoped advisory lock, so the second writer sees the first
  one's row and gets the 409 (E984).
- Query budgets no longer count `SAVEPOINT` statements or those advisory
  locks. They come from `transaction.atomic()` nesting and locking, not from
  reading data.
- **Typed fields: the database enforces what a value is (`karni.fields`).**
  `MoneyField` (NUMERIC(19,4), a declared currency, floats refused with
  `E962`, a declared rounding rule; `quantize`/`split`/`allocate` never lose
  a cent), `PercentField` and `QuantityField` (CHECK bounds),
  `EmailField` (unique on `LOWER(email)`), `SlugField` (generated,
  collision-free), `PhoneField` (E.164 CHECK), `CountryField`/`CurrencyField`
  (CHECK against shipped ISO 3166-1 / ISO 4217 lists), `JSONField(queried=True)`
  and `ArrayField` (GIN), and `SearchField` (a generated tsvector with a GIN
  index the default search provider matches through). Unique Karni fields and
  the new `LiveUniqueConstraint` are partial on soft-deletable models, so a
  deleted row frees its value. Every guarantee is proven with raw SQL on
  PostgreSQL and, where portable, SQLite. New checks: `E960` (a FloatField
  named like money fails boot), `W965` (CASCADE on a financial or audited
  model), `E964`/`W964` (a field or guarantee the configured database lacks),
  `W967` (a searched, filtered or ordered column without an index), plus
  `E961`, `E963`, `E968`, `E970`; `class Karni:` gains `append_only` (BRIN),
  `cascade`, `financial` and `not_money`. `karni schema` (`manage.py
  karni_schema`, `--json`) lists every column, constraint and index, why it
  exists and whether the database has it. `karni.accounts` 0005 creates
  `btree_gist`; `CreateExtension` names the exact SQL (`E966`) when the role
  may not. `karni make model` gains `money[:EUR]`, `percent`, `quantity`,
  `email[:unique]`, `slug[:source]`, `phone`, `country`, `currency`,
  `json[:queried]` and `array:<type>` (`email`, `slug` and `json` now write
  the Karni fields). Rule K114. See [docs/fields.md](docs/fields.md).
- **Lifecycle columns and limited resources, enforced by the database**
  ([docs/lifecycle-and-capacity.md](docs/lifecycle-and-capacity.md)).
  `karni.fields.StateField(states=..., transitions=...)` declares a status
  column's states (a `CHECK` on the column) and its legal moves:
  `row.transition("status", "confirmed")` or assignment + `save()` is checked
  against the state the row was loaded with (`E980`, `E982`, a 400 in the
  API), written with a conditional `UPDATE ... WHERE status = <loaded>` so two
  concurrent transitions never both succeed (`E981`, a 409), recorded in the
  change log (action `transition`) and announced by
  `karni.lifecycle.state_changed` / `@on_transition`. The OpenAPI schema
  carries `x-karni-transitions` and `x-karni-initial`.
  `karni.fields.CapacityField(total=...)` is a counter the database keeps
  between zero and its total, consumed only with `karni.capacity.reserve()` /
  `release()` (a locked, conditional `UPDATE`; `E985`, a 409, names what is
  left). `class Karni: no_overlap = NoOverlap("room", "during", ignore=...)`
  adds a PostgreSQL `EXCLUDE USING gist` constraint (creating `btree_gist`
  when first applied) that ignores soft-deleted and released rows (`E984`, a
  409 naming the existing row); off PostgreSQL it is not enforced and
  `karni.W980` says so. New: `karni.fields.DateRangeField` /
  `DateTimeRangeField`, `karni.models.GuardedModel` (part of `BaseModel`),
  `karni make model` types `state`, `daterange`, `datetimerange` and
  `capacity`, agent rules `K115` and `K116`, codes `E980`–`E988`, `W980` and
  `C370`–`C372`. EventHub's ticket tiers and bookings use them (615 lines of
  project code, measured).
- **`karni why`: an access decision explained by the code that makes it.**
  `karni why events/<id> --as alice@example.com [--action update]`,
  `karni why events.<field> --as ...`, `karni why-empty events --as ...` and
  `karni why 403 <request-id>` (a request the dev server recorded) print the
  user and roles, the grants that applied and where each comes from, the gate
  and every part of `read`/`write` against the row, the row's values
  (redacted like the change history), the result, `file:line` and one
  concrete fix; `--json` for agents, `why`/`why_empty` on `karni mcp`, and
  rule `K015`. The verdict comes from running DRF's own gate and lookup in a
  rolled-back transaction while the access layer records its decisions
  (`karni.api.access.trace`); `Predicate.explain()` takes a predicate apart
  with the same folds `|` and `&` use. A test matrix checks the verdict
  against the API for every user, viewset, action and row of the test app.
  New: `karni.why`, `manage.py karni_why`, `BaseViewSet.base_queryset()`,
  `karni.vetoes.first_veto`, `karni.accounts.roles.grant_rows` /
  `grant_sources`; codes `E901`–`E908`, `C310`–`C312`. See
  [debugging](docs/debugging/why.md).
- **Debugging: one request id everywhere, a development capture, and
  `karni trace` / `karni replay` / `karni explain --failure`.** Every
  request gets an id (`X-Request-ID` on the response; a client's value is
  accepted only in development or from a trusted proxy,
  `KARNI_REQUEST_ID_TRUST_HEADER`) that follows its Celery tasks and their
  retries (a message header), its email (`X-Karni-Request-ID`), outgoing
  calls (`karni.tracing.outgoing_headers()`) and the change log
  (`ChangeLog.request_id`, `ChangeBatch.request_id`; migration
  `karni_audit.0003`). With `DEBUG` on, Karni writes `.karni/requests/`,
  `.karni/failures/` and `.karni/trace/` under the project, bounded
  (`KARNI_DEBUG_CAPTURE_KEEP`, `KARNI_DEBUG_TRACE_DAYS`) and redacted by
  the change log's rules plus known secret values; with `DEBUG` off nothing
  runs. `karni trace` follows a request through its async work in order,
  `karni replay [--as USER]` re-runs it against the current code (rolled
  back unless `--commit`), `karni explain --failure` turns a crash into a
  brief; the same three are MCP tools and agent rules K030–K032. New codes
  E920–E924, W920, C320–C323. karni-payments links a webhook delivery to
  the checkout it settles. See [debugging](docs/debugging/capture.md).
- **Debugging: `karni explain -` and `karni queries`.** `karni explain -`
  reads a pasted traceback, test failure or log line (stdin) and names the
  Karni failure in it: a registered code, an agent rule, a query-count
  failure, a CSRF/CORS refusal, an access outcome or a documented
  framework-adjacent failure (driver, database, migrations, settings, Redis,
  OpenAPI), with the cause, the first project frame, the fix and the docs
  link, or says plainly that it does not recognise it. `karni queries
  <endpoint> --as <user>` runs one endpoint in-process (writes rolled back),
  records every SQL statement with its stack and groups the repeated ones by
  the serializer field and relation behind them, with the optimiser's reason
  and the exact hint (`--json`, `--explain`, `--all`). The optimiser now
  records its blind spots (`karni.api.optimizer.blind_spots`). MCP tools
  `explain_text` and `queries`; agent rules K013 and K014; codes E940–E943,
  C340, C341. See [debugging](docs/debugging/explain.md).
- One brand across the welcome page, the admin and `@karni/ui`: the same
  colours in light and dark, radius, font stack and dark-mode switch (the
  `dark` class on `<html>`, following the system preference by default). The
  `karni` package ships `@karni/ui`'s token stylesheet as the static file
  `karni/tokens.css`, a byte-for-byte copy that a test keeps identical. The
  admin loads it through `UNFOLD["STYLES"]` with `karni/unfold-theme.css`;
  unfold's primary scale and text colours now read the tokens (`@karni/ui`'s
  near-black primary in light mode, near-white in dark, replacing the indigo
  scale), its neutral scale holds the tokens' gray values, `BORDER_RADIUS` is
  `var(--karni-radius-md)` and the font is `@karni/ui`'s system stack instead
  of Inter. Retheme the admin like the frontend, with `--karni-*` overrides in
  a stylesheet appended to `UNFOLD["STYLES"]` ([admin](docs/admin.md#theming)).
  The welcome page inlines the tokens instead of its own palette. Karni's
  admin pages (import, permission matrix, effective permissions) share
  `karni/admin-pages.css`, with no colour literals and no dark-mode duplicates.
  On a tablet the matrix shows several roles beside a narrower model column,
  the template downloads and the effective-permissions link are 44px buttons,
  and on touch screens unfold's sidebar rows, inputs, selects and save buttons
  are 44px. The hard-delete confirmation uses unfold's layout and buttons (its
  buttons rendered as plain text). Account emails use the brand's colour values.
- `@karni/ui` forms: `ResourceForm` validates when a field loses focus (not
  per keystroke; `validationMode` / `reValidateMode` change it), puts every
  DRF error shape on its field, shows a focusable summary when more than one
  thing fails, words 401/403/409/429/5xx and offline failures in a banner with
  "Try again", never loses typed input, shows a skeleton shaped like the form,
  "You can't edit this event" on a 403, disables the fields while saving
  (`PendingButton`), submits with Enter and Ctrl/Cmd+Enter, autofocuses on
  create, and wires labels, `aria-invalid`, `aria-describedby` and
  `aria-required` for every field kind. Unsaved changes: `beforeunload` while
  dirty (`guardUnsavedChanges`), `onDirtyChange`, and
  `useUnsavedChangesGuard` for a router's blocker. New `slots`
  (`defaultResourceFormSlots`), `submitLabel`, `autoFocus`, `resourceLabel`.
  Fixed: an empty optional email or URL field no longer blocks the submit, and
  a created form now starts over after saving (it kept the typed values).
  `ResourceSelect` pages through the API instead of showing one page (scroll,
  "Load more", keyboard), renders only the rows in view, keeps results while
  a search loads, says when search is unavailable, tells "no venues yet" from
  "no match", has loading, error, 403 and offline states, labels preselected
  ids in one `?id__in=` request where the API has it, never shows a bare id,
  forwards its ref and takes `onBlur`, `aria-*`, `slots`
  (`defaultResourceSelectSlots`), `searchable`, `idsFilter`. Input, Textarea,
  Select, Checkbox, Switch and FileUpload draw `aria-invalid` with the
  destructive tokens; `Select` and `FileUpload` take `aria-describedby`,
  `aria-invalid` and `onBlur`. A slow `PendingButton` keeps its accessible
  name. `useSchema` returns `refetch` and `isFetching`.
- `@karni/ui` unhappy-state kit: `describeError` words any failure in plain
  words (never a status code), `ErrorState`, `PermissionDenied`,
  `PendingButton` (progress after 500ms, keeps its width), `useDelayedFlag`,
  `useOnlineStatus`. Dark mode for apps: `ThemeProvider`, `ThemeToggle` and
  `KARNI_THEME_SCRIPT` (follows the system until the user chooses), and
  `karniTheme()` from the new `@karni/ui/vite` entry, which puts the script
  first in `index.html`'s `<head>`. A project from `karni new` has all of it
  wired, with the toggle in the sidebar footer.
- `karni ui detect`: adopts the frontend's design system as `@karni/ui`'s
  tokens, in one file the project owns (`karni-theme.css`, imported after
  `@karni/ui/styles.css`). shadcn/ui: every token references the project's
  own variable (`var(--primary)`, or `hsl(var(--primary))` for Tailwind 3
  HSL channels) on `:root, .dark`, and `karni-primitives.tsx` registers the
  project's shadcn components as Karni's primitives. Otherwise a Tailwind
  theme (`@theme`, or the `tailwind.config` Node evaluates), a Material UI,
  Chakra UI or Mantine theme (literal values read statically), or Karni's
  defaults listed for editing. The report lists every token mapped and every
  value not mapped with the reason (`--json` for agents, `--dry-run` to
  preview); an edited file is never overwritten without `--force`. New error
  codes C301-C304. `karni new` does not write the file (nothing to detect in
  a fresh project). See [docs/theming.md](docs/theming.md).
- `@karni/ui` ResourceDetail, ResourceImport, ChangeHistory, LoginForm and
  AuthGuard handle every unhappy state through the kit, each with `slots`
  (and `defaultXSlots` to wrap). ResourceDetail: a loading placeholder in the
  record's own layout, header included (no layout shift); "Couldn't find this
  event" for a 404 (worded so an out-of-scope record is not confirmed to
  exist) with a `back` action; "You can't view this event" for a 403; retry
  that refetches the schema when that failed; offline reloads by itself;
  `title`/`actions` may be functions of the record; Edit and Delete with
  `onEdit`/`canEdit`, `enableDelete`/`canDelete`/`onDeleted` (delete asks
  first and reports a refusal in the dialog). A field the role may not read
  has no row at all; an empty value is the new shared `EmptyValue` (an en
  dash read as "empty"), also used by ResourceTable (which now treats `""`
  as empty) and ChangeHistory. ResourceImport shows no form when the role may
  not import, keeps the file after a failed upload, confirms a commit with
  its counts, announces progress by the quarter, and its tables have
  captions and header scopes. LoginForm tells wrong credentials from
  throttling, server errors and a dropped connection, wires the message to
  the fields and focuses the email (`autoFocus`). AuthGuard can explain a
  refusal (`explain`: a sign-in prompt for anonymous visitors,
  PermissionDenied for a role without access; `anonymous`/`denied` replace
  one case). Deprecated: a guard with no `fallback` and no `explain` still
  renders nothing, as in 0.3, and warns once in development; 1.0 makes
  `explain` the default (`fallback={null}` keeps rendering nothing).
  Behaviour changes: a non-HTTP sign-in failure no longer reads as wrong
  credentials;
  ResourceDetail's empty dash is "–" (was "—") and its error panel no longer
  shows a raw error message.
- `@karni/ui` primitive registry: `<KarniProvider primitives={{ button: Button,
  input: Input, select: {...} }}>` renders every Karni component with the
  project's own primitives (roles `button`, `input`, `textarea`, `checkbox`,
  `switch`, `label`, `skeleton` and the `select` family), keeping Karni's
  schema-driven behaviour. shadcn/ui's components fit the contract as they
  are. `KarniPrimitivesProvider` and `useKarniPrimitives` are exported.
- `@karni/ui` design tokens: every visual value in every component now
  resolves from a CSS custom property in `--karni-color-*`, `--karni-space-*`,
  `--karni-radius-*`, `--karni-font-*` or `--karni-shadow-*` (plus stacking,
  opacity, motion and line widths). The preset maps Tailwind's scales onto
  them, so one stylesheet rethemes every component; colours take any CSS
  colour. Motion drops to 0ms under `prefers-reduced-motion`. New ESLint rule
  `karni/no-style-literals` and a test that compiles every component class
  keep literals out; `npm run build` runs the lint. Every Storybook story
  renders pixel-identical before and after, light and dark. The 0.3 HSL
  triplet names (`--karni-primary`, ...) still work and are deprecated
  ([docs/migrations/0.4.md](docs/migrations/0.4.md)). ResourceDetail's section
  background now uses the shared `muted-subtle` shade (50% muted, was 40%).
- `@karni/ui` app shell, keyboard and screen readers: `Layout`, `Page`,
  `Modal`, `Toaster`, `EmptyState`, `Stat`, `DataChart` and `FileUpload` take
  `className` and `slots` (`slots={{ NavLink: RouterLink }}`), with exported
  slot contracts and `default*Slots`; `ModalTitle` and `ModalDescription` are
  exported. Layout's mobile drawer is a modal dialog (focus trapped and
  returned to the menu button, Escape closes, labelled) and the shell starts
  with a skip link; nav links, SelectTrigger and the toast close buttons show
  a keyboard focus ring. Toasts are announced by urgency (errors assertive)
  and pause while hovered or focused. FileUpload announces refused files,
  takes `error`, `uploading`, `aria-invalid`, `aria-describedby` and
  `aria-labelledby`. DataChart is focusable (the arrow keys read point by
  point), gets a generated summary and `loading`, and keeps its axis labels
  legible on phones. Stat takes `loading`, and a zero delta reads "Unchanged"
  (it read "Increased by +0"). `Input`, `Textarea`, `SelectTrigger` and
  `Checkbox` show a destructive border under `aria-invalid`. Contrast: token
  values change so every pair the components use reaches WCAG AA in both
  themes (light `muted-foreground`, `destructive`, `input`, `chart-2`,
  `chart-3`; dark `destructive`, `destructive-foreground`, `input`), checked by
  a new test, and the dark theme's modal and drawer scrim dims the page (it
  lightened it). axe-core runs over every Storybook story in both themes in
  CI (WCAG 2.x A and AA) and fails the build on any violation; a story turns
  one rule off only with a written reason. Dialogs are never taller than the
  viewport (they scroll inside), and a busy pagination button keeps its name.
- `@karni/ui` ResourceTable in every state and at real size. Each state is its
  own screen and a replaceable slot (`slots`, `defaultResourceTableSlots`):
  a loading outline of the real layout (nothing moves when data arrives),
  "No events yet" with the create action (`onCreate`, `createLabel`) apart
  from "No events match" with "Clear filters", errors in plain words with a
  retry, a failed refresh that keeps the rows, "You can't view events" for a
  403 (4xx are no longer retried, except 408 and 429; anything else retries as
  the app's QueryClient `retry` default says, so `retry: false` shows the
  error at once), offline, and progress
  after 500ms with controls that do not double-fire. Row actions follow the
  schema's `x-karni-access` rules for the signed-in user (`canCreate`,
  `canEdit`, `canDelete` override); delete failures are reported (row delete
  now confirms in a dialog instead of `window.confirm`). Bulk actions confirm
  destructive work with the count, may return `{ failed: [{ id, reason }] }`
  to mark failed rows, and show progress. Page, page size, sort, search and
  filters live in the URL (namespaced, Back works; `syncUrl`, `urlNamespace`,
  `stateStore` for a router). Page size choice, first/last and jump to page;
  wide tables scroll in their own box with a sticky header and a frozen first
  column; compact rows and hidden columns are remembered per user; below
  `cardBreakpoint` (the table's own width) rows render as cards. Rows open
  from the keyboard, checkboxes are named after their row, and page, sort,
  selection and loading changes are announced. The parsed schema now carries
  each operation's `access` rule. Changed wording: the empty screen says "No
  events yet" (was "Nothing here yet"), the select-all checkbox "Select all
  events on this page", row checkboxes "Select <row>", filter "All" items
  "Status: All", and list errors read like every other error ("Something went
  wrong on our side", "Try again").
- The README opens with why Karni exists, then says what problem it solves,
  how, what you get and what you still write. The canonical description now
  leads with the same framing (your agent writes only your domain; the rest is
  a package you upgrade) on the GitHub About, PyPI, npm, the docs homepage,
  the FAQ and llms.txt. `scripts/check_description.py` also checks the FAQ's
  first answer and the README's first two sections (order, the story's
  180-word limit, the four answers in order, no marketing words), and writes
  the homepage's description quoted.
- All five Python packages (`karni`, `karni-cli`, `karni-payments`,
  `karni-approvals`, `karni-impersonation`) are on PyPI (0.3.1). The README's quickstart installs them with a plain `pip install`;
- **Security: a row outside the requester's row scope stays hidden on every
  response.** An audit probed row-scope denials (a user who may list a
  resource but not one row in it). The row itself was already treated as
  missing everywhere (404 on detail and the write verbs, absent from lists,
  filters, search, ordering, exports and the admin); four paths leaked
  *related* rows and are fixed:
  - a write's response (`PATCH`/`PUT`/`POST …?expand=`), and any response of
    a viewset with `optimize = False` or a `select_related` /
    `prefetch_related` hint, embedded related rows (and listed to-many ids)
    outside the target's read scope. The generated serializers now check
    related rows at render time (`karni.api.related`): no extra query on the
    optimised path, one per related model and page otherwise;
  - an export named an unreadable related row by its natural key (a venue's
    name where the API shows only its id). It now keeps the id, and the
    admin's export names related rows as far as the admin's row scope shows
    them;
  - `?ordering=` on a to-many relation repeated each row once per related
    row, readable or not (and pushed others off the page), and on a forward
    relation sorted by the related model's `Meta.ordering`. Behaviour change
    for API clients: to-many and reverse relations are no longer orderable
    by default, and `?ordering=<relation>` sorts by its key column. An
    explicit `ordering_fields` is unchanged;
  - a relation in explicit `filterset_fields` filtered by the key of a row the
    requester cannot read (200) but refused a missing one (400). Its choices
    are now the readable rows (`KarniFilterSet`), so both answer 400.
- `karni.testing.assert_row_hidden(client, "/api/events/", row, visible=…)`
  proves in one line that a row outside the client's row scope behaves as
  "does not exist" on every API surface: detail and write verbs (compared
  with a missing key), detail actions, the list and its count, filters,
  search, ordering, `?expand=` and id lists from every related resource
  (writes included), and every export format.
  `assert_admin_row_hidden(staff, row, visible=…)` does the same for the
  admin's changelist, change, history and delete views. Each check runs on
  its own (`checks=["export"]`), `probe=` takes a `HiddenRowProbe` subclass,
  and a run that proves nothing (the client cannot list, or sees no row)
  fails with the new code `E616`. `assert_isolated` now runs the same probe on
  the other principal's row (and probes PUT; a 403 on a write passes only when
  a missing row gets 403 too), so tests `karni make test` writes get it
  without a change.
- `karni check` exits 1 when only eslint fails (a raw `<table>` in a page, any
  `karni/*` rule). It printed `FAILED` but exited 0, so CI let it through.
- `karni` commands no longer end in Django's traceback when the project's
  database is not ready. On the host, a command that starts Django first
  checks that the database driver loads, and one that opens the database
  (`migrate`, `seed`, `sync-roles`, `createsuperuser`, `serve --local`,
  `test`, `beat`, `manage`) that the server answers. A missing driver is
  `C012` (install `psycopg[binary]` into the project interpreter, or use
  Docker) and an unreachable database is `C013` (with the address, the
  driver's error, and a note when `.env` is missing or `db` is the compose
  host). Captured commands (`karni context`, `karni types`) are checked only
  after they fail, so they cost nothing when the project works.
  `KARNI_DB_CHECK=false` skips the check. `karni check` still runs the
  frontend checks when the backend cannot start.
- Releases can publish npm with an `NPM_TOKEN` repository secret instead of
  trusted publishing, like `PYPI_API_TOKEN` for PyPI ([releasing](docs/releasing.md)).
- The `karni` command as a container image, `ghcr.io/cbsshekhawat18-lab/karni`
  (linux/amd64 and arm64), built from the PyPI release after every release
  and listed under the repository's Packages. It runs the CLI on machines
  without Python 3.12: `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work"
  ghcr.io/cbsshekhawat18-lab/karni new "Ticket Shop"`.
- `karni`, `karni-cli`, `karni-payments` and `karni-approvals` are on PyPI
  (0.3.1). The README's quickstart installs them with a plain `pip install`;
  installing from a checkout is for unreleased changes only.
- `@karni/ui` and the three module UIs are on npm (0.3.1). The README's
  quickstart installs the frontend with a plain `npm install`, and `karni new`
  no longer says `@karni/ui` is unpublished.
- Tailwind 4 for new projects: `karni new` sets up Tailwind 4 through
  `@tailwindcss/vite`, loading the same `@karni/ui` preset with `@config`, and
  Vite 8. New `@karni/ui/tailwind-v4.css`, imported after Tailwind in a
  Tailwind 4 project, keeps a bare `border` on the `--karni-border` token.
  `@karni/ui` keeps working with Tailwind 3: every Storybook story (light and
  dark) and every page a new project generates render pixel-identical under
  Tailwind 3 and 4. The form and sign-in field gaps no longer use `space-y`
  (Tailwind 4 moved its margin onto the inline label, which ignores it).
- Development tooling: Vite 8, Vitest 5, Storybook 10 (with
  msw-storybook-addon 3) and Tailwind 4 in `@karni/ui` and the module UIs;
  CI and releases on Node 24 (Node 20 is out of support; Vitest 5 needs
  22.12 or later, npm trusted publishing needs npm 11.5); the Pages and
  artifact actions on their current majors. `npm audit` reports nothing, dev
  dependencies included.

## 0.3.1 — 2026-10-20

A patch release: security updates to the development tooling, Vite 6.4 for
new projects, and publishing to PyPI. No public API changes.

- The release workflow publishes to each registry separately:
  `KARNI_PUBLISHING` names the registries that are set up (`pypi`, `npm`,
  `pypi,npm` or `true`), and PyPI uploads one project at a time, core first,
  with `skip-existing`, so a missing trusted publisher cannot half-publish a
  release. The GitHub release carries the npm tarballs too.
- Development tooling upgraded, closing every Dependabot alert (52, all in
  build and test tools, none in what the packages ship): Vite 6.4, Vitest 4.1
  (which drops tinypool), vite-plugin-dts 5 (API Extractor, and with it
  sprintf-js, is no longer installed), typescript-eslint 8 in the module UIs,
  and overrides for `uuid` (Storybook 8) and `postcss-selector-parser`
  (Tailwind 3). New projects get Vite 6.4 and the same override. The
  generated type declarations and Tailwind's output are unchanged. Vitest 4
  hands a jsdom `FormData` to Node's fetch without file names, so the UI test
  setup restores them the way a browser sends them.

## 0.3.0 — 2026-10-20

See [docs/migrations/0.3.md](docs/migrations/0.3.md) for the two breaking
changes and how to upgrade.

- Membership scoping and generated tests, from the Social Stats case study:
  `own` takes an owner path through a many-to-many
  (`owner_field = "workspace__members"`), now documented as the way to scope
  rows to a workspace's members; the test factories accept one row for a
  many-to-many, so `assert_crud` and `assert_isolated` drive it; a new
  check, `E214`, resolves every path a role's grants filter on (owner paths,
  scope paths, custom scopes) at boot, so a scope that names a missing path
  fails `karni check` instead of answering 500; `karni make test` says, in
  its output and the test file, why it leaves `assert_isolated` out.
- Django 5.2 LTS: karni requires `Django>=5.2.8,<5.3` (5.1 is out of
  support; pip-audit reported ten unpatched advisories against 5.1.15) and
  django-unfold 0.110. Python 3.14 is supported and tested — on Django 5.1
  every admin page failed under 3.14. Projects pinned to Django 5.1 upgrade
  Django with karni; no project code changes were needed in EventHub,
  Social Leads or the modules. Dropping Django 5.1 is a minor-release
  change under the [stability promise](docs/stability.md), released as 0.3.0.
- `karni seed` can run again on a seeded database. Each run is a new process
  that draws the same UUID keys from the same seed, so a second run failed
  with `E612` on the primary key (found by running the README quickstart, then
  adding a model and seeding again). A key an earlier run used is now replaced
  by one derived from it; an empty database still gets the same rows.
- A generated reference: `scripts/gen_reference.py` writes `docs/REFERENCE.md`
  (every command, base class, `class Karni` key, setting, component, hook,
  module, error code, make target and slash command, with each capability's
  status) and the README's generated blocks from the source, and CI fails when
  either is stale. `karni.meta.OPTIONS` (and a module's `KARNI_OPTIONS`) now
  documents each `class Karni` key; the generator fails on a key that code
  reads but no list declares. Every `@karni/ui` export has a one-line JSDoc.
- The README is rewritten: a demo recorded from a real quickstart run
  (`scripts/demo/`), a cheat sheet, the generated command table and per-area
  reference, an honest comparison and status. The quickstart (README and
  docs) adds `karni make page login --kind login`: a new project had no
  sign-in page for the React app. Package READMEs link absolutely, so their
  links work on PyPI.

## 0.2.0 — 2026-10-20

See [docs/migrations/0.2.md](docs/migrations/0.2.md) for every breaking
change and its migration note.

- Roles as data: `KARNI_ROLES`, `karni sync-roles`, `user.can()`,
  `@requires()`, `Can("app.model:action")` in `access` declarations
  (ADR 0002).
- Row-level scoping (ADR 0002, P2): `access = Granted()` is the default
  `karni make viewset` writes and scopes rows by the roles' grants; the
  admin shows only the rows the user's grants reach; `scope_exempt` with a
  reason that `karni check` lists; `assert_isolated` gains the `grant`
  dimension and probes expansion, filters, search, ordering and the admin.
- Welcome page: `/` on first boot (`karni.welcome.welcome_urls()`, mounted
  last by the scaffold) shows the project live — models with admin and API
  links, modules, seven status checks each with the command that fixes a
  cross, the `karni context` output and the first agent prompt. `DEBUG`
  only, gone once the project owns `/`; `karni.E505` guards production.
- Field-level visibility (ADR 0002, P3): `class Karni: field_roles` hides
  fields per role on the API (absent, never `null`), in `?expand=`, in the
  per-role OpenAPI schema and in the admin; write-protected fields are
  refused naming the roles that may; `?ordering=`, filters and `?search=`
  ignore hidden fields; `@karni/ui` refetches the schema on identity
  change; `assert_crud` checks visibility. `?ordering=` now accepts only
  serializer-visible fields; `search_fields` may not name a write-only
  field (`E131`); `E212` validates `field_roles`.
- Change history (ADR 0002, P4): the `karni.audit` app records, for models
  that opt in with `class Karni: audit = True`, who changed what from what
  to what, captured at the model layer so the API, admin, commands and the
  shell all leave the same entry; sensitive fields are redacted; surfaced on
  the admin History tab, `GET /<resource>/<id>/history/` and
  `<ChangeHistory/>`; retention pruning off by default; `karni check` flags
  `update()`/`bulk_update()` on audited models (`audited-bulk-write`, `K113`).
- Permission matrix (ADR 0002, P5): Roles → *Permission matrix* in the
  admin changes who may do what with no deploy — roles across, models down,
  a scope selector per action, bulk selectors, a confirmation diff — with
  the guard rails (system roles keep their declared grants, nobody grants
  what they do not hold, nobody removes their own last permission to change
  permissions) and the matrix's own change history; *Effective permissions*
  answers "why can this person see this?" per user; the same as an API
  under `api/auth/permissions/` for custom UIs, fixtures and tests
  (`E213`). `RolePermission.origin` tells the sync which grants the matrix
  owns; `KARNI_MATRIX_EXCLUDE`.
- Import and export (ADR 0002, P6): `GET /<resource>/export/?format=csv|xlsx`
  on every resource — the list as the request sees it, filters and scope and
  field visibility included, relations as natural keys — and a four-step
  import (`/<resource>/import/…`): upload, map columns (remembered per model
  per user), the mandatory dry run with exact counts and per-row errors,
  then one transaction recorded as one audit batch; large files run in
  Celery with progress; per-model hooks in `class Karni` (`natural_key`,
  `import_key`, `import_lookup`, `import_transform`, `after_import`); a
  downloadable template per model. Export actions and an Import page on
  every Karni admin; `<ResourceImport/>` and export buttons on
  `<ResourceTable>` in `@karni/ui`. `KARNI_IMPORT_INLINE_ROWS`,
  `KARNI_IMPORT_MAX_ROWS`, `KARNI_EXPORT_MAX_ROWS`; `E801`–`E803`.
- Write interception: every `BaseModel` save and delete sends
  `karni.signals.pre_write`; a receiver that raises `KarniWriteDeferred`
  stops the write before any SQL — the API answers 202 with its payload,
  the admin shows its message. The hook behind the new `karni-approvals`
  module (M1): `class Karni: requires_approval = [...]` turns a maker's
  guarded change into a pending change a second person approves or
  rejects (never the maker, in code), with per-model approvals count,
  approver roles and timeouts, an admin queue, `/api/pending-changes/`,
  Celery notifications, every decision in `karni.audit`, and
  `@karni/approvals-ui` (`<ApprovalsQueue/>`, `<ApprovalsBadge/>`).
- Vetoes: `karni.vetoes.register_veto` refuses an action at the API and
  admin gates after the access declaration admitted it (a maintenance
  freeze, a read-only tenant); `KarniAdminMixin.vetoed()`. The hook behind
  the new `karni-impersonation` module (M2): "log in as user" for support
  with an explicit `impersonate` permission never implied by staff status,
  no privilege escalation (a target holding anything the actor lacks is
  refused), a banner naming both identities with a one-click exit, a
  session record, every write attributed to both identities in
  `karni.audit` (the row's actor is the target, the batch's actor the
  impersonator), a configurable time limit, a hard block on deleting,
  exporting and payment changes while impersonating, the target notified
  and a reason required by default, a threat model in the README;
  `karni.audit.capture.within_batch`; `@karni/impersonation-ui`
  (`<ImpersonationBanner/>`); `useAuth().adoptTokens` in `@karni/ui`.
- `karni check` and the architecture suite now scan a project's apps
  without `BASE_DIR` (the audit's "enforcement scans zero files" finding).
- The launch audit's remaining findings: `karni migrate` creates `pg_trgm`
  (`?search=` no longer 500s on a fresh PostgreSQL); `KARNI_CACHE=locmem`
  runs a project without Redis and the quickstart uses it, with pytest in
  its install line; `karni.welcome.media_urls()` serves uploads in
  development; `karni --version`; `karni doctor` with the venv outside the
  project; `karni context` (and the MCP `context` tool) from the interpreter
  running karni-cli; `karni serve`/`karni worker` pass SIGTERM on to the
  server; `karni test` says when pytest is missing (`C011`); `karni check`
  runs the frontend's ESLint next to jscpd; the scaling check also measures
  every list with `?expand=`; a `KARNI_*` dotted path that cannot be imported
  is `E506` naming the setting (`E507` for `KARNI_CACHE`); generated detail
  pages expand their relations; a required relation left empty says
  "Required" and an optional one clears; `[tool.karni] baseline` in a new
  project's pyproject, so `karni upgrade` never reports changes a fresh
  scaffold already satisfies; `LOGIN_REDIRECT_URL` defaults to the admin;
  the seed login says "superuser"; the two schema warnings are gone. The
  cosmetics too: choice labels from the schema's choice list instead of raw
  markdown help text (`FieldDef.enumLabels`), one casing for every table
  header, `karni rules` trimmed (402 cl100k tokens, measured), and the
  admin's *All* rows counted once. The EventHub Playwright journeys ran
  (three passed) and every package built, installed into a clean venv and
  dry-run published.
- Every `BaseViewSet` declares `access`; relation fields and `?expand=`
  follow the target's read scope; query budgets fail tests.
- Errors that teach: every error carries a code, `karni explain <code>`,
  the generated error reference.
- `karni make …` generators and the project runners (`karni serve`,
  `migrate`, `test`, `seed`, …); `karni upgrade` with codemods.
- The documentation site, the EventHub reference application, release
  automation, the brand assets.

## 0.1.0

The first cut: `BaseModel` and scopes, the `access` declaration, generated
serializers and viewsets, the derived admin, accounts, events and schedules,
`@karni/ui`, the scaffold and the agent adapters.
