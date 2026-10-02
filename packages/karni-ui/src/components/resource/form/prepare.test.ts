import { describe, expect, it } from "vitest";
import { eventFields } from "./fixtures";
import {
  buildFormValues,
  humanizeValue,
  isDirtyEntry,
  prepareSubmit,
  toDatetimeLocal,
  toIsoWithOffset,
} from "./prepare";

// Mirrors ResourceForm's field derivation: writable, renderable kinds only.
const writableFields = eventFields.filter(
  (field) => !field.readOnly && field.kind !== "unknown" && field.kind !== "array",
);

describe("humanizeValue", () => {
  it("spaces and capitalizes identifiers", () => {
    expect(humanizeValue("published_on")).toBe("Published on");
    expect(humanizeValue("draft-mode")).toBe("Draft mode");
    expect(humanizeValue("draft")).toBe("Draft");
  });
});

describe("datetime helpers", () => {
  it("toIsoWithOffset emits ISO-8601 with an explicit offset for local values", () => {
    const result = toIsoWithOffset("2026-05-01T18:30");
    expect(result).toMatch(/^2026-05-01T18:30:00[+-]\d{2}:\d{2}$/);
    // Round-trips to the same instant the Date constructor produces.
    expect(new Date(result).getTime()).toBe(new Date("2026-05-01T18:30").getTime());
  });

  it("toIsoWithOffset passes zoned values through untouched", () => {
    expect(toIsoWithOffset("2026-05-01T18:30:00Z")).toBe("2026-05-01T18:30:00Z");
    expect(toIsoWithOffset("2026-05-01T18:30:00+05:30")).toBe("2026-05-01T18:30:00+05:30");
  });

  it("toDatetimeLocal and toIsoWithOffset round-trip an instant", () => {
    const iso = "2026-04-01T18:30:00+00:00";
    const local = toDatetimeLocal(iso);
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(new Date(toIsoWithOffset(local)).getTime()).toBe(new Date(iso).getTime());
  });

  it("leaves unparseable values alone", () => {
    expect(toDatetimeLocal("not-a-date")).toBe("not-a-date");
    expect(toIsoWithOffset("not-a-date")).toBe("not-a-date");
  });
});

describe("isDirtyEntry (D3 top-level granularity)", () => {
  it("is true when any leaf of the subtree is dirty", () => {
    expect(isDirtyEntry(true)).toBe(true);
    expect(isDirtyEntry([false, false, true])).toBe(true);
    expect(isDirtyEntry({ nested: { deep: true } })).toBe(true);
  });

  it("is false for clean subtrees", () => {
    expect(isDirtyEntry(undefined)).toBe(false);
    expect(isDirtyEntry(false)).toBe(false);
    expect(isDirtyEntry([false, false])).toBe(false);
    expect(isDirtyEntry({ nested: { deep: false } })).toBe(false);
  });
});

describe("buildFormValues", () => {
  it("gives every field a controlled-input-safe initial value", () => {
    const values = buildFormValues({ fields: writableFields, item: undefined });
    expect(values["title"]).toBe("");
    expect(values["capacity"]).toBe("");
    expect(values["is_public"]).toBe(false);
    expect(values["status"]).toBeNull();
    expect(values["venue"]).toBeNull();
    expect(values["tags"]).toEqual([]);
    expect(values["image"]).toBeNull();
    expect(values["metadata"]).toBe("");
  });

  it("prefers item values over defaultValues and converts per kind", () => {
    const values = buildFormValues({
      fields: writableFields,
      item: {
        title: "Launch party",
        starts_at: "2026-04-01T18:30:00+00:00",
        capacity: 250,
        venue: 7,
        tags: [1, 2],
        metadata: { theme: "neon" },
      },
      defaultValues: { title: "ignored", slug: "kept-for-extra-fields" },
    });
    expect(values["title"]).toBe("Launch party");
    expect(values["starts_at"]).toBe(toDatetimeLocal("2026-04-01T18:30:00+00:00"));
    expect(values["capacity"]).toBe(250);
    expect(values["venue"]).toBe(7);
    expect(values["tags"]).toEqual([1, 2]);
    expect(values["metadata"]).toBe(JSON.stringify({ theme: "neon" }, null, 2));
    // Unmatched defaultValues keys seed extraFields.
    expect(values["slug"]).toBe("kept-for-extra-fields");
  });

  it("unwraps accidentally expanded relation objects to their pk", () => {
    const values = buildFormValues({
      fields: writableFields,
      item: { venue: { id: 7, name: "Berlin Arena" }, tags: [{ id: 1 }, { id: 2 }] },
    });
    expect(values["venue"]).toBe(7);
    expect(values["tags"]).toEqual([1, 2]);
  });
});

describe("prepareSubmit (D3 pipeline)", () => {
  it("create mode: coerces per kind and omits untouched non-nullable optionals", () => {
    const raw = buildFormValues({ fields: writableFields, item: undefined });
    raw["title"] = "Spring gala";
    raw["starts_at"] = "2026-05-01T18:30";
    raw["capacity"] = "40";
    raw["status"] = "published";
    raw["is_public"] = true;
    raw["venue"] = 7;
    raw["tags"] = [1, 2];
    raw["metadata"] = '{"theme": "neon"}';
    raw["internal_note"] = "secret";

    const { values, jsonErrors } = prepareSubmit({ fields: writableFields, raw, mode: "create" });
    expect(jsonErrors).toEqual([]);
    expect(values).toEqual({
      title: "Spring gala",
      description: "",
      starts_at: toIsoWithOffset("2026-05-01T18:30"),
      capacity: 40,
      status: "published",
      is_public: true,
      venue: 7,
      tags: [1, 2],
      image: null,
      metadata: { theme: "neon" },
      internal_note: "secret",
    });
  });

  it("update mode: sends only fields whose dirty subtree is truthy", () => {
    const raw = buildFormValues({ fields: writableFields, item: { title: "Old", capacity: 10 } });
    raw["title"] = "New";
    const { values } = prepareSubmit({
      fields: writableFields,
      raw,
      mode: "update",
      dirtyFields: { title: true },
    });
    expect(values).toEqual({ title: "New" });
  });

  it("update mode: a dirty leaf inside an array sends the whole field value", () => {
    const raw = buildFormValues({ fields: writableFields, item: { tags: [1, 2] } });
    raw["tags"] = [1, 3];
    const { values } = prepareSubmit({
      fields: writableFields,
      raw,
      mode: "update",
      dirtyFields: { tags: [false, true] },
    });
    expect(values).toEqual({ tags: [1, 3] });
  });

  it("D3 null-clearing: emptied nullable fields become null, many relations []", () => {
    const raw = buildFormValues({
      fields: writableFields,
      item: { capacity: 10, venue: 7, tags: [1], image: "https://x/img.png", metadata: { a: 1 } },
    });
    raw["capacity"] = "";
    raw["venue"] = null;
    raw["tags"] = null;
    raw["image"] = null;
    raw["metadata"] = "";
    const { values } = prepareSubmit({
      fields: writableFields,
      raw,
      mode: "update",
      dirtyFields: { capacity: true, venue: true, tags: true, image: true, metadata: true },
    });
    expect(values).toEqual({ capacity: null, venue: null, tags: [], image: null, metadata: null });
  });

  it("emptied non-nullable fields are omitted, not nulled", () => {
    const raw = buildFormValues({ fields: writableFields, item: { status: "draft" } });
    raw["status"] = null;
    const { values } = prepareSubmit({
      fields: writableFields,
      raw,
      mode: "update",
      dirtyFields: { status: true },
    });
    expect(values).toEqual({});
  });

  it("file fields: unchanged URL strings are omitted, File values pass through (D2)", () => {
    const file = new File(["png-bytes"], "cover.png", { type: "image/png" });
    const raw = buildFormValues({ fields: writableFields, item: {} });
    raw["image"] = "https://files.example.com/old.png";
    raw["title"] = "With file";
    let result = prepareSubmit({ fields: writableFields, raw, mode: "create" });
    expect("image" in result.values).toBe(false);

    raw["image"] = file;
    result = prepareSubmit({ fields: writableFields, raw, mode: "create" });
    expect(result.values["image"]).toBe(file);
  });

  it("invalid JSON blocks the submit with a field error", () => {
    const raw = buildFormValues({ fields: writableFields, item: undefined });
    raw["title"] = "x";
    raw["metadata"] = "{oops";
    const { jsonErrors } = prepareSubmit({ fields: writableFields, raw, mode: "create" });
    expect(jsonErrors).toEqual([{ name: "metadata", message: "Enter valid JSON." }]);
  });

  it("keys without a schema field (extraFields) pass through, dirty-gated on update", () => {
    const raw = { slug: "my-slug", title: "T" };
    const create = prepareSubmit({ fields: writableFields, raw, mode: "create" });
    expect(create.values["slug"]).toBe("my-slug");

    const update = prepareSubmit({
      fields: writableFields,
      raw,
      mode: "update",
      dirtyFields: { title: true },
    });
    expect("slug" in update.values).toBe(false);
  });
});
