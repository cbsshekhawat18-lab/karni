/**
 * @karni/approvals-ui public barrel: explicit exports only, mirroring @karni/ui.
 */
import { registerApprovalRoles } from "./roles";

export { ApprovalsQueue } from "./ApprovalsQueue";
export type { ApprovalsQueueProps } from "./ApprovalsQueue";

export { ApprovalsBadge } from "./ApprovalsBadge";
export type { ApprovalsBadgeProps } from "./ApprovalsBadge";

export {
  RESOURCE,
  pendingCountKey,
  useDecidePendingChange,
  usePendingChanges,
  usePendingCount,
} from "./hooks";
export type { DecideInput, UsePendingCountOptions } from "./hooks";

export { PENDING_STATUSES } from "./types";
export type {
  Decision,
  PendingAction,
  PendingChange,
  PendingCount,
  PendingStatus,
  Person,
} from "./types";

export { APPROVAL_COMPONENT_ROLES, registerApprovalRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

registerApprovalRoles();
