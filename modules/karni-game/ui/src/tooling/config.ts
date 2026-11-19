import { portalRow, PORTALS, type PortalConfigValue, type PortalRow } from "./portals";

/** A project's portal ids and settings, by portal and option: `{ gamedistribution: { gameId } }`. */
export type PortalConfig = Readonly<
  Record<string, Readonly<Record<string, PortalConfigValue | undefined>>>
>;

export interface ResolveOptions {
  portals?: readonly PortalRow[];
  config?: PortalConfig;
  env?: Readonly<Record<string, string | undefined>>;
}

/** The build environment variable an option is read from: `KARNI_GAME_GAMEDISTRIBUTION_GAME_ID`. */
export function envName(portal: string, option: string): string {
  const snake = option.replace(/([a-z0-9])([A-Z])/g, "$1_$2");
  return `KARNI_GAME_${portal}_${snake}`.replace(/[^A-Za-z0-9]+/g, "_").toUpperCase();
}

const parse = (value: string): PortalConfigValue =>
  value === "true" ? true : value === "false" ? false : value;

export class PortalConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalConfigError";
  }
}

/**
 * The adapter options one portal's build is made with: the row's fixed
 * options, then the project's config, then the build environment. A
 * required option that none of them sets stops the build, naming where to
 * set it. The ids never live in the game's source.
 */
export function resolvePortal(
  name: string,
  options: ResolveOptions = {},
): { row: PortalRow; options: Record<string, PortalConfigValue> } {
  const row = portalRow(name, options.portals ?? PORTALS);
  const given = options.config?.[name] ?? {};
  const env = options.env ?? {};
  const resolved: Record<string, PortalConfigValue> = { ...row.options };
  const missing: string[] = [];
  for (const option of [...row.config, ...row.optionalConfig]) {
    const fromConfig = given[option];
    const fromEnv = env[envName(name, option)];
    if (fromConfig !== undefined && fromConfig !== "") resolved[option] = fromConfig;
    else if (fromEnv !== undefined && fromEnv !== "") resolved[option] = parse(fromEnv);
    else if (row.config.includes(option)) missing.push(option);
  }
  if (missing.length > 0) {
    throw new PortalConfigError(
      `The ${row.title} build needs ${missing.join(", ")}: set ${missing
        .map((option) => envName(name, option))
        .join(", ")} in the build environment, or config.${name}.${missing[0]} in karniGame().`,
    );
  }
  return { row, options: resolved };
}
