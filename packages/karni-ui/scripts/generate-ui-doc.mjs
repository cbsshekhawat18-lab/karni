/**
 * scripts/generate-ui-doc.mjs — docs/ui.md from dist/manifest.json.
 *
 *   node scripts/generate-manifest.mjs && node scripts/generate-ui-doc.mjs > ../../docs/ui.md
 *
 * The manifest is the package's public barrel (components, hooks) plus the
 * component roles, scanned statically at build time; the page lists them with
 * one line each so the reference cannot drift from what ships.
 * tests/ui-doc.test.ts fails when docs/ui.md differs from this render.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/** Components grouped by what they are for; anything unlisted lands in "Primitives". */
const GROUPS = [
  [
    "Resource components (schema-driven)",
    [
      "ResourceTable",
      "ResourceForm",
      "ResourceDetail",
      "ResourceSelect",
      "ChangeHistory",
      "ResourceImport",
    ],
  ],
  [
    "App shell and pages",
    [
      "Layout",
      "Page",
      "EmptyState",
      "Modal",
      "ModalClose",
      "ModalTitle",
      "ModalDescription",
      "Toaster",
      "Stat",
      "DataChart",
      "FileUpload",
      "KarniMark",
    ],
  ],
  [
    "Auth",
    [
      "AuthProvider",
      "AuthGuard",
      "LoginForm",
      "SocialButton",
      "OtpLoginForm",
      "TermsGate",
      "KarniProvider",
    ],
  ],
];

/** Components and hooks under the experimental tier (docs/stability.md#experimental-names). */
const EXPERIMENTAL = new Set(["SocialButton", "OtpLoginForm", "TermsGate"]);

/** The page blocks (experimental), each with when to use it. */
const PAGE_BLOCKS = [
  [
    "DashboardGrid",
    'a responsive grid of cards: one column on phones, two on `md` screens, `columns` (2, 3 or 4) on `xl`. Each card takes a `span` (1 to 4, or `"full"`). Use it for the layout of a dashboard or a report.',
  ],
  [
    "DashboardCard",
    "one card of the grid: a region named by its title, with a description, actions, and the loading, empty and error states every data card needs. Put a DataTable, a ComparisonTable or anything else in it.",
  ],
  [
    "ChartCard",
    "a DashboardCard around a DataChart (every DataChart prop passes through). The title names the chart for a screen reader too.",
  ],
  [
    "DataTable",
    "rows the page computed (a summary, a breakdown, a report): sorting, a sticky header and first column, CSV and XLSX export of every row in the order shown, and only the rows in view rendered past 100, so 10,000 rows scroll smoothly. A resource's rows are a ResourceTable: it pages, filters and checks permissions through the API.",
  ],
  [
    "ComparisonTable",
    'entities side by side: one column per entity, one row per metric, the best value of a metric marked (`better: "higher"` or `"lower"`). Use it to compare plans, regions or products.',
  ],
  [
    "Accordion",
    "sections that open and close, after the WAI-ARIA accordion pattern (Down, Up, Home and End move between the headers). Use it where a page would write a raw `<details>`.",
  ],
  [
    "MarkdownView",
    "markdown shown as formatted HTML, sanitized: raw HTML shows as text unless `allowHtml`, and never a script, an event handler or a `javascript:` link. The parser and the sanitizer (marked, DOMPurify) load on first use.",
  ],
];

/** The example page the section shows (examples/eventhub). */
const EXAMPLE_PAGE = resolve(
  here,
  "..",
  "..",
  "..",
  "examples",
  "eventhub",
  "frontend",
  "src",
  "pages",
  "venue-overview.tsx",
);

function pageBlocks(manifest) {
  const role = (name) =>
    Object.entries(manifest.roles).find(([, component]) => component === name)?.[0];
  const lines = [
    "## Page blocks (experimental)",
    "",
    '!!! warning "Experimental"',
    "    The page blocks, `useResourceCounts` and ResourceDetail's `related` prop are",
    "    [experimental](stability.md#experimental-names): they may change in a minor",
    "    release, and each change is in the CHANGELOG.",
    "",
    "Pages for large apps are dashboards, comparisons and reports, not only resource",
    "tables. These components keep such a page within the 50-line cap",
    "(`karni/max-page-lines`), and `karni/no-raw-elements` names them where a page",
    "writes a raw `<table>` or `<details>`.",
    "",
  ];
  for (const [name, text] of PAGE_BLOCKS) {
    if (!manifest.components.includes(name)) continue;
    const claimed = role(name);
    lines.push(`- \`${name}\`${claimed ? ` (role \`${claimed}\`)` : ""}: ${text}`);
  }
  lines.push(
    "- `useResourceCounts(resources)`: the rows of each resource the user can read, as chart points (one list request each, `page_size=1`). The dashboard pages `karni build` writes chart it.",
    '- ResourceDetail\'s `related={["deals", "people"]}`: a tab per reverse relation, each a ResourceTable of the related rows filtered to the record. The backend publishes each model\'s reverse relations and the list parameter that filters by each one as `x-karni-related` on its list operation, so nothing is guessed. A name is the relation\'s name, its resource, or `resource.field` when two relations lead to one resource.',
    "",
    "Their sizes are tokens: `--karni-dashboard-gap` (the space between cards),",
    "`--karni-data-table-max-height` (the box DataTable and ComparisonTable scroll inside:",
    "keep it a length, since DataTable needs a height to render only the rows in view) and",
    "`--karni-data-table-row-height`. `karni ui detect` lists them.",
    "",
  );
  if (existsSync(EXAMPLE_PAGE)) {
    const source = readFileSync(EXAMPLE_PAGE, "utf8");
    const count = source.endsWith("\n") ? source.split("\n").length - 1 : source.split("\n").length;
    lines.push(
      "### An example page",
      "",
      `EventHub's venue overview (\`examples/eventhub/frontend/src/pages/venue-overview.tsx\`, ${count} lines)`,
      "computes its rows from one list request and lays them out with a DashboardGrid:",
      "",
      "```tsx",
      source.trimEnd(),
      "```",
      "",
    );
  }
  return lines;
}

/** Field groups, column sets and MarkdownField: a model with many fields (item 12). */
function wideModels() {
  return [
    "## Field groups and column sets (experimental)",
    "",
    '!!! warning "Experimental"',
    "    `Karni.field_groups`, `field_group_layout` and `column_sets`, their",
    "    `x-karni-field-groups` and `x-karni-column-sets` extensions, the `fieldGroups` and",
    "    `groupLayout` props of ResourceForm and ResourceDetail, ResourceTable's `columnSets`,",
    "    `columnSet` and `onColumnSetChange`, and the `FieldGroupDef`, `FieldGroupLayout`,",
    "    `FieldGroupsDef`, `ColumnSetDef` and `ColumnSetsDef` types are",
    "    [experimental](stability.md#experimental-names).",
    "",
    "A model with a hundred columns and a dozen long markdown sections makes a generated form",
    "or detail page one endless list, and its table a hundred columns. Declare the layout on",
    "the model and every screen follows, with no page code:",
    "",
    "```python",
    "from karni.fields import MarkdownField, MoneyField",
    "",
    "class Product(BaseModel):",
    "    name = models.CharField(max_length=200)",
    "    summary = MarkdownField(blank=True)",
    '    price = MoneyField(currency="EUR")',
    '    cost = MoneyField(currency="EUR")',
    "",
    "    class Karni:",
    '        field_groups = {"Overview": ["name", "summary"], "Financials": ["price", "cost"]}',
    '        field_group_layout = "tabs"  # or "sections", the default',
    "        column_sets = {",
    '            "default": ["name", "price"],',
    '            "financial": ["name", "price", "cost"],',
    "        }",
    "```",
    "",
    "- **Field groups.** ResourceForm shows each group as a fieldset with its legend,",
    "  ResourceDetail as a section with a heading, and the admin as a fieldset. The groups",
    "  keep the declaration's order, and the fields in no group come last, under Other. As",
    "  tabs, a tab with a failing field is marked, and moving focus to a field (the error",
    "  summary, a failed submit) opens its tab. `fieldGroups={false}` shows one list, and",
    "  `fieldGroups={[...]}` or `groupLayout` replace the model's in one screen.",
    "- **Column sets.** ResourceTable gets a column set menu, one choice per set. The",
    "  set named `default` shows first, else the first set, and the user's choice is",
    "  remembered per user and table in the browser. `columnSet` and `onColumnSetChange`",
    "  control it, and `columnSets={false}` shows every derived column. `columns`",
    "  overrides still apply to a set's columns.",
    "- **MarkdownField.** ResourceForm edits it with Write and Preview tabs (the preview is",
    "  MarkdownView), ResourceDetail shows it formatted and sanitized across the width, and",
    "  it is no default table column (a column set or `columns` can name it: it shows a",
    "  one-line excerpt). See [typed fields](fields.md#markdownfield).",
    "",
    "The backend publishes both on the model's list operation, limited to the fields the",
    "user's role may read, so a hidden field is never named:",
    "",
    "```json",
    '"x-karni-field-groups": {"layout": "tabs", "groups": [',
    '  {"label": "Overview", "fields": ["name", "summary"]},',
    '  {"label": "Financials", "fields": ["price", "cost"]}',
    "]},",
    '"x-karni-column-sets": {"default": "default", "sets": [',
    '  {"name": "default", "label": "Default", "columns": ["name", "price"]},',
    '  {"name": "financial", "label": "Financial", "columns": ["name", "price", "cost"]}',
    "]}",
    "```",
    "",
    "`karni check` refuses a malformed declaration (`karni.E550`, `karni.E553`), a group or",
    "set that names a field the model does not have (`karni.E551`) and a field in two groups",
    "(`karni.E552`), naming the model, the group or set, and the field. In `karni.yaml` an",
    "entity's `groups` and `column_sets` write them ([the app spec](app-spec.md#apps-and-their-entities)).",
    "",
    "A 120-field test model with twelve markdown sections keeps these budgets: a list page of",
    "25 rows under 200,000 bytes of JSON and a detail under 8,000 (the API suite), and",
    "ResourceForm under 1,000 ms and ResourceDetail under 600 ms to render in jsdom (the UI",
    "suite).",
    "",
  ];
}

const HOOKS = {
  useResourceList:
    "A page of a resource: `{ page, pageSize, ordering, search, filters, expand }` → DRF's `{ count, next, previous, results }`.",
  useResourceItem: "One row by id, optionally expanded.",
  useChangeHistory:
    "One row's field-level change history (`GET /<resource>/<id>/history/`, audited models).",
  useImportDescribe:
    "The importable fields of a resource and the user's remembered column mapping.",
  useImportJob: "One import job's state. It polls while the backend previews or commits it.",
  useImportActions: "`upload`, `preview` (the dry run) and `commit` mutations of an import.",
  useResourceMutations:
    "`create`, `update` and `remove` for a resource. On success they invalidate the resource's queries.",
  useSchema: "The parsed OpenAPI schema of one resource (fields, operations, access).",
  useKarniClient:
    "The `KarniClient` behind every hook, with `client.request(path, { method, body, query })` for custom actions.",
  useAuth:
    "`{ user, status, login(email, password), logout, refresh }` from `AuthProvider`, and (experimental) `{ terms, termsRequired, acceptTerms(client) }` for terms acceptance.",
  usePermission: "`{ hasRole(...names), isAuthenticated }` for gating UI on roles.",
  useOtpLogin:
    "Experimental. `{ step, send(email), verify(code), resend, back, status, error, cooldown, length }`: sign in with a code sent by email (`POST <authBasePath>/otp/send/`, then `otp/verify/`).",
  useSocialLogin:
    "Experimental. `{ signIn(idToken, { nonce, name }), status, error, reset }`: sign in with a Google, Microsoft or Apple ID token the app got from the provider's SDK (`POST <authBasePath>/social/<provider>/`).",
  useToast: "Show a toast through the mounted `Toaster`.",
  useResourceCounts:
    "Experimental. `{ data, loading, error, refetch }`: the rows of each resource the user can read, as chart points (one list request each with `page_size=1`).",
  useUnsavedChangesGuard:
    "`{ dirty, setDirty, isDirty, shouldBlock }` for warning before leaving a dirty form. Give `shouldBlock` to your router's blocker and `setDirty` to ResourceForm's `onDirtyChange`.",
};

export function render(manifest) {
  const placed = new Set();
  const lines = [
    "---",
    "description: Every component, hook and helper @karni/ui exports from its root, generated from the package manifest.",
    "---",
    "",
    "# @karni/ui",
    "",
    "<!-- Generated by `node scripts/generate-ui-doc.mjs` in packages/karni-ui; never edit by hand. -->",
    "",
    'This page lists everything the package exports from its root (`import { ... } from "@karni/ui"`).',
    "It comes from the manifest built with the package (`@karni/ui/manifest.json`), which",
    "coding agents read too. Props and usage are in the",
    "[package README](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md).",
    "The resource components render from the backend's OpenAPI schema, so a page",
    "is a few lines that compose them (see the [tutorial](tutorial.md)).",
    "",
  ];
  for (const [title, names] of GROUPS) {
    const present = names.filter((name) => manifest.components.includes(name));
    if (present.length === 0) continue;
    lines.push(`## ${title}`, "");
    for (const name of present) {
      placed.add(name);
      const role = Object.entries(manifest.roles).find(([, component]) => component === name)?.[0];
      const notes = [role ? `role \`${role}\`` : "", EXPERIMENTAL.has(name) ? "experimental" : ""]
        .filter(Boolean)
        .join(", ");
      lines.push(`- \`${name}\`${notes ? ` (${notes})` : ""}`);
    }
    lines.push("");
  }
  lines.push(...pageBlocks(manifest));
  lines.push(...wideModels());
  for (const [name] of PAGE_BLOCKS) placed.add(name);
  const rest = manifest.components.filter((name) => !placed.has(name));
  lines.push(
    "## Primitives",
    "",
    "Styled Radix parts and basics. Each one always merges `className` and forwards refs.",
    "",
  );
  lines.push(rest.map((name) => `\`${name}\``).join(", "), "");
  lines.push("## Hooks", "");
  for (const name of manifest.hooks) {
    lines.push(`- \`${name}\`: ${HOOKS[name] ?? "See the package README."}`);
  }
  lines.push("", "## Component roles", "");
  lines.push(
    "Every top-level component claims one semantic role. `karni make component` refuses a",
    "role that another component holds (compose it instead), and `karni context` lists the roles.",
    "",
    "| Role | Component |",
    "|---|---|",
  );
  for (const [role, component] of Object.entries(manifest.roles).sort()) {
    lines.push(`| \`${role}\` | \`${component}\` |`);
  }
  lines.push("");
  return lines.join("\n");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const path = process.argv[2] ?? resolve(here, "..", "dist", "manifest.json");
  process.stdout.write(render(JSON.parse(readFileSync(path, "utf8"))));
}
