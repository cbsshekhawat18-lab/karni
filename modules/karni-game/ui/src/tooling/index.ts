/**
 * @karni/game/build: the Node side of a game's build. Nothing here is
 * bundled into a game.
 */
export { DEFAULT_SIZE_BUDGET, PORTALS, definePortals, portalRow } from "./portals";
export type { PortalConfigValue, PortalRow } from "./portals";
export {
  API_URL_ENV,
  PortalConfigError,
  apiHosts,
  envName,
  resolveApiUrl,
  resolvePortal,
} from "./config";
export type { PortalConfig, ResolveOptions } from "./config";
export { checkPackage, checkSource, formatProblems, hostsIn } from "./checks";
export type { BuildProblem, CheckOptions, SourceCheckOptions } from "./checks";
export { packagePortals, viteBuild } from "./package";
export type { PackageOptions, PackageReport } from "./package";
export { crc32, zipFolder } from "./zip";
export { checkRules, formatImpurities } from "./rules";
export type { Impurity } from "./rules";
