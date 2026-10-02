/**
 * Self-contained backend simulation for ResourceTable's integration test and
 * stories: a drf-spectacular-shaped OpenAPI document (OAS 3.0.3, split
 * request/response components, x-karni-* extensions) plus msw handlers for
 * /api/schema/ and /api/events/ with pagination, search, ordering, filters,
 * expand and the DRF "Invalid page." 404.
 *
 * Test/story support only — never imported by shipped component code.
 */
import { http, HttpResponse, type RequestHandler } from "msw";

export interface DemoEvent {
  // BaseModel audit fields lead the payload, as on a real Karni backend.
  id: number;
  created_at: string;
  updated_at: string;
  created_by: number | null;
  updated_by: number | null;
  title: string;
  starts_at: string;
  capacity: number | null;
  status: "DRAFT" | "PUBLISHED";
  is_public: boolean;
  organizer: number | null;
  venue: number | null;
  tags: number[];
}

export const DEMO_EVENT_COUNT = 57;

const ORGANIZERS: Record<number, { id: number; name: string; email: string }> = {
  1: { id: 1, name: "Ada Lovelace", email: "ada@example.com" },
};
const VENUES: Record<number, { id: number; name: string }> = {
  1: { id: 1, name: "Main Hall" },
  2: { id: 2, name: "Garden Stage" },
};

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** Titles run opposite to ids so title-ascending differs from the default order. */
export function makeDemoEvents(count = DEMO_EVENT_COUNT): DemoEvent[] {
  return Array.from({ length: count }, (_, index) => {
    const id = index + 1;
    const created = new Date(Date.UTC(2025, 11, 1, 9, 0, id)).toISOString();
    return {
      id,
      created_at: created,
      updated_at: created,
      created_by: 1,
      updated_by: null,
      title: `Event ${pad2(count + 1 - id)}`,
      starts_at: new Date(Date.UTC(2026, 0, 1 + id, 18, 0, 0)).toISOString(),
      capacity: id % 5 === 0 ? null : id * 10,
      status: id % 3 === 0 ? "PUBLISHED" : "DRAFT",
      is_public: id % 2 === 0,
      organizer: id % 2 === 1 ? 1 : null,
      venue: id % 2 === 1 ? 1 : 2,
      tags: id % 4 === 0 ? [1] : [],
    };
  });
}

// --- OpenAPI document (drf-spectacular dialect, COMPONENT_SPLIT_REQUEST) -----

const relationExt = (resource: string, many: boolean): Record<string, unknown> => ({
  "x-karni-relation": { resource, many },
});

export const eventsOpenApi: Record<string, unknown> = {
  openapi: "3.0.3",
  info: { title: "Karni demo API", version: "0.1.0" },
  "x-karni-auth-mode": "jwt",
  paths: {
    "/api/events/": {
      get: {
        operationId: "events_list",
        "x-karni-resource": "events",
        parameters: [
          {
            name: "expand",
            in: "query",
            schema: {
              type: "array",
              items: { type: "string", enum: ["organizer", "venue", "tags"] },
            },
          },
          // Declared like any BaseModel filter; derived filters must skip it.
          { name: "created_by", in: "query", schema: { type: "integer" } },
          { name: "is_public", in: "query", schema: { type: "boolean" } },
          { name: "ordering", in: "query", schema: { type: "string" } },
          { name: "page", in: "query", schema: { type: "integer" } },
          { name: "page_size", in: "query", schema: { type: "integer" } },
          { name: "search", in: "query", schema: { type: "string" } },
          { name: "status", in: "query", schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/PaginatedEventList" },
              },
            },
          },
        },
      },
      post: {
        operationId: "events_create",
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/EventRequest" } },
          },
        },
        responses: {
          "201": {
            description: "",
            content: { "application/json": { schema: { $ref: "#/components/schemas/Event" } } },
          },
        },
      },
    },
    "/api/events/{id}/": {
      get: {
        operationId: "events_retrieve",
        responses: {
          "200": {
            description: "",
            content: { "application/json": { schema: { $ref: "#/components/schemas/Event" } } },
          },
        },
      },
      patch: {
        operationId: "events_partial_update",
        requestBody: {
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/PatchedEventRequest" },
            },
          },
        },
        responses: {
          "200": {
            description: "",
            content: { "application/json": { schema: { $ref: "#/components/schemas/Event" } } },
          },
        },
      },
      delete: {
        operationId: "events_destroy",
        responses: { "204": { description: "" } },
      },
    },
  },
  components: {
    schemas: {
      StatusEnum: { type: "string", enum: ["DRAFT", "PUBLISHED"] },
      Event: {
        type: "object",
        properties: {
          // BaseModel audit fields come first, exactly as the backend emits them.
          id: { type: "integer", readOnly: true },
          created_at: { type: "string", format: "date-time", readOnly: true },
          updated_at: { type: "string", format: "date-time", readOnly: true },
          created_by: {
            type: "integer",
            nullable: true,
            readOnly: true,
            ...relationExt("users", false),
          },
          updated_by: {
            type: "integer",
            nullable: true,
            readOnly: true,
            ...relationExt("users", false),
          },
          title: { type: "string", maxLength: 200 },
          starts_at: { type: "string", format: "date-time" },
          capacity: { type: "integer", nullable: true },
          status: { allOf: [{ $ref: "#/components/schemas/StatusEnum" }], readOnly: true },
          is_public: { type: "boolean" },
          organizer: { type: "integer", nullable: true, ...relationExt("users", false) },
          venue: { type: "integer", nullable: true, ...relationExt("venues", false) },
          tags: { type: "array", items: { type: "integer" }, ...relationExt("tags", true) },
        },
        required: [
          "id",
          "created_at",
          "updated_at",
          "created_by",
          "updated_by",
          "title",
          "starts_at",
        ],
      },
      EventRequest: {
        type: "object",
        properties: {
          title: { type: "string", maxLength: 200 },
          starts_at: { type: "string", format: "date-time" },
          capacity: { type: "integer", nullable: true },
          is_public: { type: "boolean" },
          organizer: { type: "integer", nullable: true, ...relationExt("users", false) },
          venue: { type: "integer", nullable: true, ...relationExt("venues", false) },
          tags: { type: "array", items: { type: "integer" }, ...relationExt("tags", true) },
          internal_note: { type: "string", maxLength: 500 },
        },
        required: ["title", "starts_at"],
      },
      PatchedEventRequest: {
        type: "object",
        properties: {
          title: { type: "string", maxLength: 200 },
        },
      },
      PaginatedEventList: {
        type: "object",
        properties: {
          count: { type: "integer" },
          next: { type: "string", nullable: true, format: "uri" },
          previous: { type: "string", nullable: true, format: "uri" },
          results: { type: "array", items: { $ref: "#/components/schemas/Event" } },
        },
        required: ["count", "results"],
      },
    },
  },
};

// --- /api/events/ list behaviour --------------------------------------------

function compareBy(key: string) {
  return (a: DemoEvent, b: DemoEvent): number => {
    const left = (a as unknown as Record<string, unknown>)[key];
    const right = (b as unknown as Record<string, unknown>)[key];
    if (left === null || left === undefined) return right === null || right === undefined ? 0 : -1;
    if (right === null || right === undefined) return 1;
    if (typeof left === "number" && typeof right === "number") return left - right;
    return String(left).localeCompare(String(right));
  };
}

function applyOrdering(events: DemoEvent[], ordering: string | null): DemoEvent[] {
  const keys = (ordering ?? "")
    .split(",")
    .map((key) => key.trim())
    .filter((key) => key.length > 0);
  if (keys.length === 0) return [...events].sort(compareBy("id"));
  return [...events].sort((a, b) => {
    for (const key of keys) {
      const desc = key.startsWith("-");
      const result = compareBy(desc ? key.slice(1) : key)(a, b);
      if (result !== 0) return desc ? -result : result;
    }
    return 0;
  });
}

function expandKeys(url: URL): Set<string> {
  const keys = new Set<string>();
  for (const raw of url.searchParams.getAll("expand")) {
    for (const key of raw.split(",")) {
      if (key.trim().length > 0) keys.add(key.trim());
    }
  }
  return keys;
}

function serializeEvent(event: DemoEvent, expand: Set<string>): Record<string, unknown> {
  return {
    ...event,
    organizer:
      expand.has("organizer") && event.organizer !== null
        ? (ORGANIZERS[event.organizer] ?? event.organizer)
        : event.organizer,
    venue:
      expand.has("venue") && event.venue !== null
        ? (VENUES[event.venue] ?? event.venue)
        : event.venue,
  };
}

/**
 * msw handlers for the demo backend. Register per test with
 * `server.use(...demoHandlers())` or per story via `parameters.msw.handlers`.
 */
export function demoHandlers(events: DemoEvent[] = makeDemoEvents()): RequestHandler[] {
  return [
    http.get("*/api/schema/", () => HttpResponse.json(eventsOpenApi)),
    http.get("*/api/events/", ({ request }) => {
      const url = new URL(request.url);
      let matched = events;

      const search = url.searchParams.get("search");
      if (search !== null && search.trim().length > 0) {
        const query = search.trim().toLowerCase();
        matched = matched.filter((event) => event.title.toLowerCase().includes(query));
      }
      const status = url.searchParams.get("status");
      if (status !== null && status.length > 0) {
        matched = matched.filter((event) => event.status === status);
      }
      const isPublic = url.searchParams.get("is_public");
      if (isPublic === "true" || isPublic === "false") {
        matched = matched.filter((event) => event.is_public === (isPublic === "true"));
      }

      matched = applyOrdering(matched, url.searchParams.get("ordering"));

      const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") || 1);
      const pageSize = Math.max(1, Number(url.searchParams.get("page_size") ?? "25") || 25);
      const pageCount = Math.max(1, Math.ceil(matched.length / pageSize));
      if (page > pageCount && page > 1) {
        return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
      }

      const expand = expandKeys(url);
      const results = matched
        .slice((page - 1) * pageSize, page * pageSize)
        .map((event) => serializeEvent(event, expand));

      const pageUrl = (target: number): string => {
        const next = new URL(request.url);
        next.searchParams.set("page", String(target));
        return next.toString();
      };
      return HttpResponse.json({
        count: matched.length,
        next: page < pageCount ? pageUrl(page + 1) : null,
        previous: page > 1 ? pageUrl(page - 1) : null,
        results,
      });
    }),
  ];
}
