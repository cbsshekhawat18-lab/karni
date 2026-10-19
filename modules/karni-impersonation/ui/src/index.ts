/** @karni/impersonation-ui public barrel: explicit exports only. */
import { registerImpersonationRoles } from "./roles";

export { ImpersonationBanner } from "./ImpersonationBanner";
export type { ImpersonationBannerProps } from "./ImpersonationBanner";

export {
  RESOURCE,
  impersonationKey,
  useImpersonation,
  useStartImpersonation,
  useStopImpersonation,
} from "./hooks";
export type { StartInput, UseImpersonationOptions } from "./hooks";

export type {
  CurrentResponse,
  EndReason,
  ImpersonationSession,
  Person,
  SessionResponse,
} from "./types";

export { IMPERSONATION_COMPONENT_ROLES, registerImpersonationRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

registerImpersonationRoles();
