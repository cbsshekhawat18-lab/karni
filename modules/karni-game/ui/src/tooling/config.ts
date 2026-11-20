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

/** The build environment variable that names the game API a portal build calls. */
export const API_URL_ENV = "KARNI_GAME_API_URL";

/**
 * The game API a build calls: `apiUrl`, else `KARNI_GAME_API_URL`, else
 * null (the page's own origin, as the project's own site has it). A game on
 * a portal runs on the portal's domain, so its build names the API's
 * absolute URL (`https://api.example.com`), and the server lists the
 * portal's origin in `KARNI_GAME_CORS_ORIGINS`.
 */
export function resolveApiUrl(
  apiUrl: string | undefined,
  env: Readonly<Record<string, string | undefined>> = {},
): string | null {
  const value = (apiUrl ?? env[API_URL_ENV] ?? "").trim();
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new PortalConfigError(
      `${API_URL_ENV}=${value} is not an absolute URL: name the game API as https://api.example.com`,
    );
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new PortalConfigError(`${API_URL_ENV}=${value} is not an http(s) URL`);
  }
  return value.replace(/\/+$/, "");
}

/** The host a package may name for the game API (`api.example.com`), or none. */
export function apiHosts(apiUrl: string | null): string[] {
  return apiUrl ? [new URL(apiUrl).hostname] : [];
}
