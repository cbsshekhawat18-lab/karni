/** Component-role registration, feature-detected on @karni/ui's registry. */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const IMPERSONATION_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "impersonation-banner",
    component: "ImpersonationBanner",
    package: "@karni/impersonation-ui",
    description:
      "The persistent bar naming both identities during an impersonated session, with Stop.",
  },
];

type RegisterComponentRole = (role: string, definition: ComponentRoleDefinition) => void;

export function registerImpersonationRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of IMPERSONATION_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition);
  }
  return true;
}
