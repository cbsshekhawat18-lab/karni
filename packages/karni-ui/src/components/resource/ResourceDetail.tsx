/**
 * Barrel-facing path for <ResourceDetail>. The implementation lives in
 * ./detail/ (resource form builder); every contract-pinned export name is
 * re-exported here so src/index.ts keeps resolving this module.
 */
export { ResourceDetail } from "./detail/ResourceDetail";
export type { ResourceDetailProps, ResourceDetailFieldOverride } from "./detail/ResourceDetail";
