# @karni/ui

Schema-driven React components for [Karni](https://github.com/cbsshekhawat18-lab/karni#readme) backends. Point it at a
Karni API's OpenAPI schema and you get working tables, forms, detail views and
auth, plus the themable primitives they are built from, without regenerating boilerplate.

- **Resource components**: `ResourceTable`, `ResourceForm`, `ResourceDetail`,
  `ResourceSelect` render themselves from the backend schema (`/api/schema/`).
- **Hooks**: `useResourceList`, `useResourceItem`, `useResourceMutations`,
  `useSchema` on TanStack Query, with a shared `karniKeys` key factory.
- **Auth**: `AuthProvider`, `useAuth`, `AuthGuard`, `usePermission` for Karni's
  JWT or session auth modes.
- **Primitives**: Button, Input, Textarea, Select, Checkbox, Switch, Label,
  Tabs, DropdownMenu, Skeleton. They are Radix-based, token-themed, `forwardRef`
  and `className`-mergeable.

The package ships **dual ESM/CJS** output plus `.d.ts` files: `import` resolves
`dist/index.js`, `require()` resolves `dist/index.cjs` (same for
`@karni/ui/tailwind-preset`, whose CJS form exposes the preset as `.default`).
The `@karni/ui/eslint-plugin` export stays ESM-only (flat config). Peer
dependencies are resolved by your bundler or by Node.

## Install

```sh
npm install @karni/ui @tanstack/react-query @tanstack/react-table react-hook-form @hookform/resolvers zod
```

Peer dependencies: `react` / `react-dom` (18 or 19), `@tanstack/react-query` v5,
`@tanstack/react-table` v8, `react-hook-form` v7, `@hookform/resolvers` and `zod` v3.
The project also needs `tailwindcss` (v3.4+ or v4) as a build tool. It is a
devDependency, which is how `karni new` sets it up. It compiles the classes the
components use and is never imported at runtime, so it is not a peer.

## Quick start

```tsx
import { AuthProvider, KarniProvider, ResourceTable, createKarniClient } from "@karni/ui";
import "@karni/ui/styles.css";

const client = createKarniClient({ baseUrl: "/api" });

export function App() {
  return (
    <KarniProvider client={client}>
      <AuthProvider>
        <ResourceTable resource="events" />
      </AuthProvider>
    </KarniProvider>
  );
}
```

`KarniProvider` creates a TanStack `QueryClient` when you do not pass one
(`queryClient` prop is the escape hatch). `AuthProvider` reads the auth mode from
the schema root (`x-karni-auth-mode`). Override it with `mode="jwt" | "session"`.

## Styling

Every visual value in every component resolves from a `--karni-*` CSS custom
property defined in `@karni/ui/styles.css`:

| Family             | What it holds                                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--karni-color-*`  | colours: background, foreground, card, popover, primary, secondary, muted, accent, destructive, border, input, ring, overlay, chart-1 … chart-5, and the derived `-foreground`, `-hover`, `-subtle` and `-border` shades |
| `--karni-space-*`  | the spacing scale: `--karni-space-unit` (0.25rem), or any step `--karni-space-<n>` (`--karni-space-4` is 1rem)                                                                                                           |
| `--karni-radius-*` | `sm`, `md`, `lg`, `xl`, `full` (derived from `--karni-radius`)                                                                                                                                                           |
| `--karni-font-*`   | `sans`, `mono`, `size-xs` … `size-2xl` with `leading-*`, `weight-*`, `tracking-*`                                                                                                                                        |
| `--karni-shadow-*` | `sm`, `md`, `lg` (and bare `--karni-shadow`)                                                                                                                                                                             |
| other              | `--karni-z-*`, `--karni-opacity-*`, `--karni-duration` and `--karni-ease` (0ms under `prefers-reduced-motion`), `--karni-border-width*`, `--karni-ring-*`, `--karni-table-max-height` (ResourceTable's scroll box)       |

The Tailwind preset maps its scales onto these properties, so `bg-primary`,
`p-4` or `rounded-md`, in a component or in your own code, reads them. Import
the stylesheet once, then wire Tailwind (3.4 or later) so the classes exist in
your build. The rule `karni/no-style-literals` (in the ESLint plugin) and a
test that compiles every component class keep literals out of the library.

### Tailwind v3 (preset)

```ts
// tailwind.config.ts
import karniPreset from "@karni/ui/tailwind-preset";

export default {
  presets: [karniPreset],
  content: [
    "./src/**/*.{ts,tsx}",
    // So Tailwind sees the classes used inside @karni/ui:
    "./node_modules/@karni/ui/dist/**/*.js",
  ],
};
```

```ts
// main.tsx
import "@karni/ui/styles.css";
import "./index.css"; // your @tailwind base/components/utilities file
```

### Tailwind v4 (what `karni new` sets up)

Keep the same `tailwind.config.ts` (the preset and the content paths) and load
it with `@config`. Add the `@tailwindcss/vite` plugin to `vite.config.ts`:

```css
/* src/index.css (main.tsx imports @karni/ui/styles.css first) */
@import "tailwindcss";
@import "@karni/ui/tailwind-v4.css";
@config "../tailwind.config.ts";
```

`@karni/ui/tailwind-v4.css` keeps a bare `border` on `--karni-color-border`,
as Tailwind 3 does (Tailwind 4 defaults borders to `currentColor`), and points
Tailwind 4's default transition timing at `--karni-duration` and
`--karni-ease`. A Tailwind 3 project must not import it. With it, every
Storybook story and the pages `karni new` generates render pixel-identical
under Tailwind 3 and 4, light and dark.

#### Alternative: no JavaScript config

Map the tokens in CSS instead of loading the preset. This covers colours,
spacing, type, radius, shadow and motion. The named stacking classes
(`z-popover`, …) and the token-backed opacity steps come only with the preset.

```css
/* app.css */
@import "tailwindcss";
@import "@karni/ui/styles.css";
@import "@karni/ui/tailwind-v4.css";

/* Scan the library's shipped output for class names. */
@source "../node_modules/@karni/ui/dist";

/* Dark mode is class-based: add `dark` to <html> (or any ancestor). */
@custom-variant dark (&:where(.dark, .dark *));

@theme inline {
  --color-background: var(--karni-color-background);
  --color-foreground: var(--karni-color-foreground);
  --color-card: var(--karni-color-card);
  --color-card-foreground: var(--karni-color-card-foreground);
  --color-popover: var(--karni-color-popover);
  --color-popover-foreground: var(--karni-color-popover-foreground);
  --color-primary: var(--karni-color-primary);
  --color-primary-foreground: var(--karni-color-primary-foreground);
  --color-primary-hover: var(--karni-color-primary-hover);
  --color-secondary: var(--karni-color-secondary);
  --color-secondary-foreground: var(--karni-color-secondary-foreground);
  --color-secondary-hover: var(--karni-color-secondary-hover);
  --color-muted: var(--karni-color-muted);
  --color-muted-foreground: var(--karni-color-muted-foreground);
  --color-muted-subtle: var(--karni-color-muted-subtle);
  --color-accent: var(--karni-color-accent);
  --color-accent-foreground: var(--karni-color-accent-foreground);
  --color-destructive: var(--karni-color-destructive);
  --color-destructive-foreground: var(--karni-color-destructive-foreground);
  --color-destructive-hover: var(--karni-color-destructive-hover);
  --color-destructive-subtle: var(--karni-color-destructive-subtle);
  --color-destructive-border: var(--karni-color-destructive-border);
  --color-border: var(--karni-color-border);
  --color-input: var(--karni-color-input);
  --color-ring: var(--karni-color-ring);
  --color-overlay: var(--karni-color-overlay);
  --color-chart-1: var(--karni-color-chart-1);
  --color-chart-2: var(--karni-color-chart-2);
  --color-chart-3: var(--karni-color-chart-3);
  --color-chart-4: var(--karni-color-chart-4);
  --color-chart-5: var(--karni-color-chart-5);
  --spacing: var(--karni-space-unit);
  --radius-sm: var(--karni-radius-sm);
  --radius-md: var(--karni-radius-md);
  --radius-lg: var(--karni-radius-lg);
  --radius-xl: var(--karni-radius-xl);
  --font-sans: var(--karni-font-sans);
  --font-mono: var(--karni-font-mono);
  --text-xs: var(--karni-font-size-xs);
  --text-xs--line-height: var(--karni-font-leading-xs);
  --text-sm: var(--karni-font-size-sm);
  --text-sm--line-height: var(--karni-font-leading-sm);
  --text-base: var(--karni-font-size-base);
  --text-base--line-height: var(--karni-font-leading-base);
  --text-lg: var(--karni-font-size-lg);
  --text-lg--line-height: var(--karni-font-leading-lg);
  --text-xl: var(--karni-font-size-xl);
  --text-xl--line-height: var(--karni-font-leading-xl);
  --text-2xl: var(--karni-font-size-2xl);
  --text-2xl--line-height: var(--karni-font-leading-2xl);
  --font-weight-normal: var(--karni-font-weight-normal);
  --font-weight-medium: var(--karni-font-weight-medium);
  --font-weight-semibold: var(--karni-font-weight-semibold);
  --font-weight-bold: var(--karni-font-weight-bold);
  --tracking-tight: var(--karni-font-tracking-tight);
  --tracking-wide: var(--karni-font-tracking-wide);
  --shadow-sm: var(--karni-shadow-sm);
  --shadow-md: var(--karni-shadow-md);
  --shadow-lg: var(--karni-shadow-lg);
}
```

### Theming and dark mode

Override any token after importing the stylesheet. Colours take any CSS colour
(`hsl()`, `oklch()`, hex, or `var()` of your own design system's variable):

```css
:root {
  --karni-color-primary: oklch(0.55 0.22 285);
  --karni-color-primary-foreground: white;
  --karni-radius: 0.75rem;
  --karni-space-unit: 0.225rem; /* a denser spacing scale everywhere */
  --karni-font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
}
.dark {
  --karni-color-primary: oklch(0.7 0.18 285);
}
```

The derived shades (`-hover`, `-subtle`, `-border`) follow the colour they
derive from unless you set them too.

Dark mode is the `dark` class on `<html>`. `ThemeProvider` manages it: it
follows the system until the user chooses, keeps the choice per browser, and
`ThemeToggle` is a button that cycles Light, Dark and System. The first paint
needs the theme before React starts: in a Vite app, `karniTheme()` puts
`KARNI_THEME_SCRIPT` first in `index.html`'s `<head>` (a project from
`karni new` has all three wired already):

```ts
// vite.config.ts
import { karniTheme } from "@karni/ui/vite";
export default defineConfig({ plugins: [react(), karniTheme()] });
```

```tsx
<ThemeProvider>
  <App /> {/* <ThemeToggle /> in the header */}
</ThemeProvider>
```

Without Vite, put `KARNI_THEME_SCRIPT` in an inline `<script>` in `<head>`
yourself.

The Django side of a Karni project reads the same tokens: the admin and the
welcome page load a copy of this stylesheet, so the same overrides, added to
the admin's `UNFOLD["STYLES"]`, retheme the admin too
([admin theming](https://cbsshekhawat18-lab.github.io/karni/admin/#theming)).

The 0.3 names (`--karni-primary: 262 83% 58%`, an HSL triplet) still work:
each `--karni-color-*` defaults to `hsl()` of its 0.3 name. They are
deprecated in 0.4 and removed in 1.0 ([migration note](https://cbsshekhawat18-lab.github.io/karni/migrations/0.4/)).

### Adopting your design system: `karni ui detect`

A project that already has a design system does not retype it. Run
`karni ui detect` in the frontend (or the Karni project root):

```sh
karni ui detect --dry-run   # the report and the file, nothing written
karni ui detect             # write src/karni-theme.css (and wire it in)
```

It maps the first theme it finds onto the tokens above and writes one file
the project owns, `karni-theme.css`, imported after `@karni/ui/styles.css`:

1. **shadcn/ui** (`components.json`): every token references the project's
   own variable, `--karni-color-primary: var(--primary)` (or
   `hsl(var(--primary))` for shadcn's Tailwind 3 HSL channels), declared on
   `:root, .dark` so the project's theme and dark mode flow through live. It
   also writes `karni-primitives.tsx`, registering the project's shadcn
   components as Karni's primitives (below).
2. **A Tailwind theme**: `@theme` blocks (Tailwind 4), or the
   `tailwind.config` Node evaluates in the project (Tailwind 3).
3. **A Material UI, Chakra UI or Mantine theme**: the literal values of its
   `createTheme` / `extendTheme` / `createSystem` call.
4. **Nothing**: Karni's defaults, listed commented, for you to edit.

The report lists every token mapped (from, to, value) and every value not
mapped with the reason (a palette is never turned into `primary`
silently: the line to add is printed). Re-running never overwrites a file
you edited unless you pass `--force`. `--json` prints the report for agents.
See [Theming](https://cbsshekhawat18-lab.github.io/karni/theming/) for each
source in detail.

## Unhappy states

Every component words failures the same way, through `describeError(error,
{ action, resource })`: a 403 reads "You can't delete events", a dropped
connection "You're offline", a 5xx "Something went wrong on our side". A status
code is never shown, but the server's own explanation is, when it gave one. The
building blocks are exported for your own screens:

- `ErrorState`: what failed and what to do, with "Try again" when retrying can
  help (`onRetry`, `retrying`), announced to screen readers.
- `PermissionDenied`: which action the role does not allow, in plain words.
- `PendingButton`: disabled while `pending`, shows progress after 500ms
  (`SLOW_AFTER_MS`) and keeps its width.
- `useDelayedFlag(active)` (true once work has run for 500ms) and
  `useOnlineStatus()`.

A visible field with no value (`null`, `""`, an empty list) renders the same
everywhere, as `EmptyValue`: a muted en dash that screen readers read as
"empty" (`label` changes the word). ResourceTable's cells, ResourceDetail's
rows and ChangeHistory's before/after values all use it. A field the role may
not read (`Karni.field_roles`) is different: it is absent from the per-role
schema and from the payload, so it gets no row and no cell at all. It never
gets a dash that would hint it exists.

### Replacing a state: `slots`

The resource and auth components take `slots`, an object of components that
replace one part each. `defaultXSlots` (`defaultResourceDetailSlots`, ...)
holds Karni's own, so a project can wrap one instead of rewriting it. Every
`Error` slot receives `ErrorSlotProps` (`error`, `context`, `onRetry`,
`retrying`), so one project error panel fits all of them.

```tsx
<ResourceDetail
  resource="events"
  id={id}
  slots={{ Error: MyErrorPanel, EmptyValue: ({ field }) => <i>not set</i> }}
/>
```

| Component        | Slots                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------------- |
| `ResourceDetail` | `Loading`, `Error` (+ `back`), `NotFound`, `EmptyValue`, `DeleteDialog`, `Deleted`       |
| `ResourceImport` | `Loading`, `Error`, `Progress`, `Summary`, `Problems`, `ConfirmCommit`                   |
| `ChangeHistory`  | `Loading`, `Error`, `Empty`, `Entry`                                                     |
| `LoginForm`      | `Error` (+ `id` for `aria-describedby`, and `described`: the failure worded for sign-in) |
| `AuthGuard`      | `Anonymous` (not signed in: a sign-in prompt), `Denied` (signed in, role lacks access)   |

Loading placeholders take the real layout from the start (ResourceDetail
draws one row per field the schema declares, plus the title and action
buttons) but are drawn only once loading is slow (500ms), so a fast load
never flashes them and nothing moves when the data arrives.

## Resource components

Every resource component takes the backend's resource name (the router prefix)
and renders from the schema. These are defaults. Each one exposes override
props, and you can always drop down to the hooks + primitives.

```tsx
// Table: server-driven pagination, sorting, search and filters
<ResourceTable
  resource="events"
  columns={[{ field: "title" }, { field: "starts_at" }]} // optional override
  onRowClick={(row) => navigate(`/events/${row.id}`)}
/>

// Form: fields, labels, and Zod validation derived from the schema.
// No `id` → create; with `id` it loads the item and PATCHes dirty fields.
<ResourceForm
  resource="events"
  onSuccess={(created) => navigate(`/events/${created.id}`)}
  fields={{ internal_notes: { hidden: true }, venue: { label: "Location" } }}
/>

// Detail + relation picker
<ResourceDetail resource="events" id={eventId} />
<ResourceSelect resource="venues" value={venueId} onChange={setVenueId} />
```

`ResourceDetail` also renders its own header and actions:

```tsx
<ResourceDetail
  resource="events"
  id={eventId}
  title={(event) => event.title} // a function waits for the record (a placeholder stands in)
  back={
    <Button variant="outline" onClick={() => navigate("/events")}>
      Back to events
    </Button>
  }
  onEdit={(event) => navigate(`/events/${event.id}/edit`)}
  canEdit={hasRole("organizer")} // or (event) => boolean
  enableDelete // asks for confirmation; a refusal is shown in the dialog
  canDelete={(event) => event.status === "draft"}
  onDeleted={() => navigate("/events")}
/>
```

A 404 reads "Couldn't find this event" with the `back` action and no retry.
Karni answers 404 for a record outside the user's scope too, so the words never
say the record exists. A 403 reads "You can't view this event". Other failures
offer "Try again" (it refetches the schema too when that is what failed).
Offline, it says so and reloads when the connection returns. `resourceLabel`
("event") names the resource in these messages when the router prefix does not
singularize well.

`ResourceImport` shows no upload form when the role may not import ("You
can't import events"). A failed upload keeps the chosen file, moves focus to
the error and offers "Try again" when it can help. A preview's rows with errors
are a captioned table. Commit asks for confirmation with the counts
(created, updated, unchanged, failed). Background progress is a
`progressbar` announced by the quarter, not every poll. `ChangeHistory` words
its failures the same way ("You can't view the history of this event").

Audit fields never lead the screen. These are the `AUDIT_FIELDS` (`id`,
`created_at`, `updated_at`, `created_by`, `updated_by`), which every Karni
resource carries.
`ResourceTable` hides their columns by default (domain fields come first, in
schema order, and rows are still keyed by `id`). Show one by naming it in `columns`
(`{ field: "created_at" }`), or show all of them after the domain columns with
`showAuditFields`. `ResourceDetail` lists them last, in a muted "Record" group,
and still honours `fields` overrides for them. `ResourceForm` never renders them
(they are read-only).

A create form starts from the schema's defaults (a model's `default=`), and a
cleared optional field is left out of the request rather than sent as `null`
(`null` is sent only for nullable fields).

Validation schemas are generated at runtime with `zodFor(schema, "create" | "update")`.
`displayLabel(obj)` picks a human label for relation objects.

### ResourceTable in every state

Each state is its own screen, and each is a slot you can replace:

| State                         | What the user sees                                                                                                                      | Slot           |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| first load                    | the real layout in outline: header with the real column count, a full page of rows, the pagination row. Nothing moves when data arrives | `Loading`      |
| no records yet                | "No events yet", and the create action when `onCreate` is set and the role may create                                                   | `NoRecords`    |
| nothing matches               | "No events match", what is narrowing the list (search, each filter) and "Clear filters" (pinned `params` stay)                          | `NoResults`    |
| the list failed               | `ErrorState`: plain words, "Try again" when it can help                                                                                 | `Error`        |
| a refresh failed              | the rows stay, and one line above them says so, with "Try again"                                                                        | `RefetchError` |
| 403 on the list               | "You can't view events", no retry (4xx are not retried, except 408 and 429)                                                             | `Forbidden`    |
| offline                       | a line over the rows it has, or the offline panel. The list reloads by itself when the connection is back                               | `Offline`      |
| slow (500ms, `SLOW_AFTER_MS`) | a progress bar, dimmed rows, "Loading events…" announced. The clicked control shows progress and ignores repeat clicks                  | none           |

The other slots are `Pagination`, `BulkActions` and `RowCard`. Every slot
receives the props type exported next to it (`ResourceTableLoadingProps`,
`ResourceTableNoResultsProps`, …, while `Error` and `RefetchError` take
`ErrorSlotProps`), and the defaults are exported as
`defaultResourceTableSlots`, so a replacement can wrap one:

```tsx
<ResourceTable
  resource="events"
  onCreate={() => navigate("/events/new")} // "New event" in the toolbar and the empty screen
  slots={{
    NoRecords: (props) => <OurEmptyState {...props} />,
    Error: (props) => <defaultResourceTableSlots.Error {...props} />,
  }}
/>
```

The `empty` prop still replaces both empty screens, but the `NoRecords` and
`NoResults` slots are preferred, because they tell "nothing yet" from
"nothing matches". `resourceLabel` ("events") and `itemLabel` ("event") word
every message. By default they come from the resource name.

**Permissions.** Columns follow the role's schema (a field the role cannot
read is not in its schema, so its column and filter are absent). Row actions
follow the schema's `x-karni-access` rules for the signed-in user (from
`AuthProvider`): Edit shows on the rows the update rule allows (for example
`Owned("organizer") | HasRole("staff")` shows it on the user's own rows),
Delete on the rows the delete rule allows, and the create action only when
the create rule allows it. Rules only the server can answer (grants, custom
`Where` functions) keep the action, and a refusal is reported in plain words.
`canCreate`, `canEdit` and `canDelete` (a boolean, or a function of the row)
replace the schema's answer.

**Deletes and bulk actions.** `enableDelete` asks in a dialog ("Delete
“Spring Gala”?"). A failure is reported in the dialog, with "Try again" when
it can help. A destructive bulk action (or one with `confirm: true`) asks
first with the count ("Delete 3 events?"). An action may return a promise:
the button shows progress after 500ms, the rows that succeeded are
deselected, and a resolved `{ failed: [{ id, reason }] }` marks each failed
row with its reason. `onClick(ids)` returning nothing keeps working as
before. "Select all" selects the rows on this page, and the bar says so when
more rows match.

**At real size.** Only the current page is fetched: a page size choice
(`pageSizeOptions`, default 10/25/50/100), first, previous, next, last and a
page number to jump to. Wide tables scroll inside their own box (the page
never scrolls sideways): the header sticks, the first column stays put and
shows an edge once the table scrolls. The box is at most
`--karni-table-max-height` (70vh) tall. Set it to `none` to let the page
scroll. The "View" menu toggles compact rows and hides columns, and both are
remembered per user (in `localStorage`, under the signed-in user's id).
`density` / `onDensityChange` control density from outside. Below
`cardBreakpoint` (640px of the table's own width, not the viewport's, and `0`
turns cards off) each row is a card: its title, then label and value pairs,
with its checkbox and actions, and a sort choice above the cards. The sort
choice keeps keyboard focus while the sorted page loads (the list says it is
busy instead), and when the control that opened a dialog is gone afterwards
(a deleted row, the bulk toolbar once its action ran) focus lands on the list,
as it lands on the scroll region in the table layout.

**View state in the URL.** Page, page size, ordering, search and filters are
query parameters under the table's namespace (`?events.page=2&events.ordering=-starts_at`),
so a view can be shared and Back returns to the previous one. A value equal
to the default is left out, and pinned `params` never appear. `urlNamespace`
keeps two tables on one page apart, `syncUrl={false}` keeps the view in
component state, and `stateStore` plugs in a router. A store reads the
current query values, writes changes (`null` removes a key, `push` adds a
history entry) and reports outside changes:

```tsx
// TanStack Router: the table's keys live in the route's search params.
function useRouterTableStore(): ResourceTableStateStore {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const navigate = useNavigate();
  return React.useMemo(
    () => ({
      read: () =>
        Object.fromEntries(Object.entries(search).map(([key, value]) => [key, String(value)])),
      write: (changes, { push }) =>
        void navigate({
          to: ".",
          replace: !push,
          search: (previous: Record<string, unknown>) => {
            const next = { ...previous };
            for (const [key, value] of Object.entries(changes)) {
              if (value === null) delete next[key];
              else next[key] = value;
            }
            return next;
          },
        }),
      // The store object changes with `search`, so the table re-reads it.
      subscribe: () => () => undefined,
    }),
    [search, navigate],
  );
}
```

**Keyboard and screen readers.** The table is a WAI-ARIA grid, named by a
caption (`caption`, default the capitalised `resourceLabel`). The whole table
is one Tab stop, so a 50-row page costs one Tab press instead of one per
control. Tab enters at the first row (or at the cell you left) and the next
Tab leaves the table. Inside, the arrow keys move between rows and cells,
Home and End go to the ends of a row, and Ctrl+Home and Ctrl+End go to the
first and last cell of the grid. Each control in a cell is a stop of its own:
the checkbox, the row's button, links, Edit, Delete and your `rowActions`. A
control keeps its own keys: a button activates, a menu trigger opens its menu
with ArrowDown, and Ctrl or Cmd+Enter opens a link in a new tab. On a cell,
Enter opens the row (`onRowClick`) and Space selects it (`bulkActions`).
Enter on a row's checkbox opens the row too. Sortable headers are buttons
with `aria-sort` in the grid's first row. Each checkbox is named after its row
("Select Spring Gala"), and a selected row has `aria-selected`. The mouse
works as before. `keyboardNavigation="native"` turns the grid off: a plain
table where every control is its own Tab stop and the scroll box is
focusable. Below `cardBreakpoint` the cards are a list, and their controls
are Tab stops as before. Page changes, sorting, the selection count and slow
loading are announced in a polite live region. Errors are announced as
alerts.

### ResourceForm: states, errors and the keyboard

- **Loading** draws the form's own layout: once the schema is known (edit
  mode while the row loads) it has the real rows, labels and submit row, so
  nothing moves when the values arrive.
- **A failed load** (schema or row) is an `ErrorState` with "Try again". A 403
  on the row reads "You can't edit this event" (`PermissionDenied`). Fields a
  role may not see or write are absent from its schema, so the form has no
  row for them: no blank row, no dash.
- **Validation runs when a field loses focus**, not on every keystroke. A
  field that shows an error re-checks on every change, so the error clears as
  soon as it is fixed. `validationMode` and `reValidateMode` (react-hook-form's
  `mode` / `reValidateMode`) change it.
- **Server errors** land on their field for every DRF shape (field lists,
  strings, nested serializers, list serializers, `non_field_errors`, `detail`,
  keys the form does not show). When more than one thing fails, a summary at
  the top lists them, each a link to its field, and takes focus. With one
  failing field, focus moves to it. Errors are announced, and every control
  carries `aria-invalid`, `aria-describedby` (help text and error) and, where
  its role allows, `aria-required`.
- **Any other failure** (offline, 401, 403 "You can't save this event", 409
  "This changed while you were working" with "Load the latest version", 429,
  5xx) is a banner in plain words, with "Try again" when it can help. **The
  typed values are never lost**, whatever the failure.
- **Submitting** disables the fields and the button (`PendingButton`: progress
  after 500ms, same width). Enter submits from a one-line input, and Ctrl/Cmd+Enter
  from anywhere (a textarea included). Enter inside an open relation picker
  chooses an option. The first field takes focus on create, and `autoFocus`
  changes that. Edit mode does not focus a field unless asked.

Replace any state through `slots` (`Loading`, `Error`, `Forbidden`,
`ErrorSummary`, `SubmitError`). The defaults are exported as
`defaultResourceFormSlots` to wrap. `submitLabel` renames the button and
`resourceLabel={{ singular: "person", plural: "people" }}` fixes the
resource's name in messages.

**Unsaved changes.** A dirty form warns before the page unloads
(`guardUnsavedChanges={false}` opts out). In-app navigation belongs to your
router: `useUnsavedChangesGuard()` holds the state and gives the router's
blocker its answer. With TanStack Router (what `karni new` sets up):

```tsx
import { useBlocker, useNavigate } from "@tanstack/react-router";
import { ResourceForm, useUnsavedChangesGuard } from "@karni/ui";

function EditEvent({ id }: { id: string }) {
  const navigate = useNavigate();
  const guard = useUnsavedChangesGuard();
  // Asks "You have unsaved changes. Leave without saving them?" while dirty.
  useBlocker({ shouldBlockFn: guard.shouldBlock, enableBeforeUnload: false });
  return (
    <ResourceForm
      resource="events"
      id={id}
      onDirtyChange={guard.setDirty}
      onSuccess={() => navigate({ to: "/events/$id", params: { id } })}
    />
  );
}
```

ResourceForm reports itself clean just before `onSuccess`, so navigating there
is never blocked. `useUnsavedChangesGuard({ confirm })` swaps
`window.confirm` for your own dialog, and `useUnsavedChangesGuard({ dirty })`
guards a form of your own.

### ResourceSelect: thousands of options

- Options load a page at a time from the related list (its own `next` link,
  page-number or cursor), more as the list scrolls, through "Load more", or
  when the keyboard reaches the end. Nothing fetches every row, and long lists
  render only the rows in view. The list says how many there are: "Showing 50
  of 10,000 — type to narrow".
- Typing searches (`?search=`, debounced by `searchDebounceMs`), keeping the
  previous results on screen and saying "Searching…". A related viewset with
  no `search_fields` documents no `search` parameter. Then typing narrows the
  loaded rows, and the list says search is not available. `searchable`
  overrides what the schema says.
- Empty reads "No venues yet" or "No venues match “ber”". A failure reads "You
  can't view venues", "Couldn't reach the server" or "Something went wrong on
  our side", with "Try again" when it can help.
- Preselected ids are labelled in one request when the list documents
  `id__in` (Karni's derived filters do not include it, so add it on the viewset
  with `filterset_fields = {"id": ["exact", "in"]}`), otherwise one detail
  request per id, in parallel. `idsFilter` names another filter or (`false`)
  forces per-id requests. An id that cannot be loaded says "Couldn't load venue
  12" instead of showing the bare id.
- It is an ARIA 1.2 combobox (`aria-expanded`, `aria-controls`,
  `aria-activedescendant`). Arrows, Home/End and PageUp/PageDown move through
  every loaded page. Chips remove with their button, Backspace/Delete, or
  Backspace in the empty input. The ref is the input, and `onBlur`,
  `aria-describedby`, `aria-invalid` and `aria-required` make it a form field.
  `slots` replaces `Option`, `Chip`, `Loading`, `Empty` and `Error`
  (`defaultResourceSelectSlots`).

## Hooks

```tsx
const { data, isLoading } = useResourceList<Event>("events", {
  page: 1,
  pageSize: 25,
  ordering: "-starts_at",
  search: "conf",
  filters: { status: "published" },
});

const event = useResourceItem<Event>("events", id);
const { create, update, remove } = useResourceMutations<Event>("events");
```

List responses are DRF pages: `{ count, next, previous, results }`
(the `Paginated<T>` type). Mutations invalidate `karniKeys.resource(resource)`
on success. Pass `invalidateKeys` to invalidate more. Use `karniKeys` for any
manual cache work so your keys and the library's keys never drift.

## Auth

```tsx
const { user, status, login, logout } = useAuth();
const { hasRole, isAuthenticated } = usePermission();

<AuthGuard roles={["admin"]} explain>
  <AdminPanel />
</AuthGuard>;
```

With `explain`, `AuthGuard` says why it refuses. A visitor who is not signed in
sees a sign-in prompt with a `LoginForm` (signing in reveals the content in
place). A signed-in user whose role lacks access sees `PermissionDenied` naming
who is signed in. Replace one case with `anonymous={...}` or `denied={...}` (or
the `Anonymous` / `Denied` slots). `fallback` still covers both, and
`fallback={null}` renders nothing. Without any of these a guard renders
nothing, as in 0.3, and warns once in development: 1.0 makes `explain` the
default. To hide a piece of UI from a role, prefer `usePermission().hasRole(...)`.

`LoginForm` tells wrong credentials ("That email and password do not match")
from throttling ("Too many sign-in attempts. Wait 42 seconds"), a server error
and a dropped connection. The message is announced. Both fields point at it
(`aria-describedby`) and are marked invalid when they are the problem. The
email stays after a failure, and wrong credentials clear and focus the password.
The email field takes focus on mount (`autoFocus={false}` turns that off).

In JWT mode the refresh token is stored through a pluggable `TokenStorage`.
The default is `localStorage`, which is simple but readable by any XSS on your
page. For stricter setups use `createMemoryTokenStorage()` or your own adapter,
at the cost of logout-on-reload. Session mode uses cookies + CSRF headers and needs no
token storage.

## Primitives and escape hatches

Primitives are exported directly (`Button`, `Input`, `Select`, …) and follow
three rules:

1. **`className` always merges** via `cn()` (clsx + tailwind-merge), so your
   classes win over the component's own.
2. **Refs are forwarded** to the underlying element.
3. **Composition over configuration**: for example, `buttonVariants()` is exported to
   style any element as a button, and the styled Radix parts
   (`SelectRoot`/`SelectTrigger`/`SelectContent`/`SelectItem`, the
   `DropdownMenu*` family, `Tabs*`) are exported for fully custom composition.

`Select` note: Radix reserves the empty string, so the composed `Select` maps
"no selection" through an internal `"__karni_empty__"` sentinel. Consumers only
ever see `null`. Pass `clearable` to render a clear item that emits `null`.
Option values `""` and `"__karni_empty__"` are reserved.

The `variants()` helper (a dependency-free cva-style utility) and `cn()` are
exported for building your own components in the same style.

Leaf primitives have no `slots`: there is nothing inside them to replace, and
each one is replaced whole through the registry below (or restyled with
`className`). `Input`, `Textarea`, `SelectTrigger` (and the composed `Select`)
and `Checkbox` show a destructive border while `aria-invalid` is true, so a
form marks a field invalid with the same attribute screen readers announce.
The composed `Select` passes `aria-invalid`, `aria-describedby` and
`aria-labelledby` to its trigger.

### Your design system's primitives

A project with its own design system registers its primitives once, and every
Karni component renders them in place of Karni's, keeping its schema-driven
behaviour:

```tsx
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as select from "@/components/ui/select";

<KarniProvider
  client={client}
  primitives={{
    button: Button,
    input: Input,
    select: {
      Root: select.Select,
      Trigger: select.SelectTrigger,
      Value: select.SelectValue,
      Content: select.SelectContent,
      Item: select.SelectItem,
      Group: select.SelectGroup,
      Label: select.SelectLabel,
      Separator: select.SelectSeparator,
    },
  }}
>
```

The roles are `button`, `input`, `textarea`, `checkbox`, `switch`, `label`,
`skeleton` and the `select` family. A registered component receives the props
of Karni's primitive (`ButtonProps`, `InputProps`, …) and its ref. Components
from shadcn/ui take them as they are, and another design system registers a small
adapter (its own button with Karni's `variant` and `size` names mapped onto
its own). `select` is replaced as a whole family because Radix parts share a
context. A registered component may wrap Karni's own primitive: inside it, the
role resolves to Karni's again. `KarniPrimitivesProvider` changes the registry
for a subtree.

In a shadcn/ui project, `karni ui detect` writes this registry for you as
`karni-primitives.tsx` (a file the project owns), with only the roles whose
shadcn component exists, and the `select` family only when `select.tsx`
exports all eight parts on Radix. It adds `primitives={primitives}` to the
scaffold's `<KarniProvider client={client}>`, or prints the line to add.

## App shell and support components: slots

`Layout`, `Page`, `Modal`, `Toaster`, `EmptyState`, `Stat`, `DataChart` and
`FileUpload` take `className` (merged onto their root with `cn()`) and
`slots`: replace one internal piece and keep the rest of the component's
behaviour. Each component exports its slot contract (`LayoutSlots`,
`PageSlots`, ...), the props each slot receives, and its defaults
(`defaultLayoutSlots`, ...) so a replacement can wrap the original:

```tsx
import { Layout, type LayoutNavLinkProps } from "@karni/ui";
import { Link } from "@tanstack/react-router";

function NavLink({ item, href, onClick, ...props }: LayoutNavLinkProps) {
  // onClick closes the mobile drawer; className carries the active style and focus ring.
  return <Link to={href} onClick={onClick} {...props} />;
}

<Layout navItems={nav} slots={{ NavLink }}>
  …
</Layout>;
```

| Component    | Slots                                                      |
| ------------ | ---------------------------------------------------------- |
| `Layout`     | `Header`, `Sidebar`, `NavLink`, `MobileDrawer`, `SkipLink` |
| `Page`       | `Header`, `Title`, `Description`, `Actions`                |
| `Modal`      | `Header`, `Footer`, `CloseButton`                          |
| `Toaster`    | `Title`, `Description`, `CloseButton`                      |
| `EmptyState` | `Icon`, `Title`, `Description`, `Actions`                  |
| `Stat`       | `Label`, `Value`, `Delta`, `Icon`                          |
| `DataChart`  | `Tooltip`, `Legend`, `Empty`, `Loading`                    |
| `FileUpload` | `Dropzone`, `FileRow`                                      |

Where a slot does what an older prop did, the prop keeps working and the slot
is preferred: `Layout`'s `renderNavItem` (use `NavLink`), `Page`'s `header`
(use `Header`, which still receives the title, description and actions),
`DataChart`'s `renderTooltip` (use `Tooltip`), `Toaster`'s `viewportClassName`
(use `className`). A custom `Modal` `Header` renders `ModalTitle` (and
`ModalDescription`) so the dialog stays labelled. A custom `CloseButton` wraps
its button in `ModalClose`.

Other additions: `Layout` takes `mobileNavOpen`, `defaultMobileNavOpen` and
`onMobileNavOpenChange` to control the drawer. `Stat` and `DataChart` take
`loading`, and `DataChart` also takes `summary`. `FileUpload` takes `error`,
`uploading`, `rejectionMessage`, `aria-invalid`, `aria-describedby` and
`aria-labelledby`.

## Accessibility

The app shell, the support components and the primitives target WCAG 2.2 AA.
What each one does for keyboard and screen-reader users:

- **Layout**: a "Skip to content" link is the first Tab stop and moves focus
  to `<main>`. Below `md` the sidebar is a modal drawer (Radix Dialog): named
  "Navigation", focus moves into it and stays there, Escape, the backdrop, the
  close button or a link close it, and focus returns to the menu button. The
  menu button's `aria-controls` names the drawer only while it is open. The
  drawer closes itself if the window grows past `md`. Nav links show a focus
  ring and mark the current page with `aria-current="page"`. After a
  client-side navigation (from the drawer too), focus moves to the new
  page's `<h1>` (else `<main>`) and a polite live region says the page
  title. Nothing moves on the first load (a redirect before the user acts
  included), when only search params change (filters, pagination, sorting),
  or when the page placed focus itself (an autofocused field, a control
  inside `<main>`, a dialog). No router is needed: the route is the
  URL's path, and a hash route like `#/events` counts. Render `Layout` once,
  around your router's outlet, as `karni new` does. `routeFocus={false}`
  turns this off, and `routeFocus={{ routeKey, getTarget, getAnnouncement }}`
  sets the route (for a memory router), the element to focus and the words.
- **ResourceTable**: the table is a grid with one Tab stop. The arrow keys
  move inside it, Enter opens a row and Space selects it, so a long page no
  longer costs a Tab press per control. `keyboardNavigation="native"` gives
  every control its own Tab stop again. The details are under "Keyboard and
  screen readers" in the ResourceTable section.
- **Modal**: named by its title and described by its description. Focus moves
  in, Tab stays inside, Escape closes, and focus returns to what opened it.
- **Toaster**: an error toast is announced at once (assertive), the others
  politely. F8 moves focus to the toasts, Tab walks them and their buttons,
  Escape dismisses the focused one. A toast's timer pauses while the pointer is
  over the toasts or focus is inside them.
- **FileUpload**: the dropzone is a button (Enter or Space opens the file
  picker), named by its text, `aria-label`, `aria-labelledby` or a
  `<label htmlFor={id}>`. A refused file ("notes.txt isn't an accepted file
  type.") and the `error` prop are announced and linked with
  `aria-describedby`, and `aria-invalid` gives the invalid style. While
  `uploading` it is busy and says so. Removing a file returns focus to the
  dropzone.
- **DataChart**: an image named by its title and described by its description
  plus a generated summary (each series' lowest and highest value). Every
  value is in a visually hidden table. Tab focuses the chart. The arrow keys,
  Home and End move the tooltip from point to point and announce each one, and
  Escape hides it. On a narrow screen the tick labels stay at 11px.
- **Stat**: a change is spoken ("Increased by", "Decreased by", "Unchanged")
  and drawn with an arrow or a dash, not by colour alone. `loading` sets
  `aria-busy`.
- **Primitives**: every control shows a focus ring on keyboard focus
  (`focus-visible`, the `--karni-color-ring` token). Tabs, DropdownMenu,
  Select, Checkbox and Switch follow the WAI-ARIA keyboard patterns through
  Radix.

Contrast: every text and background pair the components use reaches 4.5:1 in
both themes, and field boundaries, the switch track, focus rings, icon-only
buttons and chart series reach 3:1. `tests/contrast.test.ts` computes the
ratios from the tokens in `styles.css`, so a token change cannot lower one
unnoticed. If you override tokens, check the same pairs. Motion reads
`--karni-duration`, which is 0ms under `prefers-reduced-motion`, and nothing
animates from JavaScript.

`tests/a11y.test.tsx` runs axe-core (the WCAG A and AA rules) over every
story of these components.

## Manifest for coding agents

The published package contains `dist/manifest.json`, shaped
`{ "components": [...], "hooks": [...], "roles": {...} }`. It is generated from
the public barrel (and a static scan of the `registerComponentRole` call sites)
at build time. AI coding agents can read it (export path
`@karni/ui/manifest.json`) to discover what exists instead of crawling source.

## ESLint plugin

`@karni/ui/eslint-plugin` ships the Karni frontend enforcement rules
(`karni/no-raw-elements`, `karni/max-page-lines`, `karni/no-deep-imports`,
`karni/no-direct-http`) as a flat-config preset for ESLint >= 9. A fifth rule,
`karni/no-style-literals`, is not in the preset: it fails on any visual value
that does not resolve from a `--karni-*` token, and a project whose own code
should follow the theme turns it on with `"karni/no-style-literals": "error"`.

```js
// eslint.config.js
import karni from "@karni/ui/eslint-plugin";
export default [...karni.configs.recommended];
```

Every rule is an error. Opt-outs are disable comments with a REQUIRED reason
(`// eslint-disable-next-line karni/no-direct-http -- <reason>`). See
`docs/enforcement.md` at the repo root.

## Development

```sh
npm install
npm run build      # tsc --noEmit && vite build && generate manifest
npm test           # vitest (jsdom + testing-library + msw)
npm run lint       # eslint 9 flat config (strict TS, no `any`, D7, karni/* dogfood)
npm run storybook  # Storybook 8 (react-vite) with a light/dark toolbar
```

Before the first `npm run storybook`, generate the MSW worker once:
`npx msw init public/`.

Tests enforce the color discipline: component source uses tokens only, with no
Tailwind palette classes or raw color literals
(see `src/components/primitives/no-color-literals.test.ts`).
