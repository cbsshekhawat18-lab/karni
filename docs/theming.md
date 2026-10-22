---
description: karni ui detect maps a project's shadcn/ui, Tailwind, Material UI, Chakra UI or Mantine theme onto @karni/ui's design tokens and primitives, so Karni's components look like the project's own.
---

# Theming: fit Karni to your design system

Every visual value in `@karni/ui` resolves from a CSS custom property:
`--karni-color-*` (any CSS colour), `--karni-space-unit` and
`--karni-space-<n>`, `--karni-radius` and `--karni-radius-*`,
`--karni-font-*` and `--karni-shadow-*`. The full list is in the
[@karni/ui README](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#styling).
Override any of them after `@karni/ui/styles.css` and every component
follows.

A project that already has a design system should not retype it. `karni ui
detect` reads the design system the frontend has and writes Karni's tokens
for it:

```sh
cd frontend                  # or the Karni project root
karni ui detect --dry-run    # print the report and the files; write nothing
karni ui detect              # write src/karni-theme.css and wire it in
```

## What it detects, in order

| Source | Found by | What Karni's tokens become |
| --- | --- | --- |
| shadcn/ui | `components.json` | references to the project's own CSS variables (`var(--primary)`), live |
| A Tailwind theme | `@theme` blocks (Tailwind 4), `tailwind.config.*` (Tailwind 3, or 4 through `@config`) | the theme's semantic colours, fonts, radii, shadows, spacing unit, type scale |
| Material UI, Chakra UI, Mantine | the package in `package.json` and its `createTheme` / `extendTheme` / `createSystem` call in the source | the theme's literal values that mean a Karni token |
| Nothing | | Karni's defaults, listed commented, for you to edit |

The first source present wins. `--source shadcn|tailwind|mui|chakra|mantine|defaults`
reads one source instead of detecting.

## The files it writes

- **`karni-theme.css`**, next to the project's main stylesheet (`--output`
  chooses another path). Its header says what was detected, from which
  files, and on which date, and that the file is the project's to edit. It
  must load after `@karni/ui/styles.css`: when `src/main.tsx` has the
  scaffold's `import "@karni/ui/styles.css";` line, `karni ui detect` adds
  `import "./karni-theme.css";` right after it; otherwise the report prints
  the line to add.
- **`karni-primitives.tsx`** (shadcn/ui only, `--no-primitives` skips it):
  the [primitive registry](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#your-design-systems-primitives)
  filled with the project's shadcn components, so `ResourceTable`,
  `ResourceForm` and the rest render the project's own buttons, inputs and
  selects. It is passed to the scaffold's `<KarniProvider client={client}>`
  automatically; any other KarniProvider gets the line to add.

Both files carry a digest line (`karni ui detect: sha256 ...`). A re-run
rewrites a file only while it is exactly as generated; a file you edited (or
wrote by hand) is never overwritten without `--force`
([C302](errors.md#c302)). Compare with `--dry-run` first.

## The report

Every run lists the detected source, every token mapped (from, to, value),
every value not mapped with the reason, and the files written. `--json`
prints the same as JSON for agents (`source`, `detected`, `files_read`,
`mapped`, `not_mapped`, `notes`, `primitives`, `files`, `wiring`). On a
shadcn/ui project created with a stone base colour, the violet theme and a
large radius:

```text
karni ui detect: shadcn/ui (Tailwind 4 format: full colours, oklch)
Read: components.json, src/index.css

Mapped (30):
  --background           -> --karni-color-background: var(--background)
  --primary              -> --karni-color-primary: var(--primary)
  ...
  (none)                 -> --karni-color-destructive-foreground: white
                            (this shadcn/ui version has no --destructive-foreground ...)
  --radius               -> --karni-radius: var(--radius)
  @theme --radius-sm     -> --karni-radius-sm: calc(var(--radius) * 0.6)
  @theme --font-sans     -> --karni-font-sans: 'Inter Variable', sans-serif

Not mapped (2):
  @theme --font-heading: Karni has sans and mono font tokens only (headings use the sans font)
  --sidebar, --sidebar-foreground, ...: Karni has no sidebar tokens (its Layout reads background, border and accent)

Primitives (src/karni-primitives.tsx): button, input, select
  not registered: textarea: no @/components/ui/textarea (npx shadcn@latest add textarea)
  ...
```

## shadcn/ui

`karni ui detect` reads `components.json` for the stylesheet
(`tailwind.css`) and the `ui` alias, then the custom properties on `:root`
and `.dark` in that stylesheet. Karni's tokens reference them, never copy
them, so the project's later edits and its dark mode flow through:

- shadcn for Tailwind 3 keeps HSL channels (`--primary: 222.2 47.4% 11.2%`):
  `--karni-color-primary: hsl(var(--primary))`;
- shadcn for Tailwind 4 keeps full colours (`--primary: oklch(...)`):
  `--karni-color-primary: var(--primary)`.

The mapping is declared on `:root, .dark`, not `:root` alone: a custom
property declared on `:root` is computed there and inherited, so a `.dark`
subtree would keep the light value. Roles mapped: background, foreground,
card, popover, primary, secondary, muted, accent, destructive (each with its
`-foreground`), border, input, ring, chart-1 to chart-5, `--radius`, and
fonts, shadows and `--spacing` when the project defines them. Newer shadcn
has no `--destructive-foreground` (its destructive button sets its own text
colour); Karni's destructive button is solid, so its text is set to `white`
and the report says so. When the stylesheet's `@theme` derives the radii from `--radius`,
Karni copies the same formulas.

The generated registry has only the roles whose shadcn file exists and
exports the component (`button`, `input`, `textarea`, `checkbox`, `switch`,
`label`, `skeleton`), and the `select` family only when `select.tsx`
exports all eight parts and is built on Radix (the parts share one context).
A component built on Base UI or React Aria takes different props: it is
reported, not registered.

## Tailwind themes

A Tailwind 4 `@theme` variable becomes a token that reads it, with its value
as the fallback (Tailwind leaves unused theme variables out of the CSS, and
`@theme inline` never emits them): `--karni-color-primary:
var(--color-primary, oklch(0.55 0.22 285))`. A `tailwind.config` (Tailwind
3) is evaluated by Node in the project with the project's own `tailwindcss`
(`loadConfig` handles TypeScript configs), and only the values that differ
from Tailwind's defaults count.

Only names that clearly mean a Karni token are mapped: the semantic colours
(`primary`, `destructive`, `danger` or `error`, `muted`, `border`, ...),
`sans` and `mono` fonts, the `sm` to `xl` radii, the `sm` to `lg` shadows,
the spacing unit and the `xs` to `2xl` type scale. A palette such as
`brand: { 50 ... 950 }` is not a role, so it is reported with the line you
could add, never turned into `primary` silently. Literal colours go to
`:root` only: Tailwind colours have no dark variant, so dark mode keeps
Karni's dark palette until you add a `.dark` block.

## Material UI, Chakra UI, Mantine

The theme is read statically: `karni ui detect` finds the `createTheme`
(MUI or Mantine), `extendTheme` (Chakra 2) or `createSystem` /
`defineConfig` (Chakra 3) call by its import, and reads the literal values
(a `const` in the same file counts). It maps what has the same meaning:

| Library | Mapped |
| --- | --- |
| Material UI | `palette.primary.main` and `contrastText`, `error`, `background.default` and `paper`, `text.primary` and `secondary`, `divider`, `colorSchemes.light` and `dark`, `shape.borderRadius`, `typography.fontFamily`, `spacing` (MUI's `spacing(1)` is Karni's step 2) |
| Chakra UI | semantic colour tokens with `_dark` variants (references resolve through the project's palette, or to Chakra's CSS variable), `fonts.body` and `mono`, `radii`, `shadows`, `space`, `fontSizes` |
| Mantine | `primaryColor` with `primaryShade` (light and dark), `colors.red` as the error colour, `fontFamily`, `fontFamilyMonospace`, `defaultRadius`, `shadows` |

Anything computed (a variable from another module, `alpha(...)`, a theme
function, a spread) is reported with what it is, never guessed; so is every
key Karni has no token for (MUI's `secondary`, which is a second brand colour
and not Karni's quiet secondary surface, comes with the line to add if you
want it anyway).

## Nothing found

`karni-theme.css` lists Karni's main tokens with their defaults, read from
the installed `@karni/ui`, commented out. Uncomment a line to change it;
the rest keep following Karni's releases.

`karni new` does not write this file: a fresh project has nothing to detect,
and a copy of today's defaults would pin them in every project instead of
letting them come from the versioned `@karni/ui`. The scaffold's
`src/index.css` points at `karni ui detect` instead.

## What it does not do

- It maps tokens, not component shapes. Without the primitive registry,
  Karni's own button keeps its own height and variants (in a shadcn project:
  `h-10` against shadcn's `h-8`, a solid destructive button against shadcn's
  tinted one); the registry is what makes Karni's components render the
  project's own.
- It reads one design system: the first one found, or `--source`.
- It does not set up Tailwind for `@karni/ui` (the preset or the CSS-only
  mapping, and scanning `@karni/ui`'s classes): see the
  [README](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#styling).

Errors are coded: [C301](errors.md#c301) (no frontend found),
[C302](errors.md#c302) (an edited file is not overwritten),
[C303](errors.md#c303) (a theme source cannot be read, for example a
`tailwind.config` Node cannot load) and [C304](errors.md#c304) (`--source`
names a design system the frontend does not have).
