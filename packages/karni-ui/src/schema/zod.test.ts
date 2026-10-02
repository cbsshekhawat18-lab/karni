/**
 * zodFor suite (contract "Schema client" + D3), driven by the same parsed
 * "events" resource the MSW fixture serves, plus synthetic schemas for the
 * corners the fixture does not hit (numeric enums, uuid relations).
 */
import { describe, expect, it } from "vitest";
import { openApiFixture } from "../../tests/msw/openapi";
import { parseOpenApi } from "./parse";
import type { FieldDef, ResourceSchema } from "./types";
import { zodFor } from "./zod";

const parsed = parseOpenApi(openApiFixture);
const events = parsed.resources["events"] as ResourceSchema;

const validCreate = {
  title: "Launch Party",
  starts_at: "2026-11-05T10:00:00Z",
};

function makeField(overrides: Partial<FieldDef> & Pick<FieldDef, "name" | "kind">): FieldDef {
  return {
    label: overrides.name,
    required: false,
    readOnly: false,
    writeOnly: false,
    nullable: false,
    order: 0,
    ...overrides,
  };
}

function makeSchema(fields: FieldDef[]): ResourceSchema {
  return { resource: "synthetic", operations: {}, fields };
}

describe("zodFor — create mode", () => {
  const schema = zodFor(events, "create");

  it("accepts a minimal valid payload", () => {
    expect(schema.safeParse(validCreate).success).toBe(true);
  });

  it("requires the create request's required fields only", () => {
    const missing = schema.safeParse({ title: "No start" });
    expect(missing.success).toBe(false);
    if (!missing.success) {
      expect(missing.error.issues.map((issue) => issue.path[0])).toContain("starts_at");
    }
    // status/created_at are response-required but NOT create-required (D1).
    expect(schema.safeParse(validCreate).success).toBe(true);
  });

  it("rejects an empty required string", () => {
    const result = schema.safeParse({ ...validCreate, title: "" });
    expect(result.success).toBe(false);
  });

  it("excludes readOnly fields and includes writeOnly fields", () => {
    expect(Object.keys(schema.shape)).not.toContain("id");
    expect(Object.keys(schema.shape)).not.toContain("status");
    expect(Object.keys(schema.shape)).not.toContain("created_at");
    expect(Object.keys(schema.shape)).toContain("internal_note");
  });

  it("enforces maxLength", () => {
    const result = schema.safeParse({ ...validCreate, title: "x".repeat(201) });
    expect(result.success).toBe(false);
  });

  it("coerces number/integer input and enforces min/max", () => {
    const coerced = schema.parse({ ...validCreate, capacity: "42" });
    expect(coerced["capacity"]).toBe(42);
    expect(schema.safeParse({ ...validCreate, capacity: -1 }).success).toBe(false);
    expect(schema.safeParse({ ...validCreate, capacity: 10001 }).success).toBe(false);
  });

  it("lets nullable fields be null (capacity, category)", () => {
    expect(schema.safeParse({ ...validCreate, capacity: null }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, category: null }).success).toBe(true);
  });

  it("builds z.enum from string members; '' and null are never members", () => {
    expect(schema.safeParse({ ...validCreate, category: "meetup" }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, category: "bogus" }).success).toBe(false);
    expect(schema.safeParse({ ...validCreate, priority: "" }).success).toBe(false);
    expect(schema.safeParse({ ...validCreate, priority: "high" }).success).toBe(true);
    // priority is not nullable (BlankEnum, not NullEnum)
    expect(schema.safeParse({ ...validCreate, priority: null }).success).toBe(false);
  });

  it("derives relation value schemas from the emitted pk type", () => {
    expect(schema.safeParse({ ...validCreate, organizer: 2 }).success).toBe(true);
    const coerced = schema.parse({ ...validCreate, organizer: "2" });
    expect(coerced["organizer"]).toBe(2);
    expect(schema.safeParse({ ...validCreate, organizer: null }).success).toBe(true);
    const many = schema.parse({ ...validCreate, tags: ["1", 2] });
    expect(many["tags"]).toEqual([1, 2]);
    expect(schema.safeParse({ ...validCreate, tags: "1" }).success).toBe(false);
  });

  it("validates email/url string formats", () => {
    expect(schema.safeParse({ ...validCreate, contact_email: "nope" }).success).toBe(false);
    expect(schema.safeParse({ ...validCreate, contact_email: "a@b.co" }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, website: "not a url" }).success).toBe(false);
    expect(schema.safeParse({ ...validCreate, website: "https://karni.dev" }).success).toBe(true);
  });

  it("accepts File or string for file fields", () => {
    const file = new File(["poster"], "poster.png", { type: "image/png" });
    expect(schema.safeParse({ ...validCreate, poster: file }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, poster: "https://x/poster.png" }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, poster: 7 }).success).toBe(false);
  });

  it("passes anything through json fields", () => {
    expect(schema.safeParse({ ...validCreate, metadata: { a: [1, 2] } }).success).toBe(true);
    expect(schema.safeParse({ ...validCreate, metadata: "raw" }).success).toBe(true);
  });

  it("transforms datetime-local input to ISO-8601 with offset on submit (D3)", () => {
    const out = schema.parse({ ...validCreate, starts_at: "2026-05-01T10:30" });
    const submitted = out["starts_at"];
    expect(typeof submitted).toBe("string");
    expect(submitted).toMatch(/(Z|[+-]\d{2}:\d{2})$/);
    expect(new Date(String(submitted)).getTime()).toBe(new Date("2026-05-01T10:30").getTime());
    // Already-zoned values pass through untouched.
    const zoned = schema.parse({ ...validCreate, starts_at: "2026-05-01T10:30:00+05:30" });
    expect(zoned["starts_at"]).toBe("2026-05-01T10:30:00+05:30");
  });
});

describe("zodFor — update mode", () => {
  const schema = zodFor(events, "update");

  it("makes every field optional", () => {
    expect(schema.safeParse({}).success).toBe(true);
  });

  it("nests .nullable() inside .optional() for nullable fields (D3)", () => {
    expect(schema.safeParse({ capacity: null }).success).toBe(true);
    expect(schema.safeParse({ capacity: undefined }).success).toBe(true);
    // Non-nullable fields still reject null even though they are optional.
    expect(schema.safeParse({ title: null }).success).toBe(false);
  });

  it("still rejects blank values for required-at-create strings when provided", () => {
    expect(schema.safeParse({ title: "" }).success).toBe(false);
    expect(schema.safeParse({ title: "Renamed" }).success).toBe(true);
  });
});

describe("zodFor — synthetic corners", () => {
  it("builds a union of literals for non-string enums", () => {
    const schema = zodFor(
      makeSchema([makeField({ name: "level", kind: "enum", enumValues: [1, 2, 3] })]),
      "create",
    );
    expect(schema.safeParse({ level: 2 }).success).toBe(true);
    expect(schema.safeParse({ level: 4 }).success).toBe(false);
  });

  it("uses uuid validation for uuid-pk relations", () => {
    const schema = zodFor(
      makeSchema([
        makeField({
          name: "owner",
          kind: "relation",
          relation: { resource: "owners", many: false },
          relationValueType: "uuid",
          required: true,
        }),
      ]),
      "create",
    );
    expect(schema.safeParse({ owner: "not-a-uuid" }).success).toBe(false);
    expect(schema.safeParse({ owner: "7f8d9c7e-3f6a-4b1e-9f3d-2a1b3c4d5e6f" }).success).toBe(true);
  });

  it("skips nothing for unknown kinds — they validate as unknown", () => {
    const schema = zodFor(makeSchema([makeField({ name: "weird", kind: "unknown" })]), "create");
    expect(schema.safeParse({ weird: Symbol("anything") }).success).toBe(true);
    expect(schema.safeParse({}).success).toBe(true);
  });
});
