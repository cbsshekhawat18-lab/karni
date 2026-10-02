#!/usr/bin/env node
/**
 * Emits dist/manifest.json — { components, hooks, roles } — parsed from the
 * explicit re-exports in src/index.ts (contract D7) plus a static scan of the
 * registerComponentRole call sites under src/ (enforcement contract F11). AI
 * coding agents read this file to discover what @karni/ui ships without
 * crawling source.
 *
 * Classification rules (documented so they stay deterministic):
 * - Only VALUE exports are considered (`export type { ... }` lines and
 *   `type X` entries inside a value export are skipped).
 * - hooks: names matching /^use[A-Z]/.
 * - components: PascalCase names (first letter uppercase, at least one
 *   lowercase letter — this excludes ALL_CAPS constants) that are not in the
 *   NON_COMPONENT_VALUES set below.
 *
 * Role scan (build-time duplicate check, F11) — FAILS the build when:
 * - a registerComponentRole call's first argument is not a string literal, or
 * - the same role literal appears at distinct call sites and the duplicates
 *   do not carry `replace: true` (the explicit, reasoned opt-out).
 *
 * Runs as the last step of `npm run build`, after vite has populated dist/.
 * `--root <dir>` points the script at another package root (used by tests).
 */
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootArgIndex = process.argv.indexOf("--root");
const root =
  rootArgIndex !== -1 && process.argv[rootArgIndex + 1]
    ? resolve(process.argv[rootArgIndex + 1])
    : resolve(dirname(fileURLToPath(import.meta.url)), "..");
const barrelPath = resolve(root, "src/index.ts");
const outPath = resolve(root, "dist/manifest.json");

/** PascalCase value exports that are not React components. */
const NON_COMPONENT_VALUES = new Set(["KarniApiError"]);

function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

/** @returns {string[]} the value-export names declared in the barrel */
function parseValueExports(source) {
  const names = [];
  // Matches `export { a, b as c } from "..."` but NOT `export type { ... }`.
  const exportBlock = /export\s*(type\s*)?\{([^}]*)\}\s*from\s*["'][^"']+["']/g;
  for (const match of stripComments(source).matchAll(exportBlock)) {
    const isTypeOnlyBlock = Boolean(match[1]);
    if (isTypeOnlyBlock) continue;
    for (const rawEntry of match[2].split(",")) {
      const entry = rawEntry.trim();
      if (!entry || entry.startsWith("type ")) continue;
      // `original as alias` exports the alias.
      const alias = entry.includes(" as ") ? entry.split(" as ").at(-1) : entry;
      if (alias) names.push(alias.trim());
    }
  }
  return names;
}

// --- role scan (F11) --------------------------------------------------------

/** Replaces comment contents with spaces, preserving newlines/offsets. */
function maskComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\/[^\n]*/g, (m) => " ".repeat(m.length));
}

/** @returns {string[]} shipped .ts/.tsx sources under <root>/src */
function shippedSources(srcRoot) {
  const files = [];
  for (const entry of readdirSync(srcRoot, { recursive: true })) {
    const path = join(srcRoot, String(entry));
    if (!statSync(path).isFile()) continue;
    if (!path.endsWith(".ts") && !path.endsWith(".tsx")) continue;
    if (path.includes(".test.") || path.includes(".stories.") || path.endsWith(".d.ts")) continue;
    files.push(path);
  }
  return files.sort();
}

/**
 * Parses a leading string literal; returns { value, end } (end = index just
 * past the closing quote) or null when the text does not start with one.
 */
function parseStringLiteral(text) {
  const quote = text[0];
  if (quote !== '"' && quote !== "'") return null;
  let value = "";
  for (let i = 1; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "\\") {
      value += text[i + 1];
      i += 1;
    } else if (ch === quote) {
      return { value, end: i + 1 };
    } else {
      value += ch;
    }
  }
  return null;
}

/** Extracts the balanced `( ... )` argument text starting at openParenIndex. */
function callArguments(source, openParenIndex) {
  let depth = 0;
  for (let i = openParenIndex; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(openParenIndex + 1, i);
    }
  }
  return source.slice(openParenIndex + 1);
}

/**
 * Collects registerComponentRole("<literal>", ...) call sites across src/.
 * @returns {{ sites: {file: string, line: number, role: string, component: string, replace: boolean}[], errors: string[] }}
 */
function scanRoles(srcRoot) {
  const sites = [];
  const errors = [];
  for (const file of shippedSources(srcRoot)) {
    const masked = maskComments(readFileSync(file, "utf8"));
    const label = relative(root, file);
    for (const match of masked.matchAll(/\bregisterComponentRole\s*\(/g)) {
      // Skip the function's own declaration (src/lib/roles.ts).
      if (/function\s+$/.test(masked.slice(0, match.index))) continue;
      const line = masked.slice(0, match.index).split("\n").length;
      const args = callArguments(masked, match.index + match[0].length - 1).trimStart();
      const first = parseStringLiteral(args);
      if (first === null) {
        errors.push(
          `${label}:${line} registerComponentRole's first argument must be a string literal ` +
            `(F11) — the role registry is statically scanned.`,
        );
        continue;
      }
      const rest = args.slice(first.end).replace(/^\s*,\s*/, "");
      const component = parseStringLiteral(rest)?.value ?? rest.split(",")[0].trim();
      const replace = /\breplace\s*:\s*true\b/.test(args);
      sites.push({ file: label, line, role: first.value, component, replace });
    }
  }

  const byRole = new Map();
  for (const site of sites) {
    const group = byRole.get(site.role) ?? [];
    group.push(site);
    byRole.set(site.role, group);
  }
  for (const [role, group] of byRole) {
    const unforced = group.filter((site) => !site.replace);
    if (group.length > 1 && unforced.length > 1) {
      errors.push(
        `duplicate component role "${role}" registered at ` +
          group.map((site) => `${site.file}:${site.line} ("${site.component}")`).join(", ") +
          ` — compose the existing component, or pass { replace: true, reason: "<why>" }.`,
      );
    }
  }

  const roles = {};
  for (const site of sites) {
    roles[site.role] = site.component;
  }
  return { roles, errors };
}

const valueExports = parseValueExports(readFileSync(barrelPath, "utf8"));
if (valueExports.length === 0) {
  console.error(`generate-manifest: no value exports found in ${barrelPath}`);
  process.exit(1);
}

const hooks = valueExports.filter((name) => /^use[A-Z]/.test(name));
const components = valueExports.filter(
  (name) =>
    /^[A-Z][A-Za-z0-9]*$/.test(name) && /[a-z]/.test(name) && !NON_COMPONENT_VALUES.has(name),
);

const { roles, errors } = scanRoles(resolve(root, "src"));
if (errors.length > 0) {
  for (const error of errors) {
    console.error(`generate-manifest: ${error}`);
  }
  process.exit(1);
}

const manifest = {
  components: [...components].sort(),
  hooks: [...hooks].sort(),
  roles: Object.fromEntries(Object.entries(roles).sort(([a], [b]) => a.localeCompare(b))),
};

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(
  `generate-manifest: wrote ${manifest.components.length} components, ` +
    `${manifest.hooks.length} hooks, ${Object.keys(manifest.roles).length} roles -> dist/manifest.json`,
);
