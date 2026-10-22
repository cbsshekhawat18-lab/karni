import { describe, expect, it } from "vitest";
import { resourceNames } from "../resource-names";
import { mapServerErrors } from "./server-errors";

const FIELDS = new Set(["title", "capacity", "metadata", "address.city", "items.1.name"]);
const isField = (path: string): boolean => FIELDS.has(path);

describe("mapServerErrors: every DRF error shape", () => {
  it("field lists and plain strings land on their field", () => {
    expect(
      mapServerErrors({ title: ["Required.", "Too short."], capacity: "Too big." }, { isField }),
    ).toEqual({ fields: { title: "Required. Too short.", capacity: "Too big." }, root: [] });
  });

  it("a nested serializer lands on the deepest rendered path, else on its parent field", () => {
    expect(mapServerErrors({ address: { city: ["Required."] } }, { isField }).fields).toEqual({
      "address.city": "Required.",
    });
    expect(mapServerErrors({ metadata: { theme: ["Unknown."] } }, { isField }).fields).toEqual({
      metadata: "Theme: Unknown.",
    });
  });

  it("list serializer errors are walked by position", () => {
    expect(mapServerErrors({ items: [{}, { name: ["Required."] }] }, { isField }).fields).toEqual({
      "items.1.name": "Required.",
    });
  });

  it("errors keyed by position on a field are named in its message", () => {
    expect(
      mapServerErrors({ capacity: { "0": ["Bad."] } }, { isField: (path) => path === "capacity" })
        .fields,
    ).toEqual({ capacity: "Item 1: Bad." });
  });

  it("non_field_errors, detail, __all__, a bare list and a bare string are form-level", () => {
    expect(mapServerErrors({ non_field_errors: ["Closed."] }, { isField }).root).toEqual([
      "Closed.",
    ]);
    expect(mapServerErrors({ detail: "Frozen.", code: "frozen" }, { isField }).root).toEqual([
      "Frozen.",
    ]);
    expect(mapServerErrors({ __all__: ["Overlap."] }, { isField }).root).toEqual(["Overlap."]);
    expect(mapServerErrors(["One.", "Two."], { isField }).root).toEqual(["One.", "Two."]);
    expect(mapServerErrors("Plain text.", { isField }).root).toEqual(["Plain text."]);
  });

  it("keys the form does not render become form-level messages that name them", () => {
    expect(mapServerErrors({ secret_code: ["Admins only."] }, { isField }).root).toEqual([
      "Secret code: Admins only.",
    ]);
    expect(
      mapServerErrors(
        { venue: ["Gone."] },
        { isField, labelOf: (path) => (path === "venue" ? "Location" : path) },
      ).root,
    ).toEqual(["Location: Gone."]);
  });

  it("DRF's full-details shape ({message, code}) reads as its message", () => {
    expect(
      mapServerErrors({ title: [{ message: "Required.", code: "required" }] }, { isField }).fields,
    ).toEqual({ title: "Required." });
  });

  it("an HTML error page is never shown", () => {
    expect(mapServerErrors("<!doctype html><h1>Bad Request</h1>", { isField })).toEqual({
      fields: {},
      root: [],
    });
  });
});

describe("resourceNames", () => {
  it("derives the singular from the router prefix", () => {
    expect(resourceNames("events")).toEqual({ singular: "event", plural: "events" });
    expect(resourceNames("loose-slots")).toEqual({ singular: "loose slot", plural: "loose slots" });
    expect(resourceNames("categories").singular).toBe("category");
    expect(resourceNames("addresses").singular).toBe("address");
    expect(resourceNames("boxes").singular).toBe("box");
  });

  it("takes the project's words when the rules get it wrong", () => {
    expect(resourceNames("people", { singular: "person" })).toEqual({
      singular: "person",
      plural: "people",
    });
  });
});
