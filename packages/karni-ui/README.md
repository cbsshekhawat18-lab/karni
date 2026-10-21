# @karni/ui

Schema-driven React components for [Karni](https://github.com/cbsshekhawat18-lab/karni#readme) backends. Point it at a
Karni API's OpenAPI schema and get working tables, forms, detail views and auth —
plus the themable primitives they are built from — without regenerating boilerplate.

- **Resource components** — `ResourceTable`, `ResourceForm`, `ResourceDetail`,
  `ResourceSelect` render themselves from the backend schema (`/api/schema/`).
- **Hooks** — `useResourceList`, `useResourceItem`, `useResourceMutations`,
  `useSchema` on TanStack Query, with a shared `karniKeys` key factory.
- **Auth** — `AuthProvider`, `useAuth`, `AuthGuard`, `usePermission` for Karni's
  JWT or session auth modes.
- **Primitives** — Button, Input, Textarea, Select, Checkbox, Switch, Label,
  Tabs, DropdownMenu, Skeleton: Radix-based, token-themed, `forwardRef`,
  `className`-mergeable.

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
The project also needs `tailwindcss` (v3.4+ or v4) as a build tool — a
devDependency, as `karni new` sets it up: it compiles the classes the
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
the schema root (`x-karni-auth-mode`); override it with `mode="jwt" | "session"`.

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
| other              | `--karni-z-*`, `--karni-opacity-*`, `--karni-duration` and `--karni-ease` (0ms under `prefers-reduced-motion`), `--karni-border-width*`, `--karni-ring-*`                                                                |

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
it with `@config`; add the `@tailwindcss/vite` plugin to `vite.config.ts`:

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
spacing, type, radius, shadow and motion; the named stacking classes
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
derive from unless you set them too. Toggle dark mode by adding or removing the
`dark` class on `<html>`.

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
you edited unless you pass `--force`; `--json` prints the report for agents.
See [Theming](https://cbsshekhawat18-lab.github.io/karni/theming/) for each
source in detail.

## Resource components

Every resource component takes the backend's resource name (the router prefix)
and renders from the schema. They are defaults, not cages — each one exposes
override props, and you can always drop down to the hooks + primitives.

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

Audit fields — `AUDIT_FIELDS`: `id`, `created_at`, `updated_at`, `created_by`,
`updated_by`, which every Karni resource carries — never lead the screen.
`ResourceTable` hides their columns by default (domain fields come first, in
schema order; rows are still keyed by `id`). Show one by naming it in `columns`
(`{ field: "created_at" }`), or show all of them after the domain columns with
`showAuditFields`. `ResourceDetail` lists them last, in a muted "Record" group,
and still honours `fields` overrides for them. `ResourceForm` never renders them
(they are read-only).

A create form starts from the schema's defaults (a model's `default=`), and a
cleared optional field is left out of the request rather than sent as `null`
(`null` is sent only for nullable fields).

Validation schemas are generated at runtime with `zodFor(schema, "create" | "update")`;
`displayLabel(obj)` picks a human label for relation objects.

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
on success; pass `invalidateKeys` to invalidate more. Use `karniKeys` for any
manual cache work so your keys and the library's keys never drift.

## Auth

```tsx
const { user, status, login, logout } = useAuth();
const { hasRole, isAuthenticated } = usePermission();

<AuthGuard roles={["admin"]} fallback={<LoginPage />}>
  <AdminPanel />
</AuthGuard>;
```

In JWT mode the refresh token is stored via a pluggable `TokenStorage`; the
default is `localStorage` (simple, but readable by any XSS on your page — use
`createMemoryTokenStorage()` or your own adapter for stricter setups, at the
cost of logout-on-reload). Session mode uses cookies + CSRF headers and needs no
token storage.

## Primitives and escape hatches

Primitives are exported directly (`Button`, `Input`, `Select`, …) and follow
three rules:

1. **`className` always merges** via `cn()` (clsx + tailwind-merge), so your
   classes win over the component's own.
2. **Refs are forwarded** to the underlying element.
3. **Composition over configuration** — e.g. `buttonVariants()` is exported to
   style any element as a button, and the styled Radix parts
   (`SelectRoot`/`SelectTrigger`/`SelectContent`/`SelectItem`, the
   `DropdownMenu*` family, `Tabs*`) are exported for fully custom composition.

`Select` note: Radix reserves the empty string, so the composed `Select` maps
"no selection" through an internal `"__karni_empty__"` sentinel. Consumers only
ever see `null`; pass `clearable` to render a clear item that emits `null`.
Option values `""` and `"__karni_empty__"` are reserved.

The `variants()` helper (a dependency-free cva-style utility) and `cn()` are
exported for building your own components in the same style.

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
of Karni's primitive (`ButtonProps`, `InputProps`, …) and its ref; shadcn/ui's
components take them as they are, and another design system registers a small
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

## Manifest for coding agents

The published package contains `dist/manifest.json` —
`{ "components": [...], "hooks": [...], "roles": {...} }` — generated from the
public barrel (and a static scan of the `registerComponentRole` call sites) at
build time. AI coding agents can read it (export path
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

Every rule is an error; opt-outs are disable comments with a REQUIRED reason
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

The source of truth for color discipline is enforced by tests: no Tailwind
palette classes or raw color literals in component source — tokens only
(see `src/components/primitives/no-color-literals.test.ts`).
