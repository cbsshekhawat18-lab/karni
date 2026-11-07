/**
 * Component-role registration, feature-detected on @karni/ui's registry (the
 * same shape as @karni/payments-ui). SavedChart registers its role itself
 * when its module loads. `registerChartRoles` is the escape hatch: call it
 * with your own registry object.
 */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const CHART_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "saved-chart",
    component: "SavedChart",
    package: "@karni/charts-ui",
    description:
      "A chart saved in the admin, drawn from its source's aggregate (GET /charts/<slug>/data/).",
  },
];

type RegisterComponentRole = (role: string, component: string) => void;

/**
 * Registers each role on `registry.registerComponentRole` when present, with the
 * component's name (the same call SavedChart makes, so registering twice is a
 * no-op). Returns true when registration happened, false when it was skipped.
 */
export function registerChartRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of CHART_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition.component);
  }
  return true;
}
