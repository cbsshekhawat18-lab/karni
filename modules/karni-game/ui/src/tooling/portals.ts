import {
  CRAZYGAMES_SDK_URL,
  GAMEDISTRIBUTION_SDK_URL,
  POKI_SDK_URL,
  Y8_SDK_URL,
} from "../portal/sdks";

/** A value an adapter option takes from the project's config. */
export type PortalConfigValue = string | number | boolean;

/**
 * One portal a game can be built for. The table drives the per-portal build
 * (which adapter is bundled, which SDK tag goes in the page), the checks run
 * on each package and the documentation. A project adds or replaces rows
 * with `definePortals` instead of editing this file.
 */
export interface PortalRow {
  /** The build name: `--portal <name>`, and the folder each package lands in. */
  readonly name: string;
  readonly title: string;
  /** The adapter the build bundles: a module and the factory it exports. */
  readonly adapter: { readonly module: string; readonly factory: string };
  /** Adapter options a build cannot run without; their values come from the project's config. */
  readonly config: readonly string[];
  /** Adapter options the project's config may set. */
  readonly optionalConfig: readonly string[];
  /** Fixed adapter options for this row. */
  readonly options: Readonly<Record<string, PortalConfigValue>>;
  /** The SDK `<script>` the build puts in the page's head, or null (none, or the adapter loads it). */
  readonly headScript: string | null;
  /** The only external hosts the package may name. Empty: the package works offline. */
  readonly hosts: readonly string[];
  /** Text only this portal's SDK use contains: every other portal's package must be free of it. */
  readonly markers: readonly string[];
  /** Patterns that fail this portal's package, each with the reason. */
  readonly forbid: readonly { readonly pattern: string; readonly reason: string }[];
  /** Zip the package for upload. */
  readonly zip: boolean;
  /** The package's largest total size, in bytes. */
  readonly sizeBudget: number;
}

/** The size budget of a row that sets none: 20 MiB. Set each portal's own from its current rules. */
export const DEFAULT_SIZE_BUDGET = 20 * 1024 * 1024;

const row = (
  fields: Pick<PortalRow, "name" | "title" | "adapter"> & Partial<PortalRow>,
): PortalRow => ({
  config: [],
  optionalConfig: [],
  options: {},
  headScript: null,
  hosts: [],
  markers: [],
  forbid: [],
  zip: true,
  sizeBudget: DEFAULT_SIZE_BUDGET,
  ...fields,
});

const NONE = { module: "@karni/game/portals/none", factory: "noPortal" } as const;

/** The portals Karni knows. A build for one bundles that row's adapter and no other. */
export const PORTALS: readonly PortalRow[] = [
  row({
    name: "web",
    title: "Your own site",
    adapter: NONE,
    options: { name: "web" },
    zip: false,
  }),
  row({
    name: "itch",
    title: "itch.io",
    adapter: NONE,
    options: { name: "itch" },
  }),
  row({
    name: "poki",
    title: "Poki",
    adapter: { module: "@karni/game/portals/poki", factory: "poki" },
    headScript: POKI_SDK_URL,
    hosts: [new URL(POKI_SDK_URL).host],
    markers: ["PokiSDK", new URL(POKI_SDK_URL).host],
    forbid: [{ pattern: "setDebug", reason: "a Poki build must not turn on the SDK's debug mode" }],
  }),
  row({
    name: "crazygames",
    title: "CrazyGames",
    adapter: { module: "@karni/game/portals/crazygames", factory: "crazyGames" },
    headScript: CRAZYGAMES_SDK_URL,
    hosts: [new URL(CRAZYGAMES_SDK_URL).host],
    markers: ["CrazyGames", new URL(CRAZYGAMES_SDK_URL).host],
    // CrazyGames takes the files themselves, not a zip.
    zip: false,
  }),
  row({
    name: "gamedistribution",
    title: "GameDistribution",
    adapter: { module: "@karni/game/portals/gamedistribution", factory: "gameDistribution" },
    config: ["gameId"],
    hosts: [new URL(GAMEDISTRIBUTION_SDK_URL).host],
    markers: ["gdsdk", "GD_OPTIONS", new URL(GAMEDISTRIBUTION_SDK_URL).host],
  }),
  row({
    name: "y8",
    title: "Y8",
    adapter: { module: "@karni/game/portals/y8", factory: "y8" },
    config: ["appId"],
    optionalConfig: ["gameId", "autoLogin"],
    headScript: Y8_SDK_URL,
    hosts: [new URL(Y8_SDK_URL).host],
    markers: ["y8sdk.ready", new URL(Y8_SDK_URL).host],
  }),
];

/**
 * The portal table with a project's rows added or replaced by name. A row
 * given as a partial changes only the fields it names.
 */
export function definePortals(
  changes: readonly (Partial<PortalRow> & { name: string })[] = [],
  base: readonly PortalRow[] = PORTALS,
): PortalRow[] {
  const rows = base.map((existing) => ({ ...existing }));
  for (const change of changes) {
    const index = rows.findIndex((existing) => existing.name === change.name);
    const current = rows[index];
    if (current) {
      rows[index] = { ...current, ...change };
    } else if (change.adapter && change.title) {
      rows.push(row({ ...change, adapter: change.adapter, title: change.title }));
    } else {
      throw new Error(`portal "${change.name}" is new, so it needs a title and an adapter`);
    }
  }
  return rows;
}

export function portalRow(name: string, rows: readonly PortalRow[] = PORTALS): PortalRow {
  const found = rows.find((existing) => existing.name === name);
  if (!found) {
    throw new Error(
      `no portal named "${name}". Known: ${rows.map((existing) => existing.name).join(", ")}`,
    );
  }
  return found;
}
