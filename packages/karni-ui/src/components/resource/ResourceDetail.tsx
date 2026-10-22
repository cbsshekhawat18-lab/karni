/**
 * Barrel-facing path for <ResourceDetail>. The implementation lives in
 * ./detail/ (resource form builder). Every contract-pinned export name is
 * re-exported here so src/index.ts keeps resolving this module.
 */
export { ResourceDetail, defaultResourceDetailSlots } from "./detail/ResourceDetail";
export type {
  ResourceDetailProps,
  ResourceDetailFieldOverride,
  ResourceDetailSlots,
  ResourceDetailLoadingProps,
  ResourceDetailErrorProps,
  ResourceDetailNotFoundProps,
  ResourceDetailDeletedProps,
  ResourceDetailEmptyValueProps,
  ResourceDetailDeleteDialogProps,
} from "./detail/ResourceDetail";
