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

All component colors resolve through `--karni-*` CSS custom properties defined in
`@karni/ui/styles.css` (light values on `:root`, dark values under `.dark`).
Import it once, then wire Tailwind so the token-backed utility classes
(`bg-primary`, `text-muted-foreground`, …) exist in your build.

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

### Tailwind v4 (CSS-first recipe)

Tailwind v4 has no `presets` array; map the tokens in CSS instead:

```css
/* app.css */
@import "tailwindcss";
@import "@karni/ui/styles.css";

/* Scan the library's shipped output for class names. */
@source "../node_modules/@karni/ui/dist";

/* Dark mode is class-based: add `dark` to <html> (or any ancestor). */
@custom-variant dark (&:where(.dark, .dark *));

/* Map Tailwind color/radius theme slots onto the --karni-* tokens. */
@theme inline {
  --color-background: hsl(var(--karni-background));
  --color-foreground: hsl(var(--karni-foreground));
  --color-card: hsl(var(--karni-card));
  --color-card-foreground: hsl(var(--karni-card-foreground));
  --color-popover: hsl(var(--karni-popover));
  --color-popover-foreground: hsl(var(--karni-popover-foreground));
  --color-primary: hsl(var(--karni-primary));
  --color-primary-foreground: hsl(var(--karni-primary-foreground));
  --color-secondary: hsl(var(--karni-secondary));
  --color-secondary-foreground: hsl(var(--karni-secondary-foreground));
  --color-muted: hsl(var(--karni-muted));
  --color-muted-foreground: hsl(var(--karni-muted-foreground));
  --color-accent: hsl(var(--karni-accent));
  --color-accent-foreground: hsl(var(--karni-accent-foreground));
  --color-destructive: hsl(var(--karni-destructive));
  --color-destructive-foreground: hsl(var(--karni-destructive-foreground));
  --color-border: hsl(var(--karni-border));
  --color-input: hsl(var(--karni-input));
  --color-ring: hsl(var(--karni-ring));
  --color-chart-1: hsl(var(--karni-chart-1));
  --color-chart-2: hsl(var(--karni-chart-2));
  --color-chart-3: hsl(var(--karni-chart-3));
  --color-chart-4: hsl(var(--karni-chart-4));
  --color-chart-5: hsl(var(--karni-chart-5));
  --radius-lg: var(--karni-radius);
  --radius-md: calc(var(--karni-radius) - 2px);
  --radius-sm: calc(var(--karni-radius) - 4px);
}
```

### Theming and dark mode

Override any token after importing the stylesheet — components pick it up
everywhere, in both Tailwind versions:

```css
:root {
  --karni-primary: 262 83% 58%; /* HSL triplet, no hsl() wrapper */
  --karni-radius: 0.75rem;
}
```

Toggle dark mode by adding/removing the `dark` class on `<html>`. Chart series
colors are `--karni-chart-1` … `--karni-chart-5`.

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

## Manifest for coding agents

The published package contains `dist/manifest.json` —
`{ "components": [...], "hooks": [...], "roles": {...} }` — generated from the
public barrel (and a static scan of the `registerComponentRole` call sites) at
build time. AI coding agents can read it (export path
`@karni/ui/manifest.json`) to discover what exists instead of crawling source.

## ESLint plugin

`@karni/ui/eslint-plugin` ships the Karni frontend enforcement rules
(`karni/no-raw-elements`, `karni/max-page-lines`, `karni/no-deep-imports`,
`karni/no-direct-http`) as a flat-config preset for ESLint >= 9:

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
