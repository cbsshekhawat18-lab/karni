/**
 * Component-role registration, feature-detected on @karni/ui's registry
 * (the same shape as @karni/payments-ui). `registerApprovalRoles` is the
 * escape hatch: call it with your own registry object.
 */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const APPROVAL_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "approvals-queue",
    component: "ApprovalsQueue",
    package: "@karni/approvals-ui",
    description: "The pending changes the user may decide, with Approve / Reject and a reason.",
  },
  {
    role: "approvals-badge",
    component: "ApprovalsBadge",
    package: "@karni/approvals-ui",
    description:
      "A count of the pending changes the user may decide (GET /pending-changes/count/).",
  },
];

type RegisterComponentRole = (role: string, definition: ComponentRoleDefinition) => void;

/** Registers both roles when the installed @karni/ui exposes the registry. */
export function registerApprovalRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of APPROVAL_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition);
  }
  return true;
}
