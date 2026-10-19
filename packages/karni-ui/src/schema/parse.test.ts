/**
 * Parsing suite (contract "Schema client" + D1 + D9).
 *
 * Runs against BOTH schema documents:
 * - the handwritten MSW fixture (tests/msw/openapi.ts) — always,
 * - the Python side's generated testapp snapshot (tests/fixtures/
 *   schema.testapp.json) — when present (D9), skipped with a pointer when not.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { openApiFixture, openApiFixtureWithAuthMode } from "../../tests/msw/openapi";
import { parseOpenApi } from "./parse";
import type { FieldDef, ResourceSchema } from "./types";

function fieldOf(schema: ResourceSchema, name: string): FieldDef {
  const field = schema.fields.find((candidate) => candidate.name === name);
  expect(field, `field "${name}" should exist on ${schema.resource}`).toBeDefined();
  return field as FieldDef;
}

describe("parseOpenApi — handwritten fixture", () => {
  const parsed = parseOpenApi(openApiFixture);
  const events = parsed.resources["events"];

  it("registers every x-karni-resource and the root auth mode", () => {
    expect(Object.keys(parsed.resources).sort()).toEqual(["events", "tags", "users", "venues"]);
    expect(parsed.authMode).toBe("jwt");
  });

  it("parses the session variant's auth mode", () => {
    expect(parseOpenApi(openApiFixtureWithAuthMode("session")).authMode).toBe("session");
  });

  it("derives the five operations with their paths", () => {
    expect(events).toBeDefined();
    if (events === undefined) return;
    expect(events.operations.list?.path).toBe("/api/events/");
    expect(events.operations.create?.method).toBe("post");
    expect(events.operations.detail?.path).toBe("/api/events/{id}/");
    expect(events.operations.update?.method).toBe("patch");
    expect(events.operations.remove?.method).toBe("delete");
  });

  it("records declared list query params, the expand enum, and hasSearch", () => {
    const list = events?.operations.list;
    expect(list).toBeDefined();
    if (list === undefined) return;
    expect([...list.queryParams].sort()).toEqual([
      "category",
      "expand",
      "is_public",
      "ordering",
      "organizer",
      "page",
      "page_size",
      "search",
      "status",
      "venue",
    ]);
    expect(list.expandEnum).toEqual(["organizer", "venue", "tags"]);
    expect(list.hasSearch).toBe(true);
  });

  it("takes required from the CREATE request body only (D1)", () => {
    if (events === undefined) return;
    // The response component's required array lists id/status/created_at too;
    // none of them may leak into `required`.
    const required = events.fields.filter((field) => field.required).map((field) => field.name);
    expect(required.sort()).toEqual(["starts_at", "title"]);
  });

  it("maps scalar kinds, maxLength and min/max", () => {
    if (events === undefined) return;
    const title = fieldOf(events, "title");
    expect(title.kind).toBe("string");
    expect(title.maxLength).toBe(200);
    expect(title.label).toBe("Title");

    expect(fieldOf(events, "description").kind).toBe("text"); // no maxLength → TextField
    expect(fieldOf(events, "starts_at").kind).toBe("datetime");
    expect(fieldOf(events, "is_public")).toMatchObject({ kind: "boolean", required: false });

    const capacity = fieldOf(events, "capacity");
    expect(capacity).toMatchObject({ kind: "integer", nullable: true, min: 0, max: 10000 });

    expect(fieldOf(events, "contact_email").format).toBe("email");
    expect(fieldOf(events, "metadata").kind).toBe("json"); // `{}` any-schema
  });

  it("resolves allOf-$ref enums with siblings (status → read-only enum)", () => {
    if (events === undefined) return;
    const status = fieldOf(events, "status");
    expect(status.kind).toBe("enum");
    expect(status.enumValues).toEqual(["draft", "published"]);
    expect(status.readOnly).toBe(true);
    expect(status.writeOnly).toBe(false);
  });

  it("maps oneOf [XEnum, NullEnum] → nullable enum without null member", () => {
    if (events === undefined) return;
    const category = fieldOf(events, "category");
    expect(category.kind).toBe("enum");
    expect(category.nullable).toBe(true);
    expect(category.enumValues).toEqual(["conference", "meetup", "workshop"]);
  });

  it('maps oneOf [XEnum, BlankEnum] → enum excluding "" (D1)', () => {
    if (events === undefined) return;
    const priority = fieldOf(events, "priority");
    expect(priority.kind).toBe("enum");
    expect(priority.enumValues).toEqual(["low", "high"]);
    expect(priority.nullable).toBe(false);
  });

  it("derives relations from x-karni-relation with their pk value type", () => {
    if (events === undefined) return;
    const organizer = fieldOf(events, "organizer");
    expect(organizer.kind).toBe("relation");
    expect(organizer.relation).toEqual({ resource: "users", many: false });
    expect(organizer.relationValueType).toBe("integer");
    expect(organizer.nullable).toBe(true);

    expect(fieldOf(events, "venue").relation).toEqual({ resource: "venues", many: false });

    const tags = fieldOf(events, "tags");
    expect(tags.kind).toBe("relation");
    expect(tags.relation).toEqual({ resource: "tags", many: true });
    expect(tags.relationValueType).toBe("integer");
  });

  it("marks kind file from the request side's format: binary (D1)", () => {
    if (events === undefined) return;
    const poster = fieldOf(events, "poster");
    expect(poster.kind).toBe("file"); // response side is format: uri (display URL)
    expect(poster.nullable).toBe(true);
    expect(poster.readOnly).toBe(false);
  });

  it("flags readOnly for flagged-or-response-only, writeOnly for request-only", () => {
    if (events === undefined) return;
    expect(fieldOf(events, "id").readOnly).toBe(true); // flagged
    expect(fieldOf(events, "created_at").readOnly).toBe(true); // flagged + response-only
    const note = fieldOf(events, "internal_note");
    expect(note.writeOnly).toBe(true); // flagged + request-only
    expect(note.readOnly).toBe(false);
    expect(note.maxLength).toBe(500);
  });

  it("keeps response declaration order and appends request-only fields", () => {
    if (events === undefined) return;
    const names = events.fields.map((field) => field.name);
    expect(names.indexOf("id")).toBe(0);
    expect(names.indexOf("title")).toBeLessThan(names.indexOf("status"));
    expect(names.indexOf("internal_note")).toBe(names.length - 1); // request-only → appended
    expect(events.fields.map((field) => field.order)).toEqual(
      events.fields.map((_, index) => index),
    );
  });

  it("treats resources without a create op as fully read-only (D1)", () => {
    const users = parsed.resources["users"];
    expect(users).toBeDefined();
    if (users === undefined) return;
    expect(users.operations.create).toBeUndefined();
    expect(users.fields.length).toBeGreaterThan(0);
    expect(users.fields.every((field) => field.readOnly)).toBe(true);
    expect(users.fields.every((field) => !field.required)).toBe(true);
  });
});

describe("parseOpenApi — resilience", () => {
  it("returns an empty registry for malformed documents", () => {
    expect(parseOpenApi(null).resources).toEqual({});
    expect(parseOpenApi("nonsense").resources).toEqual({});
    expect(parseOpenApi({ paths: 7 }).resources).toEqual({});
    expect(parseOpenApi({ "x-karni-auth-mode": "carrier-pigeon" }).authMode).toBeUndefined();
  });

  it("lands unsupported constructs as kind unknown instead of crashing", () => {
    const doc = {
      openapi: "3.0.3",
      paths: {
        "/api/widgets/": {
          get: {
            "x-karni-resource": "widgets",
            responses: {
              "200": {
                content: {
                  "application/json": {
                    schema: {
                      type: "object",
                      properties: {
                        results: {
                          type: "array",
                          items: {
                            type: "object",
                            properties: {
                              id: { type: "integer", readOnly: true },
                              shape: { oneOf: [{ type: "object" }, { type: "string" }] },
                              warp: { type: "wormhole" },
                              dangling: { $ref: "#/components/schemas/Missing" },
                            },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      },
    };
    const widgets = parseOpenApi(doc).resources["widgets"];
    expect(widgets).toBeDefined();
    if (widgets === undefined) return;
    expect(fieldOf(widgets, "shape").kind).toBe("unknown");
    expect(fieldOf(widgets, "warp").kind).toBe("unknown");
    // A dangling $ref resolves to {} — indistinguishable from drf-spectacular's
    // JSONField "any" schema, so it lands as json (still never a crash).
    expect(fieldOf(widgets, "dangling").kind).toBe("json");
    expect(fieldOf(widgets, "id").kind).toBe("integer");
  });

  it("degrades gracefully without x-karni-relation (plain fields)", () => {
    const doc = {
      openapi: "3.0.3",
      paths: {
        "/api/posts/": {
          get: {
            "x-karni-resource": "posts",
            responses: {
              "200": {
                content: {
                  "application/json": {
                    schema: {
                      type: "object",
                      properties: {
                        results: {
                          type: "array",
                          items: {
                            type: "object",
                            properties: { author: { type: "integer", nullable: true } },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      },
    };
    const posts = parseOpenApi(doc).resources["posts"];
    expect(posts).toBeDefined();
    if (posts === undefined) return;
    const author = fieldOf(posts, "author");
    expect(author.kind).toBe("integer"); // no extension → plain field
    expect(author.relation).toBeUndefined();
  });
});

// D9 snapshot guard

const SNAPSHOT_PATH = join(process.cwd(), "tests", "fixtures", "schema.testapp.json");
const snapshotPresent = existsSync(SNAPSHOT_PATH);

describe("parseOpenApi — generated testapp snapshot (D9)", () => {
  it.skipIf(!snapshotPresent)(
    "parses the testapp Event resource with the pinned field facts " +
      "(schema.testapp.json absent? copy it from packages/karni tests/api/fixtures — " +
      "see tests/fixtures/README.md)",
    () => {
      const parsed = parseOpenApi(JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8")));

      const event = Object.values(parsed.resources).find((resource) =>
        resource.fields.some((field) => field.name === "internal_note"),
      );
      expect(
        event,
        `expected a resource with an internal_note field (testapp Event); ` +
          `found resources: ${Object.keys(parsed.resources).join(", ")}`,
      ).toBeDefined();
      if (event === undefined) return;

      const status = fieldOf(event, "status");
      expect(status.kind).toBe("enum");
      expect(status.readOnly).toBe(true); // read_only via APIMeta
      expect(status.enumValues).toBeDefined();
      expect(status.enumValues?.length).toBeGreaterThan(0);
      expect(status.default).toBeUndefined(); // read-only: nothing to prefill

      const isPublic = fieldOf(event, "is_public");
      expect(isPublic.default).toBe(true); // the model default, for create forms

      const capacity = fieldOf(event, "capacity");
      expect(capacity.kind).toBe("integer");
      expect(capacity.nullable).toBe(true);

      const organizer = fieldOf(event, "organizer");
      expect(organizer.kind).toBe("relation");
      expect(organizer.relation?.many).toBe(false);
      expect(organizer.relationValueType).toBe("uuid"); // testapp pks are UUIDs

      const venue = fieldOf(event, "venue");
      expect(venue.kind).toBe("relation");
      expect(venue.relation?.many).toBe(false);

      // Tag has no viewset in the testapp, so the backend omits
      // x-karni-relation (B13: unrouted target) — tags must degrade to a
      // plain array field, never crash or guess.
      const tags = fieldOf(event, "tags");
      expect(tags.kind).toBe("array");
      expect(tags.relation).toBeUndefined();

      const note = fieldOf(event, "internal_note");
      expect(note.writeOnly).toBe(true);
      expect(note.readOnly).toBe(false);

      expect(fieldOf(event, "title").required).toBe(true);
      expect(fieldOf(event, "id").readOnly).toBe(true);
    },
  );
});

describe("parseOpenApi — import and export operations (karni.transfer)", () => {
  const doc = {
    paths: {
      "/api/things/": {
        get: { "x-karni-resource": "things", responses: {} },
        post: { responses: {} },
      },
      "/api/things/export/": {
        get: { parameters: [{ in: "query", name: "format" }], responses: {} },
      },
      "/api/things/import/": { post: { responses: {} } },
      "/api/plain/": { get: { "x-karni-resource": "plain", responses: {} } },
    },
  };
  const parsed = parseOpenApi(doc);

  it("records the export and import operations under the list path", () => {
    const things = parsed.resources["things"];
    expect(things?.operations.export?.path).toBe("/api/things/export/");
    expect(things?.operations.export?.queryParams).toEqual(["format"]);
    expect(things?.operations.import?.path).toBe("/api/things/import/");
    expect(things?.operations.import?.method).toBe("post");
  });

  it("leaves them undefined for a resource without them", () => {
    expect(parsed.resources["plain"]?.operations.export).toBeUndefined();
    expect(parsed.resources["plain"]?.operations.import).toBeUndefined();
  });
});

describe("parseOpenApi — enum choice labels", () => {
  function withStatusDescription(description: string) {
    const doc = structuredClone(openApiFixture) as typeof openApiFixture;
    const schemas = (doc as unknown as { components: { schemas: Record<string, unknown> } })
      .components.schemas;
    schemas["StatusEnum"] = { ...(schemas["StatusEnum"] as object), description };
    return parseOpenApi(doc);
  }

  it("turns drf-spectacular's choice list into labels and drops it from the help text", () => {
    const parsed = withStatusDescription("* `draft` - Draft\n* `published` - Published");
    const status = fieldOf(parsed.resources["events"] as ResourceSchema, "status");
    expect(status.enumLabels).toEqual({ draft: "Draft", published: "Published" });
    expect(status.description).toBeUndefined();
  });

  it("keeps the field's own help text next to the choice list", () => {
    const parsed = withStatusDescription(
      "Visibility of the event.\n\n* `draft` - Draft\n* `published` - Published",
    );
    const status = fieldOf(parsed.resources["events"] as ResourceSchema, "status");
    expect(status.enumLabels).toEqual({ draft: "Draft", published: "Published" });
    expect(status.description).toBe("Visibility of the event.");
  });
});
