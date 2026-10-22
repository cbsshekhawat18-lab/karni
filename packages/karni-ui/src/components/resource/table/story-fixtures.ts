/**
 * Backends for ResourceTable's state and real-size stories (and tests): a
 * 50-column resource, a 100,000-row list computed page by page, an events
 * schema with `x-karni-access` rules, and an in-memory state store.
 *
 * Test/story support only. Shipped component code never imports it.
 */
import { http, HttpResponse, type RequestHandler } from "msw";
import type { ResourceTableStateStore } from "./url-state";
import { eventsOpenApi } from "./demo-fixtures";

// 50 columns

export const WIDE_COLUMN_COUNT = 50;

const METRIC_NAMES = [
  "region",
  "revenue",
  "orders",
  "refunds",
  "visitors",
  "signups",
  "churn",
  "margin",
  "tickets",
  "nps",
];

function metricField(index: number): string {
  return `${METRIC_NAMES[index % METRIC_NAMES.length] ?? "metric"}_${String(Math.floor(index / METRIC_NAMES.length) + 1)}`;
}

/** Field names of the wide resource: `name`, then 49 metrics. */
export const WIDE_FIELDS: readonly string[] = [
  "name",
  ...Array.from({ length: WIDE_COLUMN_COUNT - 1 }, (_, index) => metricField(index)),
];

export const wideOpenApi: Record<string, unknown> = {
  openapi: "3.0.3",
  info: { title: "Wide demo API", version: "0.1.0" },
  paths: {
    "/api/metrics/": {
      get: {
        operationId: "metrics_list",
        "x-karni-resource": "metrics",
        parameters: [
          { name: "ordering", in: "query", schema: { type: "string" } },
          { name: "page", in: "query", schema: { type: "integer" } },
          { name: "page_size", in: "query", schema: { type: "integer" } },
          { name: "search", in: "query", schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    count: { type: "integer" },
                    next: { type: "string", nullable: true },
                    previous: { type: "string", nullable: true },
                    results: { type: "array", items: { $ref: "#/components/schemas/Metric" } },
                  },
                },
              },
            },
          },
        },
      },
    },
  },
  components: {
    schemas: {
      Metric: {
        type: "object",
        properties: Object.fromEntries([
          ["id", { type: "integer", readOnly: true }],
          ["name", { type: "string", readOnly: true }],
          ...WIDE_FIELDS.slice(1).map((name) => [name, { type: "integer", readOnly: true }]),
        ]),
      },
    },
  },
};

function wideRow(id: number): Record<string, unknown> {
  const row: Record<string, unknown> = { id, name: `Store ${String(id).padStart(3, "0")}` };
  WIDE_FIELDS.slice(1).forEach((name, index) => {
    row[name] = ((id * 7919 + index * 104729) % 9000) + 100;
  });
  return row;
}

function pageOf(url: URL, total: number): { page: number; size: number; pages: number } {
  const size = Math.max(1, Number(url.searchParams.get("page_size") ?? "25") || 25);
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") || 1);
  return { page, size, pages: Math.max(1, Math.ceil(total / size)) };
}

function pageLink(request: Request, page: number): string {
  const next = new URL(request.url);
  next.searchParams.set("page", String(page));
  return next.toString();
}

export function wideHandlers(total = 120): RequestHandler[] {
  return [
    http.get("*/api/schema/", () => HttpResponse.json(wideOpenApi)),
    http.get("*/api/metrics/", ({ request }) => {
      const { page, size, pages } = pageOf(new URL(request.url), total);
      if (page > pages) return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
      const first = (page - 1) * size + 1;
      const last = Math.min(total, page * size);
      return HttpResponse.json({
        count: total,
        next: page < pages ? pageLink(request, page + 1) : null,
        previous: page > 1 ? pageLink(request, page - 1) : null,
        results: Array.from({ length: last - first + 1 }, (_, index) => wideRow(first + index)),
      });
    }),
  ];
}

// 100,000 rows, built one page at a time

export const LARGE_EVENT_COUNT = 100_000;

function largeEvent(id: number): Record<string, unknown> {
  const created = new Date(Date.UTC(2024, 0, 1) + id * 60_000).toISOString();
  return {
    id,
    created_at: created,
    updated_at: created,
    created_by: 1,
    updated_by: null,
    title: `Event ${String(id).padStart(6, "0")}`,
    starts_at: new Date(Date.UTC(2026, 0, 1) + id * 3_600_000).toISOString(),
    capacity: id % 5 === 0 ? null : (id % 40) * 10 + 20,
    status: id % 3 === 0 ? "PUBLISHED" : "DRAFT",
    is_public: id % 2 === 0,
    organizer: null,
    venue: id % 2 === 1 ? 1 : 2,
    tags: [],
  };
}

/** `/api/events/` with `total` rows. Only the requested page is ever built. */
export function largeHandlers(total = LARGE_EVENT_COUNT): RequestHandler[] {
  return [
    http.get("*/api/schema/", () => HttpResponse.json(eventsOpenApi)),
    http.get("*/api/events/", ({ request }) => {
      const url = new URL(request.url);
      const { page, size, pages } = pageOf(url, total);
      if (page > pages) return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
      const descending = (url.searchParams.get("ordering") ?? "").startsWith("-");
      const first = (page - 1) * size;
      const ids = Array.from({ length: Math.min(size, total - first) }, (_, index) =>
        descending ? total - first - index : first + index + 1,
      );
      return HttpResponse.json({
        count: total,
        next: page < pages ? pageLink(request, page + 1) : null,
        previous: page > 1 ? pageLink(request, page - 1) : null,
        results: ids.map(largeEvent),
      });
    }),
  ];
}

// access rules (x-karni-access)

function withAccess(
  document: Record<string, unknown>,
  rules: Record<string, Record<string, unknown>>,
): Record<string, unknown> {
  const copy = JSON.parse(JSON.stringify(document)) as {
    paths: Record<string, Record<string, Record<string, unknown>>>;
  };
  for (const [key, rule] of Object.entries(rules)) {
    const [path, method] = key.split(" ");
    const operation =
      path === undefined || method === undefined ? undefined : copy.paths[path]?.[method];
    if (operation !== undefined) operation["x-karni-access"] = rule;
  }
  return copy as unknown as Record<string, unknown>;
}

/**
 * The events schema as a backend with `Access(write=Owned("organizer") |
 * HasRole("staff"), create=HasRole("staff"))` and deletes for admins only
 * publishes it.
 */
export const accessOpenApi = withAccess(eventsOpenApi, {
  "/api/events/ get": { public: true },
  "/api/events/ post": { role: ["staff"] },
  "/api/events/{id}/ patch": { any: [{ owned: "organizer" }, { role: ["staff"] }] },
  "/api/events/{id}/ delete": { role: ["admin"] },
});

/**
 * `accessOpenApi` as a role that may not read `capacity` (`Karni.field_roles`):
 * the per-role schema leaves the field out, so the column is absent.
 */
export const partialOpenApi = ((): Record<string, unknown> => {
  const copy = JSON.parse(JSON.stringify(accessOpenApi)) as {
    components: { schemas: Record<string, { properties: Record<string, unknown> }> };
  };
  for (const name of ["Event", "EventRequest"]) {
    delete copy.components.schemas[name]?.properties["capacity"];
  }
  return copy as unknown as Record<string, unknown>;
})();

// an in-memory store (a router stand-in)

/** A ResourceTableStateStore over a plain object: what a router adapter looks like. */
export function memoryStateStore(
  initial: Record<string, string> = {},
): ResourceTableStateStore & { values: Record<string, string> } {
  const listeners = new Set<() => void>();
  const store = {
    values: { ...initial },
    read: () => store.values,
    write(changes: Readonly<Record<string, string | null>>) {
      const next = new Map(Object.entries(store.values));
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      store.values = Object.fromEntries(next);
      for (const listener of listeners) listener();
    },
    subscribe(onChange: () => void) {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
  };
  return store;
}
