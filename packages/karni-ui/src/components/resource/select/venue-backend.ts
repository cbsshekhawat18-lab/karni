/**
 * A simulated Karni backend for ResourceSelect's tests and stories: a
 * `venues` resource of any size (10,000 rows for the paging stories) with
 * DRF page-number pagination, optional `?search=` (a viewset without
 * search_fields documents no search parameter and ignores it), an optional
 * `?id__in=` filter, and failures on demand. Every request is logged.
 *
 * Test and story support only: never imported by shipped component code.
 */
import { delay, http, HttpResponse, type RequestHandler } from "msw";

export interface VenueRow {
  id: number;
  name: string;
  city: string;
}

const NAMED: ReadonlyArray<[string, string]> = [
  ["Aurora Hall", "Oslo"],
  ["Basalt Rooms", "Reykjavik"],
  ["Cedar Pavilion", "Portland"],
  ["Delta Loft", "Rotterdam"],
  ["Ember Yard", "Lisbon"],
  ["Fjord Stage", "Bergen"],
  ["Berlin Arena", "Berlin"],
  ["Granite Works", "Aberdeen"],
  ["Harbor House", "Hamburg"],
  ["Iris Garden", "Kyoto"],
  ["Juniper Court", "Ljubljana"],
  ["Kite Field", "Wellington"],
];

const CITIES = ["Oslo", "Lisbon", "Kyoto", "Bergen", "Porto", "Turin", "Ghent", "Cork"];

/** `count` venues: twelve named ones, then "Venue 00013", "Venue 00014", ... */
export function makeVenues(count: number = NAMED.length): VenueRow[] {
  return Array.from({ length: count }, (_, index) => {
    const named = NAMED[index];
    return named !== undefined
      ? { id: index + 1, name: named[0], city: named[1] }
      : {
          id: index + 1,
          name: `Venue ${String(index + 1).padStart(5, "0")}`,
          city: CITIES[index % CITIES.length] ?? "Oslo",
        };
  });
}

export type Failure = number | "offline";
export type Delay = number | "infinite";

export interface VenueBackendOptions {
  /** How many venues exist. Default 12. */
  count?: number;
  /** Whether the list documents and honours `?search=`. Default true. */
  search?: boolean;
  /** Whether the list documents and honours `?id__in=1,2`. Default false (Karni's default). */
  idsFilter?: boolean;
  /** The server's page size when the request names none. Default 50. */
  pageSize?: number;
  /** Fail every list request (a status, or "offline" for a dropped connection). */
  listFailure?: Failure;
  /** Fail list requests for pages after the first. */
  nextPageFailure?: Failure;
  /** Fail every detail request. */
  detailFailure?: Failure;
  /** Delay every list request. */
  listDelay?: Delay;
  /** Delay list requests that carry a search term (the "Searching…" state). */
  searchDelay?: Delay;
  /** Delay every detail request. */
  detailDelay?: Delay;
}

export interface VenueBackend {
  handlers: RequestHandler[];
  /** Every venues request, in order. */
  requests: URL[];
  rows: VenueRow[];
  /** The list requests only. */
  listRequests: () => URL[];
}

function query(name: string, type: string): Record<string, unknown> {
  return { in: "query", name, required: false, schema: { type } };
}

/** The OpenAPI document of the simulated backend (drf-spectacular dialect). */
export function venueOpenApi(options: Pick<VenueBackendOptions, "search" | "idsFilter"> = {}) {
  const { search = true, idsFilter = false } = options;
  const venue = {
    type: "object",
    required: ["id", "name", "city"],
    properties: {
      id: { type: "integer", readOnly: true },
      name: { type: "string", maxLength: 200 },
      city: { type: "string", maxLength: 100 },
    },
  };
  return {
    openapi: "3.0.3",
    info: { title: "Venues", version: "1.0.0" },
    "x-karni-auth-mode": "jwt",
    paths: {
      "/api/venues/": {
        get: {
          operationId: "venues_list",
          "x-karni-resource": "venues",
          parameters: [
            query("city", "string"),
            ...(idsFilter ? [query("id__in", "string")] : []),
            query("ordering", "string"),
            query("page", "integer"),
            query("page_size", "integer"),
            ...(search ? [query("search", "string")] : []),
          ],
          responses: {
            "200": {
              description: "",
              content: {
                "application/json": { schema: { $ref: "#/components/schemas/PaginatedVenueList" } },
              },
            },
          },
        },
      },
      "/api/venues/{id}/": {
        get: {
          operationId: "venues_retrieve",
          parameters: [{ in: "path", name: "id", required: true, schema: { type: "integer" } }],
          responses: {
            "200": {
              description: "",
              content: { "application/json": { schema: { $ref: "#/components/schemas/Venue" } } },
            },
          },
        },
      },
    },
    components: {
      schemas: {
        Venue: venue,
        PaginatedVenueList: {
          type: "object",
          required: ["count", "results"],
          properties: {
            count: { type: "integer" },
            next: { type: "string", nullable: true, format: "uri" },
            previous: { type: "string", nullable: true, format: "uri" },
            results: { type: "array", items: { $ref: "#/components/schemas/Venue" } },
          },
        },
      },
    },
  };
}

async function wait(value: Delay | undefined): Promise<void> {
  if (value === undefined) return;
  await delay(value);
}

function failWith(failure: Failure): Response {
  if (failure === "offline") return HttpResponse.error();
  return HttpResponse.json(
    failure === 403
      ? { detail: "You do not have permission to perform this action." }
      : { detail: "Server error." },
    { status: failure },
  );
}

/** Handlers for the schema and the venues endpoints, plus the request log. */
export function venueBackend(options: VenueBackendOptions = {}): VenueBackend {
  const {
    count = NAMED.length,
    search = true,
    idsFilter = false,
    pageSize: defaultPageSize = 50,
    listFailure,
    nextPageFailure,
    detailFailure,
    listDelay,
    searchDelay,
    detailDelay,
  } = options;
  const rows = makeVenues(count);
  const requests: URL[] = [];
  const schema = venueOpenApi({ search, idsFilter });

  const handlers: RequestHandler[] = [
    http.get("*/api/schema/", () => HttpResponse.json(schema)),
    http.get("*/api/venues/", async ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const term = (url.searchParams.get("search") ?? "").trim().toLowerCase();
      await wait(listDelay);
      if (term !== "") await wait(searchDelay);
      if (listFailure !== undefined) return failWith(listFailure);
      const page = Number(url.searchParams.get("page") ?? "1");
      if (page > 1 && nextPageFailure !== undefined) return failWith(nextPageFailure);

      let matched = rows;
      if (search && term !== "") {
        matched = matched.filter(
          (row) => row.name.toLowerCase().includes(term) || row.city.toLowerCase().includes(term),
        );
      }
      const city = url.searchParams.get("city");
      if (city !== null) matched = matched.filter((row) => row.city === city);
      const ids = url.searchParams.get("id__in");
      if (idsFilter && ids !== null) {
        const wanted = new Set(ids.split(",").map((id) => id.trim()));
        matched = matched.filter((row) => wanted.has(String(row.id)));
      }

      const size = Math.min(Number(url.searchParams.get("page_size") ?? defaultPageSize), 100);
      const pageCount = Math.max(1, Math.ceil(matched.length / size));
      if (page > pageCount) return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
      const next = new URL(url.toString());
      next.searchParams.set("page", String(page + 1));
      return HttpResponse.json({
        count: matched.length,
        next: page < pageCount ? next.toString() : null,
        previous: null,
        results: matched.slice((page - 1) * size, page * size),
      });
    }),
    http.get("*/api/venues/:id/", async ({ request, params }) => {
      requests.push(new URL(request.url));
      await wait(detailDelay);
      if (detailFailure !== undefined) return failWith(detailFailure);
      const row = rows.find((candidate) => String(candidate.id) === String(params["id"]));
      return row === undefined
        ? HttpResponse.json({ detail: "No Venue matches the given query." }, { status: 404 })
        : HttpResponse.json(row);
    }),
  ];

  return {
    handlers,
    requests,
    rows,
    listRequests: () => requests.filter((url) => url.pathname.endsWith("/venues/")),
  };
}
