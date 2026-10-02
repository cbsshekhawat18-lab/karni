/**
 * Barrel-facing path for <ResourceSelect>. The implementation lives in
 * ./select/ (resource form builder); every contract-pinned export name is
 * re-exported here so src/index.ts keeps resolving this module.
 */
export { ResourceSelect } from "./select/ResourceSelect";
export type { ResourceSelectProps } from "./select/ResourceSelect";
