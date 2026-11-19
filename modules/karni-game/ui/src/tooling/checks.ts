import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { PORTALS, type PortalRow } from "./portals";

export interface BuildProblem {
  /** A short name of the rule: "size", "host", "debug-hook", ... */
  rule: string;
  /** The file, relative to the package folder. */
  file?: string;
  message: string;
}

export interface CheckOptions {
  /** The portal table, to know every other portal's markers. Default Karni's. */
  portals?: readonly PortalRow[];
  /** Hosts allowed besides the row's (the game's own API, a font host). */
  allowHosts?: readonly string[];
  /** Let `console.log` and `console.debug` through. Default false. */
  allowConsole?: boolean;
  /** Patterns of the project's own that fail the build, each with its reason. */
  forbid?: readonly { pattern: string | RegExp; reason: string }[];
}

const TEXT = new Set([
  ".html",
  ".htm",
  ".js",
  ".mjs",
  ".cjs",
  ".css",
  ".json",
  ".svg",
  ".txt",
  ".webmanifest",
]);

/** Namespace and spec URLs that appear in libraries and are never fetched. */
const NAMESPACE_HOSTS = new Set([
  "www.w3.org",
  "w3.org",
  "www.khronos.org",
  "reactjs.org",
  "react.dev",
]);

const SECRET_SHAPES: readonly { name: string; pattern: RegExp }[] = [
  { name: "a private key", pattern: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: "a live payment key", pattern: /\b(?:sk|rk)_live_[A-Za-z0-9]{16,}/ },
  { name: "a cloud access key", pattern: /\bAKIA[0-9A-Z]{16}\b/ },
  { name: "a source-host token", pattern: /\bgh[pousr]_[A-Za-z0-9]{36,}\b/ },
  { name: "a chat-app token", pattern: /\bxox[abprs]-[A-Za-z0-9-]{10,}/ },
  {
    name: "a secret assigned in code",
    pattern:
      /\b(?:secret|api[_-]?key|private[_-]?key|password)\s*[:=]\s*["'][A-Za-z0-9+/_-]{20,}["']/i,
  },
];

/** Debug hooks that must not reach players: globals for tests, breakpoints. */
const DEBUG_HOOKS: readonly { name: string; pattern: RegExp }[] = [
  {
    name: "a window.__ global (a test or debug hook)",
    pattern: /\b(?:window|globalThis|self)\.__[A-Za-z0-9_$]+\s*=(?!=)/,
  },
  { name: "a debugger statement", pattern: /(?:^|[;{}\s])debugger\s*;/ },
];

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) files.push(...walk(path));
    else files.push(path);
  }
  return files;
}

/** Every http(s) URL host in a text, without the namespace hosts libraries carry. */
export function hostsIn(text: string): { host: string; url: string }[] {
  const found: { host: string; url: string }[] = [];
  for (const match of text.matchAll(/\b(https?):\/\/([A-Za-z0-9.-]+(?::\d+)?)([^\s"'`<>)]*)/g)) {
    const host = (match[2] ?? "").toLowerCase().replace(/:\d+$/, "");
    if (NAMESPACE_HOSTS.has(host) || (!host.includes(".") && host !== "localhost")) continue;
    found.push({ host, url: match[0] });
  }
  return found;
}

/**
 * Check one portal's package: index.html at its root, relative paths only,
 * no host but the portal's own, no other portal's SDK, no localhost or
 * plain-http address, no secret-shaped token, no stray debug hook or
 * console call, the row's forbidden patterns, and the size budget.
 */
export function checkPackage(
  dir: string,
  row: PortalRow,
  options: CheckOptions = {},
): BuildProblem[] {
  const problems: BuildProblem[] = [];
  if (!existsSync(join(dir, "index.html"))) {
    problems.push({ rule: "index", message: "index.html is not at the package's root" });
  }
  const files = existsSync(dir) ? walk(dir) : [];
  const total = files.reduce((sum, file) => sum + statSync(file).size, 0);
  if (total > row.sizeBudget) {
    problems.push({
      rule: "size",
      message: `the package is ${total} bytes, over the ${row.title} budget of ${row.sizeBudget}`,
    });
  }
  const allowed = new Set(
    [...row.hosts, ...(options.allowHosts ?? [])].map((host) => host.toLowerCase()),
  );
  const others = (options.portals ?? PORTALS).filter((other) => other.name !== row.name);
  const forbid = [
    ...row.forbid.map((rule) => ({ pattern: new RegExp(rule.pattern), reason: rule.reason })),
    ...(options.forbid ?? []).map((rule) => ({
      pattern: typeof rule.pattern === "string" ? new RegExp(rule.pattern) : rule.pattern,
      reason: rule.reason,
    })),
  ];

  for (const path of files) {
    if (!TEXT.has(extname(path).toLowerCase()) || path.endsWith(".map")) continue;
    const file = relative(dir, path);
    const text = readFileSync(path, "utf8");
    const add = (rule: string, message: string): void =>
      void problems.push({ rule, file, message });

    if (extname(path) === ".html") {
      for (const match of text.matchAll(/\b(?:src|href)="(\/[^/"][^"]*)"/g)) {
        add(
          "absolute-path",
          `${match[1]} starts at the site's root: the package must use relative paths`,
        );
      }
    }
    for (const { host, url } of hostsIn(text)) {
      if (host === "localhost" || host.startsWith("127.") || host.startsWith("0.0.0.0")) {
        add("localhost", `${url} points at a development machine`);
      } else if (url.startsWith("http://")) {
        add("insecure-url", `${url} is plain http: a portal's page is https`);
      } else if (!allowed.has(host)) {
        add("host", `${url} names ${host}, which the ${row.title} package may not load`);
      }
    }
    for (const other of others) {
      for (const marker of other.markers) {
        if (text.includes(marker))
          add("other-portal", `${marker} belongs to ${other.title}: one SDK per build`);
      }
    }
    for (const { pattern, reason } of forbid) {
      if (pattern.test(text)) add("forbidden", reason);
    }
    for (const { name, pattern } of SECRET_SHAPES) {
      if (pattern.test(text)) add("secret", `the package holds ${name}`);
    }
    for (const { name, pattern } of DEBUG_HOOKS) {
      if (pattern.test(text))
        add("debug-hook", `the package has ${name}: guard it with __KARNI_GAME_DEV__`);
    }
    if (!options.allowConsole && /\bconsole\.(?:log|debug)\s*\(/.test(text)) {
      add("console", "console.log or console.debug is left in: guard it with __KARNI_GAME_DEV__");
    }
  }
  return problems;
}

export interface SourceCheckOptions {
  /** The ids of the project's config: none may be typed into the source. */
  ids?: readonly string[];
  /** File extensions to read. Default .js, .mjs, .cjs, .ts, .tsx, .jsx, .html, .json. */
  extensions?: readonly string[];
}

const ID_ASSIGNMENT =
  /\b(?:gameId|appId|game_id|app_id|adClient|ad_client)\s*[:=]\s*["']([A-Za-z0-9_-]{8,})["']/;

/**
 * Check a game's source and build scripts for portal ids typed into code.
 * Ids belong in the project's config or the build environment, so the same
 * source builds for every portal and no id leaks into another's package.
 */
export function checkSource(
  dirs: readonly string[],
  options: SourceCheckOptions = {},
): BuildProblem[] {
  const extensions = new Set(
    options.extensions ?? [".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".json"],
  );
  const ids = (options.ids ?? []).filter((id) => id.length >= 6);
  const problems: BuildProblem[] = [];
  for (const dir of dirs) {
    if (!existsSync(dir)) continue;
    for (const path of walk(dir)) {
      if (
        relative(dir, path).split(/[\\/]/).includes("node_modules") ||
        !extensions.has(extname(path))
      ) {
        continue;
      }
      const text = readFileSync(path, "utf8");
      const lines = text.split("\n");
      lines.forEach((line, index) => {
        const file = `${relative(process.cwd(), path)}:${index + 1}`;
        const assigned = line.match(ID_ASSIGNMENT);
        if (assigned) {
          problems.push({
            rule: "hard-coded-id",
            file,
            message: `${assigned[0]}: read the id from the config or the build environment`,
          });
        }
        for (const id of ids) {
          if (line.includes(id)) {
            problems.push({
              rule: "hard-coded-id",
              file,
              message: "a configured portal id is typed into the source",
            });
          }
        }
      });
    }
  }
  return problems;
}

export function formatProblems(problems: readonly BuildProblem[]): string {
  return problems.map((p) => `  ${p.rule}${p.file ? ` ${p.file}` : ""}: ${p.message}`).join("\n");
}
