/**
 * karniKeys shape + normalization tests (contract D4).
 */
import { describe, expect, it } from "vitest";
import { karniKeys } from "./keys";

describe("karniKeys.schema / resource", () => {
  it("pins the schema key to ['karni', '$schema']", () => {
    expect(karniKeys.schema()).toEqual(["karni", "$schema"]);
  });

  it("pins the resource root to ['karni', resource]", () => {
    expect(karniKeys.resource("events")).toEqual(["karni", "events"]);
  });
});

describe("karniKeys.list (D4 normalization)", () => {
  it("has the pinned shape ['karni', resource, 'list', params]", () => {
    const key = karniKeys.list("events");
    expect(key.slice(0, 3)).toEqual(["karni", "events", "list"]);
    expect(key[3]).toEqual({});
    expect(key).toHaveLength(4);
  });

  it("stringifies values as they hit the query string", () => {
    const key = karniKeys.list("events", {
      page: 2,
      pageSize: 10,
      ordering: "-starts_at",
      search: "conf",
      expand: ["venue", "organizer"],
      filters: { status: "published", is_public: true, capacity: 10 },
    });
    expect(key[3]).toEqual({
      capacity: "10",
      expand: "venue,organizer",
      is_public: "true",
      ordering: "-starts_at",
      page: "2",
      page_size: "10",
      search: "conf",
      status: "published",
    });
  });

  it("drops undefined and null filter values", () => {
    const key = karniKeys.list("events", {
      filters: { status: null, venue: undefined, city: "pune" },
    });
    expect(key[3]).toEqual({ city: "pune" });
  });

  it("sorts keys so param order never fragments the cache", () => {
    const a = karniKeys.list("events", { search: "x", page: 2, filters: { b: "2", a: "1" } });
    const b = karniKeys.list("events", { filters: { a: "1", b: "2" }, page: 2, search: "x" });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    expect(Object.keys(a[3] as Record<string, unknown>)).toEqual(["a", "b", "page", "search"]);
  });

  it("keeps array filters as stringified arrays (repeated query keys)", () => {
    const key = karniKeys.list("events", { filters: { tag: ["a", "b", 3] } });
    expect(key[3]).toEqual({ tag: ["a", "b", "3"] });
  });

  it("lets explicit params win over a filters entry of the same name", () => {
    const key = karniKeys.list("events", { page: 2, filters: { page: 99 } });
    expect(key[3]).toEqual({ page: "2" });
  });

  it("treats empty search/ordering/expand as unset", () => {
    const key = karniKeys.list("events", { search: "", ordering: "", expand: [] });
    expect(key[3]).toEqual({});
  });
});

describe("karniKeys.detail", () => {
  it("has the pinned shape with a stringified id", () => {
    expect(karniKeys.detail("events", 5)).toEqual(["karni", "events", "detail", "5"]);
    expect(karniKeys.detail("events", "5")).toEqual(["karni", "events", "detail", "5"]);
  });

  it("appends normalized params only when present, under the resource prefix", () => {
    const key = karniKeys.detail("events", 5, { expand: ["venue"] });
    expect(key).toEqual(["karni", "events", "detail", "5", { expand: "venue" }]);
    // Both variants stay under the resource invalidation root (D4).
    expect(key.slice(0, 2)).toEqual(karniKeys.resource("events"));
    expect(karniKeys.detail("events", 5, { expand: [] })).toHaveLength(4);
  });
});
