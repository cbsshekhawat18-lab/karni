/**
 * Component-role registration (contract G8), feature-detected like the other
 * module UI packages: when @karni/ui exports `registerComponentRole`, the
 * storage roles are registered at import time. `registerStorageRoles` is the
 * escape hatch: call it with your own registry object.
 */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const STORAGE_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "protected-file-input",
    component: "ProtectedFileInput",
    package: "@karni/storage-ui",
    description: "A protected file field of ResourceForm, uploaded straight to the bucket.",
  },
  {
    role: "protected-file-link",
    component: "ProtectedFileLink",
    package: "@karni/storage-ui",
    description: "A link that opens a protected file through a short-lived signed URL.",
  },
  {
    role: "protected-image",
    component: "ProtectedImage",
    package: "@karni/storage-ui",
    description: "A protected image or its thumbnail through a short-lived signed URL.",
  },
];

type RegisterComponentRole = (role: string, definition: ComponentRoleDefinition) => void;

/** Registers the roles on `registry.registerComponentRole` when present (G8). */
export function registerStorageRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of STORAGE_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition);
  }
  return true;
}
