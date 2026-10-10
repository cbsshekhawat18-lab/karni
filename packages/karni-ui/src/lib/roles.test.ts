/**
 * Component role registry — runtime semantics (enforcement contract §4 + F11):
 * idempotent re-registration, conflict throw in prod/test, explicit
 * replace-with-reason opt-out, and the HMR replace-instead-of-throw branch
 * (approximated by overriding the import.meta.hot detector, as the module
 * cannot see a real Vite dev server under vitest).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetRoleRegistryForTests,
  __setHotDetectorForTests,
  getRoleRegistry,
  registerComponentRole,
} from "./roles";

beforeEach(() => {
  __resetRoleRegistryForTests();
});

afterEach(() => {
  __setHotDetectorForTests(null);
});

describe("registerComponentRole", () => {
  it("registers a role and exposes it through getRoleRegistry", () => {
    registerComponentRole("data-table", "ResourceTable");
    expect(getRoleRegistry()).toEqual({ "data-table": "ResourceTable" });
  });

  it("is idempotent for the same role + component name", () => {
    registerComponentRole("data-table", "ResourceTable");
    expect(() => registerComponentRole("data-table", "ResourceTable")).not.toThrow();
    expect(getRoleRegistry()).toEqual({ "data-table": "ResourceTable" });
  });

  it("throws when a different component claims a registered role", () => {
    registerComponentRole("data-table", "ResourceTable");
    expect(() => registerComponentRole("data-table", "FancyTable")).toThrowError(
      /duplicate component role "data-table".*ResourceTable.*FancyTable/,
    );
    // The original registration survives the rejected claim.
    expect(getRoleRegistry()).toEqual({ "data-table": "ResourceTable" });
  });

  it("replaces when asked to, with a reason, and logs the replacement", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    registerComponentRole("data-table", "ResourceTable");
    registerComponentRole("data-table", "FancyTable", {
      replace: true,
      reason: "project-specific table with tree grouping",
    });
    expect(getRoleRegistry()).toEqual({ "data-table": "FancyTable" });
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("tree grouping"));
  });

  it("throws when replace: true carries no reason", () => {
    registerComponentRole("data-table", "ResourceTable");
    expect(() => registerComponentRole("data-table", "FancyTable", { replace: true })).toThrowError(
      /non-empty reason/,
    );
    expect(() =>
      registerComponentRole("data-table", "FancyTable", { replace: true, reason: "   " }),
    ).toThrowError(/non-empty reason/);
    expect(getRoleRegistry()).toEqual({ "data-table": "ResourceTable" });
  });

  it("allows replace with reason even for an unregistered role", () => {
    registerComponentRole("data-table", "FancyTable", { replace: true, reason: "first claim" });
    expect(getRoleRegistry()).toEqual({ "data-table": "FancyTable" });
  });

  it("replaces and console.errors instead of throwing under HMR", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    registerComponentRole("data-table", "ResourceTable");
    __setHotDetectorForTests(() => true);
    expect(() => registerComponentRole("data-table", "RenamedTable")).not.toThrow();
    expect(getRoleRegistry()).toEqual({ "data-table": "RenamedTable" });
    expect(error).toHaveBeenCalledWith(
      expect.stringContaining('duplicate component role "data-table"'),
    );
  });

  it("stays idempotent under HMR too", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    __setHotDetectorForTests(() => true);
    registerComponentRole("modal", "Modal");
    registerComponentRole("modal", "Modal");
    expect(error).not.toHaveBeenCalled();
    expect(getRoleRegistry()).toEqual({ modal: "Modal" });
  });
});

describe("getRoleRegistry", () => {
  it("returns a frozen snapshot, not the live registry", () => {
    registerComponentRole("stat", "Stat");
    const snapshot = getRoleRegistry();
    expect(Object.isFrozen(snapshot)).toBe(true);
    registerComponentRole("chart", "DataChart");
    expect(snapshot).toEqual({ stat: "Stat" });
    expect(getRoleRegistry()).toEqual({ stat: "Stat", chart: "DataChart" });
  });
});

describe("package self-registrations", () => {
  it("registers every top-level component role on import of the barrel", async () => {
    // Import AFTER the reset above so this file observes the registrations.
    await import("../index");
    // FileUpload self-registers too but is not yet re-exported from the
    // barrel, so its module is imported directly here.
    await import("../components/file-upload/FileUpload");
    expect(getRoleRegistry()).toEqual({
      "async-select": "ResourceSelect",
      "auth-guard": "AuthGuard",
      chart: "DataChart",
      "data-table": "ResourceTable",
      "detail-view": "ResourceDetail",
      "empty-state": "EmptyState",
      "file-upload": "FileUpload",
      "layout-shell": "Layout",
      "login-form": "LoginForm",
      modal: "Modal",
      "page-shell": "Page",
      "resource-form": "ResourceForm",
      stat: "Stat",
      toast: "Toaster",
    });
  });
});
