import * as karniUi from "@karni/ui";
import { describe, expect, it, vi } from "vitest";
import { STORAGE_COMPONENT_ROLES, registerStorageRoles } from "./roles";

describe("registerStorageRoles (G8 feature detection)", () => {
  it("registers every role on a registry that supports roles", () => {
    const registerComponentRole = vi.fn();
    expect(registerStorageRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledTimes(3);
    expect(registerComponentRole).toHaveBeenCalledWith(
      "protected-file-input",
      expect.objectContaining({ component: "ProtectedFileInput" }),
    );
  });

  it("skips silently when the registry lacks registerComponentRole", () => {
    expect(registerStorageRoles({})).toBe(false);
    expect(registerStorageRoles(null)).toBe(false);
  });

  it("follows the installed @karni/ui", () => {
    const hasRegistry =
      typeof (karniUi as Record<string, unknown>)["registerComponentRole"] === "function";
    expect(registerStorageRoles()).toBe(hasRegistry);
    expect(STORAGE_COMPONENT_ROLES.map((role) => role.role)).toEqual([
      "protected-file-input",
      "protected-file-link",
      "protected-image",
    ]);
  });
});
