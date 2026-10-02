/**
 * Shared fixtures for the ResourceForm / ResourceSelect / ResourceDetail test
 * suites and stories (owner: resource form builder).
 *
 * Tests mock the schema/hooks modules (they are built concurrently by other
 * builders) and feed them these parsed shapes. Stories go through the real
 * pipeline instead: `demoHandlers` serves a D1-dialect OpenAPI document plus
 * matching CRUD endpoints over msw, so the stories exercise the real
 * createKarniClient → useSchema → component path once those modules land.
 */
import { http, HttpResponse } from "msw";
import type { FieldDef, ResourceSchema } from "../../../schema/types";

function field(
  partial: Partial<FieldDef> & Pick<FieldDef, "name" | "label" | "kind">,
  order: number,
): FieldDef {
  return {
    required: false,
    readOnly: false,
    writeOnly: false,
    nullable: false,
    order,
    ...partial,
  };
}

// ---------------------------------------------------------------------------
// Parsed schema fixtures (what useSchema returns after parsing)
// ---------------------------------------------------------------------------

export const eventFields: readonly FieldDef[] = [
  field({ name: "id", label: "Id", kind: "integer", readOnly: true }, 0),
  field({ name: "title", label: "Title", kind: "string", required: true, maxLength: 200 }, 1),
  field({ name: "description", label: "Description", kind: "text" }, 2),
  field({ name: "starts_at", label: "Starts at", kind: "datetime", required: true }, 3),
  field({ name: "capacity", label: "Capacity", kind: "integer", nullable: true, min: 0 }, 4),
  field({ name: "status", label: "Status", kind: "enum", enumValues: ["draft", "published"] }, 5),
  field({ name: "is_public", label: "Is public", kind: "boolean" }, 6),
  field(
    {
      name: "venue",
      label: "Venue",
      kind: "relation",
      nullable: true,
      relation: { resource: "venues", many: false },
      relationValueType: "integer",
    },
    7,
  ),
  field(
    {
      name: "tags",
      label: "Tags",
      kind: "relation",
      relation: { resource: "tags", many: true },
      relationValueType: "integer",
    },
    8,
  ),
  field({ name: "image", label: "Image", kind: "file", nullable: true }, 9),
  field({ name: "metadata", label: "Metadata", kind: "json", nullable: true }, 10),
  field({ name: "internal_note", label: "Internal note", kind: "string", writeOnly: true }, 11),
  field({ name: "created_at", label: "Created at", kind: "datetime", readOnly: true }, 12),
  field({ name: "mystery", label: "Mystery", kind: "unknown" }, 13),
];

export const eventSchema: ResourceSchema = {
  resource: "events",
  operations: {
    list: {
      path: "/api/events/",
      method: "get",
      queryParams: ["page", "page_size", "ordering", "search", "expand"],
      expandEnum: ["venue", "tags"],
      hasSearch: true,
    },
    detail: {
      path: "/api/events/{id}/",
      method: "get",
      queryParams: ["expand"],
      expandEnum: ["venue", "tags"],
    },
    create: { path: "/api/events/", method: "post", queryParams: [] },
    update: { path: "/api/events/{id}/", method: "patch", queryParams: [] },
    remove: { path: "/api/events/{id}/", method: "delete", queryParams: [] },
  },
  fields: eventFields,
};

export const venueFields: readonly FieldDef[] = [
  field({ name: "id", label: "Id", kind: "integer", readOnly: true }, 0),
  field({ name: "name", label: "Name", kind: "string", required: true, maxLength: 120 }, 1),
  field({ name: "city", label: "City", kind: "string", required: true, maxLength: 120 }, 2),
];

export const venueSchema: ResourceSchema = {
  resource: "venues",
  operations: {
    list: {
      path: "/api/venues/",
      method: "get",
      queryParams: ["page", "page_size", "ordering", "search"],
      hasSearch: true,
    },
    detail: { path: "/api/venues/{id}/", method: "get", queryParams: [] },
  },
  fields: venueFields,
};

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

export interface VenueRecord extends Record<string, unknown> {
  id: number;
  name: string;
  city: string;
}

export const venues: readonly VenueRecord[] = [
  { id: 1, name: "Aurora Hall", city: "Oslo" },
  { id: 2, name: "Basalt Rooms", city: "Reykjavik" },
  { id: 3, name: "Cedar Pavilion", city: "Portland" },
  { id: 4, name: "Delta Loft", city: "Rotterdam" },
  { id: 5, name: "Ember Yard", city: "Lisbon" },
  { id: 6, name: "Fjord Stage", city: "Bergen" },
  { id: 7, name: "Berlin Arena", city: "Berlin" },
  { id: 8, name: "Granite Works", city: "Aberdeen" },
  { id: 9, name: "Harbor House", city: "Hamburg" },
  { id: 10, name: "Iris Garden", city: "Kyoto" },
  { id: 11, name: "Juniper Court", city: "Ljubljana" },
  { id: 12, name: "Kite Field", city: "Wellington" },
];

export const venueById: Readonly<Record<string, VenueRecord>> = Object.fromEntries(
  venues.map((venue) => [String(venue.id), venue]),
);

export const tags: ReadonlyArray<Record<string, unknown>> = [
  { id: 1, name: "music" },
  { id: 2, name: "outdoor" },
  { id: 3, name: "charity" },
];

/** UNEXPANDED detail record, as edit mode receives it (D10). */
export const eventRecord: Record<string, unknown> = {
  id: 1,
  title: "Launch party",
  description: "Celebrating the v1 release.",
  starts_at: "2026-04-01T18:30:00+00:00",
  capacity: 250,
  status: "published",
  is_public: true,
  venue: 7,
  tags: [1, 2],
  image: "https://files.example.com/events/launch.png",
  metadata: { theme: "neon" },
  created_at: "2026-01-05T09:00:00+00:00",
};

// ---------------------------------------------------------------------------
// Story support: a D1-dialect OpenAPI document + msw handlers
// ---------------------------------------------------------------------------

const paginationParams = [
  { name: "page", in: "query", required: false, schema: { type: "integer" } },
  { name: "page_size", in: "query", required: false, schema: { type: "integer" } },
];

function listOperation(
  resource: string,
  componentName: string,
  extraParameters: ReadonlyArray<Record<string, unknown>> = [],
): Record<string, unknown> {
  return {
    operationId: `${resource}_list`,
    "x-karni-resource": resource,
    parameters: [
      ...paginationParams,
      { name: "ordering", in: "query", required: false, schema: { type: "string" } },
      { name: "search", in: "query", required: false, schema: { type: "string" } },
      ...extraParameters,
    ],
    responses: {
      "200": {
        content: {
          "application/json": {
            schema: { $ref: `#/components/schemas/Paginated${componentName}List` },
          },
        },
        description: "",
      },
    },
  };
}

function paginatedComponent(componentName: string): Record<string, unknown> {
  return {
    type: "object",
    required: ["count", "results"],
    properties: {
      count: { type: "integer" },
      next: { type: "string", format: "uri", nullable: true },
      previous: { type: "string", format: "uri", nullable: true },
      results: { type: "array", items: { $ref: `#/components/schemas/${componentName}` } },
    },
  };
}

const venueRelationExtension = { resource: "venues", many: false };
const tagsRelationExtension = { resource: "tags", many: true };

/**
 * Minimal drf-spectacular-shaped document (OAS 3.0.3,
 * COMPONENT_SPLIT_REQUEST=True): split request/response components,
 * x-karni-resource on list ops, x-karni-relation on pk fields and
 * x-karni-auth-mode at the root (api contract B13/B14).
 */
export const demoOpenApiDocument: Record<string, unknown> = {
  openapi: "3.0.3",
  info: { title: "Karni demo API", version: "0.1.0" },
  "x-karni-auth-mode": "jwt",
  paths: {
    "/api/events/": {
      get: listOperation("events", "DemoEvent", [
        {
          name: "expand",
          in: "query",
          required: false,
          schema: { type: "string", enum: ["venue", "tags"] },
        },
      ]),
      post: {
        operationId: "events_create",
        requestBody: {
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/DemoEventRequest" } },
            "multipart/form-data": { schema: { $ref: "#/components/schemas/DemoEventRequest" } },
          },
          required: true,
        },
        responses: {
          "201": {
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DemoEvent" } },
            },
            description: "",
          },
        },
      },
    },
    "/api/events/{id}/": {
      get: {
        operationId: "events_retrieve",
        parameters: [
          { name: "id", in: "path", required: true, schema: { type: "integer" } },
          {
            name: "expand",
            in: "query",
            required: false,
            schema: { type: "string", enum: ["venue", "tags"] },
          },
        ],
        responses: {
          "200": {
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DemoEvent" } },
            },
            description: "",
          },
        },
      },
      patch: {
        operationId: "events_partial_update",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "integer" } }],
        requestBody: {
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/PatchedDemoEventRequest" },
            },
            "multipart/form-data": {
              schema: { $ref: "#/components/schemas/PatchedDemoEventRequest" },
            },
          },
        },
        responses: {
          "200": {
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DemoEvent" } },
            },
            description: "",
          },
        },
      },
      delete: {
        operationId: "events_destroy",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "integer" } }],
        responses: { "204": { description: "" } },
      },
    },
    "/api/venues/": { get: listOperation("venues", "DemoVenue") },
    "/api/venues/{id}/": {
      get: {
        operationId: "venues_retrieve",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "integer" } }],
        responses: {
          "200": {
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DemoVenue" } },
            },
            description: "",
          },
        },
      },
    },
    "/api/tags/": { get: listOperation("tags", "DemoTag") },
    "/api/tags/{id}/": {
      get: {
        operationId: "tags_retrieve",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "integer" } }],
        responses: {
          "200": {
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DemoTag" } },
            },
            description: "",
          },
        },
      },
    },
  },
  components: {
    schemas: {
      StatusEnum: { type: "string", enum: ["draft", "published"] },
      DemoEvent: {
        type: "object",
        required: ["id", "title", "starts_at", "created_at"],
        properties: {
          id: { type: "integer", readOnly: true },
          title: { type: "string", maxLength: 200 },
          description: { type: "string" },
          starts_at: { type: "string", format: "date-time" },
          capacity: { type: "integer", nullable: true, minimum: 0 },
          status: { allOf: [{ $ref: "#/components/schemas/StatusEnum" }] },
          is_public: { type: "boolean" },
          venue: { type: "integer", nullable: true, "x-karni-relation": venueRelationExtension },
          tags: {
            type: "array",
            items: { type: "integer" },
            "x-karni-relation": tagsRelationExtension,
          },
          image: { type: "string", format: "uri", nullable: true, readOnly: true },
          metadata: { type: "object", additionalProperties: {}, nullable: true },
          created_at: { type: "string", format: "date-time", readOnly: true },
        },
      },
      DemoEventRequest: {
        type: "object",
        required: ["title", "starts_at"],
        properties: {
          title: { type: "string", maxLength: 200, minLength: 1 },
          description: { type: "string" },
          starts_at: { type: "string", format: "date-time" },
          capacity: { type: "integer", nullable: true, minimum: 0 },
          status: { allOf: [{ $ref: "#/components/schemas/StatusEnum" }] },
          is_public: { type: "boolean" },
          venue: { type: "integer", nullable: true, "x-karni-relation": venueRelationExtension },
          tags: {
            type: "array",
            items: { type: "integer" },
            "x-karni-relation": tagsRelationExtension,
          },
          image: { type: "string", format: "binary", nullable: true },
          metadata: { type: "object", additionalProperties: {}, nullable: true },
          internal_note: { type: "string", writeOnly: true },
        },
      },
      PatchedDemoEventRequest: {
        type: "object",
        properties: {
          title: { type: "string", maxLength: 200, minLength: 1 },
          description: { type: "string" },
          starts_at: { type: "string", format: "date-time" },
          capacity: { type: "integer", nullable: true, minimum: 0 },
          status: { allOf: [{ $ref: "#/components/schemas/StatusEnum" }] },
          is_public: { type: "boolean" },
          venue: { type: "integer", nullable: true, "x-karni-relation": venueRelationExtension },
          tags: {
            type: "array",
            items: { type: "integer" },
            "x-karni-relation": tagsRelationExtension,
          },
          image: { type: "string", format: "binary", nullable: true },
          metadata: { type: "object", additionalProperties: {}, nullable: true },
          internal_note: { type: "string", writeOnly: true },
        },
      },
      DemoVenue: {
        type: "object",
        required: ["id", "name", "city"],
        properties: {
          id: { type: "integer", readOnly: true },
          name: { type: "string", maxLength: 120 },
          city: { type: "string", maxLength: 120 },
        },
      },
      DemoTag: {
        type: "object",
        required: ["id", "name"],
        properties: {
          id: { type: "integer", readOnly: true },
          name: { type: "string", maxLength: 60 },
        },
      },
      PaginatedDemoEventList: paginatedComponent("DemoEvent"),
      PaginatedDemoVenueList: paginatedComponent("DemoVenue"),
      PaginatedDemoTagList: paginatedComponent("DemoTag"),
    },
  },
};

function paginate(rows: ReadonlyArray<Record<string, unknown>>, request: Request): Response {
  const url = new URL(request.url);
  const search = (url.searchParams.get("search") ?? "").toLowerCase();
  const filtered =
    search === ""
      ? rows
      : rows.filter((row) =>
          Object.values(row).some(
            (value) => typeof value === "string" && value.toLowerCase().includes(search),
          ),
        );
  const pageSize = Number(url.searchParams.get("page_size") ?? "25");
  const page = Number(url.searchParams.get("page") ?? "1");
  const start = (page - 1) * pageSize;
  return HttpResponse.json({
    count: filtered.length,
    next: null,
    previous: null,
    results: filtered.slice(start, start + pageSize),
  });
}

/** msw handlers for stories: schema document + events/venues/tags endpoints. */
export const demoHandlers = [
  http.get("/api/schema/", () => HttpResponse.json(demoOpenApiDocument)),
  http.get("/api/events/", ({ request }) => paginate([eventRecord], request)),
  http.post("/api/events/", async ({ request }) => {
    const contentType = request.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json")
      ? ((await request.json()) as Record<string, unknown>)
      : Object.fromEntries((await request.formData()).entries());
    return HttpResponse.json({ ...eventRecord, ...body, id: 99 }, { status: 201 });
  }),
  http.get("/api/events/:id/", () => HttpResponse.json(eventRecord)),
  http.patch("/api/events/:id/", async ({ request }) => {
    const contentType = request.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json")
      ? ((await request.json()) as Record<string, unknown>)
      : Object.fromEntries((await request.formData()).entries());
    return HttpResponse.json({ ...eventRecord, ...body });
  }),
  http.get("/api/venues/", ({ request }) => paginate(venues, request)),
  http.get("/api/venues/:id/", ({ params }) => {
    const venue = venueById[String(params["id"])];
    return venue === undefined
      ? HttpResponse.json({ detail: "Not found." }, { status: 404 })
      : HttpResponse.json(venue);
  }),
  http.get("/api/tags/", ({ request }) => paginate(tags, request)),
  http.get("/api/tags/:id/", ({ params }) => {
    const tag = tags.find((candidate) => String(candidate["id"]) === String(params["id"]));
    return tag === undefined
      ? HttpResponse.json({ detail: "Not found." }, { status: 404 })
      : HttpResponse.json(tag);
  }),
];
