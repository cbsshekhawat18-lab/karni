import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FieldDef } from "../../../schema/types";
import { createHistoryStateStore, decodeFilter, encodeFilter } from "./url-state";

function field(partial: Partial<FieldDef> & Pick<FieldDef, "name" | "kind">): FieldDef {
  return {
    label: partial.name,
    required: false,
    readOnly: false,
    writeOnly: false,
    nullable: false,
    order: 0,
    ...partial,
  };
}

beforeEach(() => window.history.replaceState(null, "", "/events?tab=all#top"));
afterEach(() => window.history.replaceState(null, "", "/"));

describe("createHistoryStateStore", () => {
  it("merges its keys into the URL, keeping the path, other params and the hash", () => {
    const store = createHistoryStateStore();
    store.write({ "events.page": "2", "events.search": "gala" }, { push: true });
    expect(window.location.pathname).toBe("/events");
    expect(window.location.hash).toBe("#top");
    expect(store.read()).toEqual({ tab: "all", "events.page": "2", "events.search": "gala" });
    store.write({ "events.search": null }, { push: false });
    expect(store.read()).toEqual({ tab: "all", "events.page": "2" });
  });

  it("pushes a history entry or replaces the current one", () => {
    const store = createHistoryStateStore();
    const before = window.history.length;
    store.write({ "events.page": "2" }, { push: true });
    expect(window.history.length).toBe(before + 1);
    store.write({ "events.page": "3" }, { push: false });
    expect(window.history.length).toBe(before + 1);
    // Writing what is already there adds nothing.
    store.write({ "events.page": "3" }, { push: true });
    expect(window.history.length).toBe(before + 1);
  });

  it("tells subscribers about Back/Forward and about other tables' writes", () => {
    const store = createHistoryStateStore();
    const onChange = vi.fn();
    const unsubscribe = store.subscribe(onChange);
    window.dispatchEvent(new PopStateEvent("popstate"));
    createHistoryStateStore().write({ "bookings.page": "2" }, { push: true });
    expect(onChange).toHaveBeenCalledTimes(2);
    unsubscribe();
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});

describe("filter values in the URL", () => {
  it("round-trips each filter kind to the type its control and the API expect", () => {
    const status = field({ name: "status", kind: "enum", enumValues: ["DRAFT", 3] });
    const isPublic = field({ name: "is_public", kind: "boolean" });
    const venue = field({
      name: "venue",
      kind: "relation",
      relation: { resource: "venues", many: false },
      relationValueType: "integer",
    });
    const tags = field({
      name: "tags",
      kind: "relation",
      relation: { resource: "tags", many: true },
      relationValueType: "uuid",
    });
    expect(decodeFilter("DRAFT", status)).toBe("DRAFT");
    expect(decodeFilter("3", status)).toBe(3);
    expect(decodeFilter("BOGUS", status)).toBeUndefined();
    expect(decodeFilter(encodeFilter(false) ?? "", isPublic)).toBe(false);
    expect(decodeFilter("7", venue)).toBe(7);
    expect(encodeFilter(["a", "b"])).toBe("a,b");
    expect(decodeFilter("a,b", tags)).toEqual(["a", "b"]);
    expect(encodeFilter([])).toBeNull();
    expect(encodeFilter(null)).toBeNull();
  });
});
