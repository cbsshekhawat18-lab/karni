import { describe, expect, it, vi } from "vitest";
import { APPROVAL_COMPONENT_ROLES, registerApprovalRoles } from "./roles";

describe("registerApprovalRoles", () => {
  it("registers both roles on a registry that has registerComponentRole", () => {
    const registerComponentRole = vi.fn();
    expect(registerApprovalRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledTimes(APPROVAL_COMPONENT_ROLES.length);
    expect(registerComponentRole.mock.calls.map((call) => call[0])).toEqual([
      "approvals-queue",
      "approvals-badge",
    ]);
  });

  it("skips silently without a registry", () => {
    expect(registerApprovalRoles({})).toBe(false);
    expect(registerApprovalRoles(null)).toBe(false);
  });
});
