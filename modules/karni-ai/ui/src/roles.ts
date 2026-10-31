/** Component-role registration, feature-detected on @karni/ui's registry. */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const AI_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "extract-button",
    component: "ExtractButton",
    package: "@karni/ai-ui",
    description:
      "Reads rows of a resource from a text, a web page or a PDF into the import preview, then commits them.",
  },
];

type RegisterComponentRole = (role: string, definition: ComponentRoleDefinition) => void;

/** Experimental. Registers the package's components in @karni/ui's role registry, if any. */
export function registerAiRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of AI_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition);
  }
  return true;
}
