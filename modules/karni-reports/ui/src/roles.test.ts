import * as karniUi from "@karni/ui";
import { describe, expect, it, vi } from "vitest";
import { REPORT_COMPONENT_ROLES, registerReportRoles } from "./roles";

describe("registerReportRoles", () => {
  it("registers report-button under its component name", () => {
    const registerComponentRole = vi.fn();
    expect(registerReportRoles({ registerComponentRole })).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledWith("report-button", "ReportButton");
  });

  it("skips a registry without registerComponentRole", () => {
    expect(registerReportRoles({})).toBe(false);
    expect(registerReportRoles(null)).toBe(false);
  });

  it("registers against the installed @karni/ui when it has the registry", () => {
    const hasRegistry =
      typeof (karniUi as Record<string, unknown>)["registerComponentRole"] === "function";
    expect(registerReportRoles()).toBe(hasRegistry);
    expect(REPORT_COMPONENT_ROLES.map((definition) => definition.role)).toEqual(["report-button"]);
  });
});
