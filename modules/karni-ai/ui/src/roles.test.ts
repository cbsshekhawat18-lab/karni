import { describe, expect, it, vi } from "vitest";
import { AI_COMPONENT_ROLES, registerAiRoles } from "./roles";

describe("registerAiRoles", () => {
  it("registers the extract button on a registry that has registerComponentRole", () => {
    const registerComponentRole = vi.fn();
    expect(registerAiRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledTimes(AI_COMPONENT_ROLES.length);
    expect(registerComponentRole.mock.calls[0]?.[0]).toBe("extract-button");
  });

  it("skips silently without a registry", () => {
    expect(registerAiRoles({})).toBe(false);
  });
});
