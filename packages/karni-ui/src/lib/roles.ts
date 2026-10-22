/**
 * Component role registry (enforcement contract §4 + F11).
 *
 * Every top-level component claims a semantic role ("data-table",
 * "resource-form", …) at module scope. Two components claiming the same role
 * is a conflict: it throws at import time (so vitest and the dev server both
 * surface it) and `scripts/generate-manifest.mjs` fails the build on the same
 * duplicate via a static scan of these call sites.
 *
 * Conventions:
 * - The `role` argument MUST be a string literal. The build-time scan rejects
 *   any non-literal first argument.
 * - Same role + same component name is idempotent (modules re-evaluate under
 *   HMR and across test files).
 * - Replacing on purpose is explicit and must carry a reason:
 *   `{ replace: true, reason: "<why>" }`. An empty reason throws.
 * - Under Vite HMR (`import.meta.hot`) an accidental conflict logs a
 *   console.error and replaces instead of throwing, so a rename mid-edit does
 *   not kill the dev server.
 * - The registry reflects imported modules only (accepted v0.1 trade-off).
 */

export interface RegisterComponentRoleOptions {
  /** Replace an existing registration on purpose. Requires `reason`. */
  replace?: boolean;
  /** Why the replacement is intentional. Required with `replace: true`. */
  reason?: string;
}

const registry = new Map<string, string>();

/**
 * `import.meta.hot` is defined by Vite's dev server and undefined in prod
 * builds. Vitest also ships an import.meta.hot stub, but tests must throw on
 * conflicts (F11), so the test environment is explicitly excluded.
 */
function defaultHotDetector(): boolean {
  try {
    const meta = import.meta as ImportMeta & { hot?: unknown; env?: { MODE?: string } };
    if (!meta.hot) return false;
    if (meta.env?.MODE === "test") return false;
    if (typeof process !== "undefined" && process.env?.VITEST !== undefined) return false;
    return true;
  } catch {
    return false;
  }
}

let detectHot: () => boolean = defaultHotDetector;

/**
 * Test-only override for HMR detection. Pass `null` to restore the default.
 * Not exported from the package barrel.
 * @internal
 */
export function __setHotDetectorForTests(detector: (() => boolean) | null): void {
  detectHot = detector ?? defaultHotDetector;
}

/**
 * Test-only registry reset. Not exported from the package barrel.
 * @internal
 */
export function __resetRoleRegistryForTests(): void {
  registry.clear();
}

/**
 * Claims a UI role (such as `data-table`) for a component, so a second component with the same role fails the build. The first argument must be a string literal
 * (build-scan convention, F11).
 */
export function registerComponentRole(
  role: string,
  component: string,
  options?: RegisterComponentRoleOptions,
): void {
  if (options?.replace) {
    const reason = options.reason?.trim() ?? "";
    if (reason === "") {
      throw new Error(
        `[karni] registerComponentRole: replacing role "${role}" requires a non-empty reason. ` +
          `Pass { replace: true, reason: "<why>" }.`,
      );
    }
    const previous = registry.get(role);
    if (previous !== undefined && previous !== component) {
      console.warn(
        `[karni] component role "${role}" replaced: "${previous}" -> "${component}" (${reason})`,
      );
    }
    registry.set(role, component);
    return;
  }

  const existing = registry.get(role);
  if (existing === undefined || existing === component) {
    // Idempotent: first registration, or the same component re-registering.
    registry.set(role, component);
    return;
  }

  const message =
    `[karni] duplicate component role "${role}": already registered by "${existing}", now ` +
    `claimed by "${component}". Compose or extend the existing component instead, or replace ` +
    `it on purpose with { replace: true, reason: "<why>" }.`;

  if (detectHot()) {
    // Dev HMR: a module re-evaluating mid-rename must not kill the app.
    console.error(message);
    registry.set(role, component);
    return;
  }
  throw new Error(message);
}

/** Snapshot of the current registry ({ role: component }) for tooling. */
export function getRoleRegistry(): Readonly<Record<string, string>> {
  return Object.freeze(Object.fromEntries(registry));
}
