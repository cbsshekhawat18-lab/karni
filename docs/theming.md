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
  `import "./karni-theme.css";` right after it. Otherwise the report prints
  the line to add.
- **`karni-primitives.tsx`** (shadcn/ui only, `--no-primitives` skips it):
  the [primitive registry](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#your-design-systems-primitives)
  filled with the project's shadcn components, so `ResourceTable`,
  `ResourceForm` and the rest render the project's own buttons, inputs and
  selects. It is passed to the scaffold's `<KarniProvider client={client}>`
  automatically. Any other KarniProvider gets the line to add.

Both files carry a digest line (`karni ui detect: sha256 ...`). A re-run
rewrites a file only while it is exactly as generated. A file you edited (or
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
  `--karni-color-primary: hsl(var(--primary))`.
- shadcn for Tailwind 4 keeps full colours (`--primary: oklch(...)`):
  `--karni-color-primary: var(--primary)`.

The mapping is declared on `:root, .dark`, not `:root` alone: a custom
property declared on `:root` is computed there and inherited, so a `.dark`
subtree would keep the light value. Roles mapped: background, foreground,
card, popover, primary, secondary, muted, accent, destructive (each with its
`-foreground`), border, input, ring, chart-1 to chart-5, `--radius`, and
fonts, shadows and `--spacing` when the project defines them. Newer shadcn
has no `--destructive-foreground` (its destructive button sets its own text
colour). Karni's destructive button is solid, so its text is set to `white`
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
`:root:not(.dark)` only: Tailwind colours have no dark variant, so dark mode
keeps Karni's dark palette until you add a `.dark` block. (A plain `:root`
block would tie with Karni's own `.dark` block and win, because
`karni-theme.css` loads after `@karni/ui/styles.css`.)

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
function, a spread) is reported with what it is, never guessed. So is every
key Karni has no token for. MUI's `secondary`, for example, is a second brand
colour and not Karni's quiet secondary surface. It comes with the line to
add if you want it anyway.

## Any stylesheet: --css

A design that is not a design system still has a brand. `karni ui detect
--css <path>` reads any stylesheet and maps it onto the same tokens: plain
CSS with a few custom properties, a Bootstrap theme, or a hand-written sheet
with no variables at all. It is never auto-detected: you name the files.

```sh
karni ui detect --css design/styles.css --dry-run   # the report and the file
karni ui detect --css design/                       # the pages' stylesheets, in link order
karni ui detect --css vendor/bootstrap.css --css theme.css   # later files win
```

A `.css` file is read as it is. A directory is read through its pages: the
local stylesheets its `.html` files link, in document order, each once. A
directory without pages gives every `.css` file under it, framework files
(`normalize*`, `reset*`, `bootstrap*`, `*.min.css`) first. A local `@import`
is read before the file that imports it. A missing path is
[C303](errors.md#c303), and `--css` with `--source` is
[C106](errors.md#c106).

The values written are literals, never `var()` references, so the file
stands on its own: the staff app imports it after `@karni/ui/styles.css`
and the admin loads the same file (see [one theme for both](#one-theme-for-the-staff-app-and-the-admin)).

### What it reads, in three grades

| Grade | Where the value comes from |
| --- | --- |
| **found** | A custom property whose name means the role, its `var()` chain resolved through the stylesheet's own variables. |
| **inferred** | An ordinary rule (`body { background }`, `a { color }`, `button { border-radius }`), or a value derived from another token: the ring is the primary, the input border is the border, the text on a primary button is the stylesheet's own page colour with the most contrast (else white or black). |
| **defaulted** | Nothing in the stylesheet says. The token is not written, Karni's default applies, and the report lists it with the reason. |

Variable names are matched after lowercasing and dropping a common prefix
(`bs-`, `wp--preset--color--`, `md-sys-color-`, `pico-`, `color-`, `clr-`,
`c-`, `theme-`, `site-`, `global-`). An unshaded name beats a shade
(`--brand` over `--brand-600`, then 600, then 500). Channel variables such
as `--bs-primary-rgb` are read for resolving `var()` but never mapped
themselves.

| Token | Variable names | Rules it is inferred from |
| --- | --- | --- |
| `--karni-color-primary` | `primary`, `brand`, `main`, `primary-color`, else `accent`, then `link` | a primary button's background (`.btn-primary`, `button`, `.btn`, `[type=submit]`), else the `a` colour |
| `--karni-color-primary-foreground` | `primary-foreground`, `primary-contrast`, `on-primary`, `primary-text` | the primary button's `color` when its background is the primary, else derived for contrast |
| `--karni-color-background` | `background`, `bg`, `body-bg`, `page-bg`, `surface`, `paper`, `canvas` | `body` (or `html`) background |
| `--karni-color-foreground` | `foreground`, `fg`, `text`, `text-color`, `body-color`, `ink`, `on-surface` | `body` colour |
| `--karni-color-border` | `border`, `border-color`, `line`, `divider`, `outline`, `stroke` | `input`, `textarea` and `select` borders, else `hr`, else `table` |
| `--karni-color-input` | `input`, `input-border`, `field-border` | the border colour |
| `--karni-color-ring` | `ring`, `focus`, `focus-ring`, `focus-color` | the primary colour |
| `--karni-color-muted` | `muted`, `subtle`, `secondary-bg`, `tertiary-bg`, `surface-2`, `bg-muted` | (none) |
| `--karni-color-muted-foreground` | `muted-foreground`, `text-muted`, `secondary-color`, `text-secondary`, `hint` | `.text-muted`, `.muted`, `small`, `.caption`, `figcaption` colour |
| `--karni-color-destructive` | `danger`, `error`, `destructive`, `negative`, `critical` | `.error`, `.danger`, `.is-invalid`, `.alert-danger` colour or border |
| `--karni-radius` | `radius`, `border-radius`, `rounded`, `radius-md` | the button's `border-radius`, else an input's |
| `--karni-font-sans` | `font-sans`, `font-body`, `body-font-family`, `font-family`, `font-base`, `font-sans-serif` | `body` `font-family` or `font` shorthand |
| `--karni-font-mono` | `font-mono`, `font-monospace`, `font-code` | (none) |

A heading or display font (`--font-display`, `--font-heading`) is reported
as not mapped with the line to add, because Karni has one sans font and
headings use it. So is a second brand colour (`--accent` next to `--brand`),
with `--karni-color-accent` suggested. A value that reads a variable the
stylesheets do not define, or that is not the role's kind (channels where a
colour should be, a weight where a length should be), is reported, never
guessed.

### Light, dark, or both

Variables and rules on `:root`, `html` or `body` are the light values. Those
under `.dark`, `html.dark`, `[data-theme="dark"]`, `[data-bs-theme="dark"]`,
`[data-mode="dark"]` or inside `@media (prefers-color-scheme: dark)` are the
dark values and go to the `.dark` block. A stylesheet with no dark variant
whose page background is dark is a dark design: its colours are written for
both of Karni's modes (`:root, .dark`), and the report says so. A light-only
design writes light colours only, under `:root:not(.dark)`, and the report
notes that dark mode keeps Karni's dark palette. The radius and the fonts
apply in both modes.

### What the --css report says

```text
karni ui detect: plain CSS (1 stylesheet)
Read: design/style.css

Found (0):
  (none)

Inferred (11):
  button { background-color } -> --karni-color-primary: #0e7c86 [light]
  button { color }            -> --karni-color-primary-foreground: #ffffff [light]
  body { background-color }   -> --karni-color-background: #f7fbfc [light]
  body { color }              -> --karni-color-foreground: #1f2933 [light]
  input { border }            -> --karni-color-border: #cbd5dc [light]
  derived                     -> --karni-color-input: #cbd5dc [light]
                                 (the border colour: inputs share it)
  derived                     -> --karni-color-ring: #0e7c86 [light]
                                 (the primary colour: the focus ring follows it)
  .text-muted { color }       -> --karni-color-muted-foreground: #627d8a [light]
  .error { color }            -> --karni-color-destructive: #c0392b [light]
  button { border-radius }    -> --karni-radius: 6px
  body { font }               -> --karni-font-sans: "Nunito", "Segoe UI", sans-serif

Defaulted (2): Karni's own value applies
  --karni-color-muted: no muted or secondary surface variable
  --karni-font-mono: no monospace font variable
```

`--json` adds `found`, `inferred` and `defaulted` to the usual keys
(`mapped`, `not_mapped`, `notes`, `files`, `wiring`). Without a frontend,
`--css` still prints the report with `--dry-run` or `--json`, and writes the
file wherever `--output` says.

### From Python

Other tools read a design the same way without writing anything:

```python
from karni_cli.uitheme import detect_css

report = detect_css("design/")            # a file, a directory, or a list of them
report.found, report.inferred, report.defaulted
report.as_dict()                          # the --json shape
report.theme_css(date="2026-01-01")       # the karni-theme.css text
```

`karni import design` calls it when `karni-cli` is installed, so an imported
site's staff app wears the site's own brand.

## Nothing found

`karni-theme.css` lists Karni's main tokens with their defaults, read from
the installed `@karni/ui`, commented out. Uncomment a line to change it, and
the rest keep following Karni's releases.

`karni new` does not write this file: a fresh project has nothing to detect,
and a copy of today's defaults would pin them in every project instead of
letting them come from the versioned `@karni/ui`. The scaffold's
`src/index.css` points at `karni ui detect` instead.

## One theme for the staff app and the admin

`karni-theme.css` is the one file that holds a project's brand, and the
admin reads it too. `karni_settings()` sets `KARNI_THEME_CSS` to
`frontend/src/karni-theme.css` (relative to the project root, where `karni
ui detect` writes it), and:

- `karni.admin.theme.ProjectThemeFinder`, listed in `STATICFILES_FINDERS`,
  serves that file as the static file `karni/project-theme.css`. `runserver`
  reads the file live, and `collectstatic` copies it into `STATIC_ROOT`, so
  production serves it from the site's own origin, which the
  [Content-Security-Policy](security.md#security-headers)'s `style-src
  'self'` allows.
- `UNFOLD["STYLES"]` loads it third, after `karni/tokens.css` (Karni's
  defaults) and `karni/unfold-theme.css` (unfold drawn with the tokens).
  Karni's own admin pages load it the same way.

Without the file, the URL serves an empty stylesheet with a comment that
says how to make one, so a fresh project's admin wears Karni's defaults and
never loads a missing file. The order of events in a new project:

```sh
karni new shop && cd shop
karni ui detect --css ../design/style.css   # frontend/src/karni-theme.css
karni serve                                 # the staff app and /admin/ both wear the brand
```

Only the `--karni-*` tokens reach the admin: a `karni-theme.css` written
for shadcn/ui references the project's own variables (`var(--primary)`),
which the admin does not define, so for a shared theme prefer the literal
values `--css` writes, or add the variables to the admin with a stylesheet
of your own. `KARNI_THEME_CSS` points at another file (an absolute path, or
one relative to the project root), and `""` turns the admin side off. See
[admin: theming](admin.md#theming) for the rest of the admin's look (its
neutral scale, logo and unfold's own settings).

## What it does not do

- It maps tokens, not component shapes. Without the primitive registry,
  Karni's own button keeps its own height and variants (in a shadcn project:
  `h-10` against shadcn's `h-8`, a solid destructive button against shadcn's
  tinted one). The registry is what makes Karni's components render the
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
