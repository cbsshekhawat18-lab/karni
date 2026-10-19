import { describe, expect, it, vi } from "vitest";
import { IMPERSONATION_COMPONENT_ROLES, registerImpersonationRoles } from "./roles";

describe("registerImpersonationRoles", () => {
  it("registers the banner role on a registry that has registerComponentRole", () => {
    const registerComponentRole = vi.fn();
    expect(registerImpersonationRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledTimes(IMPERSONATION_COMPONENT_ROLES.length);
    expect(registerComponentRole.mock.calls[0]?.[0]).toBe("impersonation-banner");
  });

  it("skips silently without a registry", () => {
    expect(registerImpersonationRoles({})).toBe(false);
  });
});
