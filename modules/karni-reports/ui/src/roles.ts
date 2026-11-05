/**
 * Component-role registration, feature-detected on @karni/ui's registry.
 *
 * Experimental. When the installed @karni/ui exports `registerComponentRole`,
 * the role `report-button` is registered at import time under the component
 * name. `registerReportRoles` is the escape hatch: call it with your own
 * registry object to register the role elsewhere.
 */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const REPORT_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "report-button",
    component: "ReportButton",
    package: "@karni/reports-ui",
    description: "Requests the PDF report of one row, follows its status and downloads it.",
  },
];

type RegisterComponentRole = (role: string, component: string) => void;

/** Registers the roles when `registry` has `registerComponentRole`. False when it was skipped. */
export function registerReportRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of REPORT_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition.component);
  }
  return true;
}
