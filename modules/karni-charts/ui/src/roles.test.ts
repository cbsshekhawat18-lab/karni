import * as karniUi from "@karni/ui";
import { describe, expect, it, vi } from "vitest";
import { CHART_COMPONENT_ROLES, registerChartRoles } from "./roles";
import "./SavedChart";

describe("registerChartRoles (feature detection)", () => {
  it("registers saved-chart with the component's name on a registry that supports roles", () => {
    const registerComponentRole = vi.fn();
    expect(registerChartRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledWith("saved-chart", "SavedChart");
  });

  it("skips silently when the registry lacks registerComponentRole", () => {
    expect(registerChartRoles({})).toBe(false);
    expect(registerChartRoles(null)).toBe(false);
  });

  it("is a no-op next to SavedChart's own registration", () => {
    expect(registerChartRoles()).toBe(true);
    expect(karniUi.getRoleRegistry()["saved-chart"]).toBe("SavedChart");
    expect(CHART_COMPONENT_ROLES.map((definition) => definition.role)).toEqual(["saved-chart"]);
  });
});
