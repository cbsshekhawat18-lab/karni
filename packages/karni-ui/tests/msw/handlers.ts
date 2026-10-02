/**
 * MSW handlers simulating a Karni backend (every suite imports from here).
 *
 * Endpoints (any origin — handlers are registered with a leading `*`; use an
 * absolute baseUrl such as "http://karni.test" in tests, Node's fetch rejects
 * relative URLs):
 * - GET  *\/api/schema/                    → the handwritten OpenAPI fixture
 * - CRUD *\/api/events/ (+ /{id}/)         → pagination, search, ordering,
 *   filters (status/category/is_public/venue/organizer), expand with B9-style
 *   validation, JSON + multipart bodies, DRF-shaped 400/404 errors
 * - GET  *\/api/{venues,tags,users}/ (+ /{id}/) → read-only resources with
 *   search + pagination (ResourceSelect fodder)
 * - *\/api/auth/{login,refresh,logout,me,csrf,2fa/login}/ → JWT flows with
 *   rotating refresh tokens (D6)
 *
 * State: module-level in-memory DB + token registry. Vitest isolates test
 * files, so state is fresh per file; within a file call `resetMswData()` in
 * `beforeEach` when tests mutate data. Auth test controls:
 * `authTestControls.invalidateAccessTokens()` forces the next authed request
 * to 401 (refresh-race suites), `.invalidateRefreshToken()` kills the session.
 */
import { http, HttpResponse } from "msw";
import { openApiFixture } from "./openapi";

export { openApiFixture, openApiFixtureWithAuthMode } from "./openapi";

// --- fixture records ---------------------------------------------------------

export interface VenueRecord {
  id: number;
  name: string;
  city: string;
}

export interface TagRecord {
  id: number;
  name: string;
}

export interface UserRecord {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
}

export interface EventRecord {
  id: number;
  title: string;
  description: string;
  starts_at: string;
  capacity: number | null;
  status: "draft" | "published";
  category: "conference" | "meetup" | "workshop" | null;
  priority: "low" | "high" | "";
  is_public: boolean;
  organizer: number | null;
  venue: number | null;
  tags: number[];
  poster: string | null;
  contact_email: string;
  website: string;
  metadata: unknown;
  /** writeOnly — accepted on create/update, never serialized. */
  internal_note: string;
  created_at: string;
  updated_at: string;
}

function seedVenues(): VenueRecord[] {
  return [
    { id: 1, name: "Grand Hall", city: "Jaipur" },
    { id: 2, name: "Riverside Pavilion", city: "Udaipur" },
    { id: 3, name: "Summit Center", city: "Jodhpur" },
  ];
}

function seedTags(): TagRecord[] {
  return [
    { id: 1, name: "tech" },
    { id: 2, name: "design" },
    { id: 3, name: "community" },
  ];
}

function seedUsers(): UserRecord[] {
  return [
    { id: 1, email: "ada@example.com", first_name: "Ada", last_name: "Lovelace" },
    { id: 2, email: "grace@example.com", first_name: "Grace", last_name: "Hopper" },
  ];
}

function seedEvents(): EventRecord[] {
  const titles = [
    "Annual Conference",
    "Design Meetup",
    "API Workshop",
    "Launch Party",
    "Quarterly Review",
    "Hack Night",
    "Community Picnic",
    "Keynote Rehearsal",
    "Partner Summit",
    "Office Hours",
    "Retro Session",
    "Town Hall",
  ];
  return titles.map((title, index) => {
    const id = index + 1;
    const day = String(id).padStart(2, "0");
    return {
      id,
      title,
      description: `Description for ${title.toLowerCase()}`,
      starts_at: `2026-11-${day}T10:00:00Z`,
      capacity: id % 3 === 0 ? null : id * 10,
      status: id % 2 === 0 ? "published" : "draft",
      category: id % 4 === 0 ? null : (["conference", "meetup", "workshop"] as const)[id % 3],
      priority: id % 5 === 0 ? "" : id % 2 === 0 ? "high" : "low",
      is_public: id % 2 === 0,
      organizer: id % 3 === 0 ? null : (id % 2) + 1,
      venue: id % 4 === 0 ? null : (id % 3) + 1,
      tags: id % 3 === 0 ? [] : [(id % 3) + 1],
      poster: null,
      contact_email: "",
      website: "",
      metadata: null,
      internal_note: "",
      created_at: `2026-10-${day}T09:00:00Z`,
      updated_at: `2026-10-${day}T09:00:00Z`,
    } satisfies EventRecord;
  });
}

interface MswDb {
  events: EventRecord[];
  venues: VenueRecord[];
  tags: TagRecord[];
  users: UserRecord[];
  nextEventId: number;
}

function freshDb(): MswDb {
  const events = seedEvents();
  return {
    events,
    venues: seedVenues(),
    tags: seedTags(),
    users: seedUsers(),
    nextEventId: events.length + 1,
  };
}

/** Live in-memory state; read it in assertions, mutate it to stage scenarios. */
export const mswDb: MswDb = freshDb();

// --- auth state --------------------------------------------------------------

export const TEST_USER = {
  id: 1,
  email: "ada@example.com",
  password: "correct-horse",
  first_name: "Ada",
  last_name: "Lovelace",
  roles: ["admin", "editor"],
};

export const TEST_2FA_USER = {
  id: 2,
  email: "grace@example.com",
  password: "correct-horse",
  roles: ["viewer"],
};

export const TEST_OTP = "123456";
export const TEST_EPHEMERAL_TOKEN = "ephemeral-2fa-token";
export const TEST_CSRF_TOKEN = "test-csrf-token";

interface AuthState {
  counter: number;
  validAccessTokens: Set<string>;
  currentRefreshToken: string | null;
}

const authState: AuthState = {
  counter: 0,
  validAccessTokens: new Set(),
  currentRefreshToken: null,
};

function issueTokens(): { access: string; refresh: string } {
  authState.counter += 1;
  const access = `access-${authState.counter}`;
  const refresh = `refresh-${authState.counter}`;
  authState.validAccessTokens.add(access);
  authState.currentRefreshToken = refresh;
  return { access, refresh };
}

/** Hooks for auth suites to stage 401s and dead sessions deterministically. */
export const authTestControls = {
  /** Expire every issued access token: next Bearer request 401s (D6 races). */
  invalidateAccessTokens(): void {
    authState.validAccessTokens.clear();
  },
  /** Kill the refresh token: the next refresh attempt 401s. */
  invalidateRefreshToken(): void {
    authState.currentRefreshToken = null;
  },
  /** Issued-token snapshot for assertions. */
  snapshot(): { validAccessTokens: string[]; currentRefreshToken: string | null } {
    return {
      validAccessTokens: [...authState.validAccessTokens],
      currentRefreshToken: authState.currentRefreshToken,
    };
  },
};

/** Restores the DB seed and clears the token registry. */
export function resetMswData(): void {
  const next = freshDb();
  mswDb.events = next.events;
  mswDb.venues = next.venues;
  mswDb.tags = next.tags;
  mswDb.users = next.users;
  mswDb.nextEventId = next.nextEventId;
  authState.counter = 0;
  authState.validAccessTokens.clear();
  authState.currentRefreshToken = null;
}

// --- shared helpers ----------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function notFound(model: string) {
  return HttpResponse.json({ detail: `No ${model} matches the given query.` }, { status: 404 });
}

/** DRF PageNumberPagination over already-filtered rows (404 on invalid page). */
function paginate<T>(url: URL, rows: readonly T[]) {
  const pageRaw = url.searchParams.get("page");
  const sizeRaw = url.searchParams.get("page_size");
  const page = pageRaw === null ? 1 : Number(pageRaw);
  const pageSize = sizeRaw === null ? 10 : Math.min(Math.max(Number(sizeRaw), 1), 100);
  if (!Number.isInteger(page) || page < 1) {
    return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
  }
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (page > totalPages) {
    return HttpResponse.json({ detail: "Invalid page." }, { status: 404 });
  }
  const results = rows.slice((page - 1) * pageSize, page * pageSize);
  const pageUrl = (target: number): string => {
    const next = new URL(url.toString());
    next.searchParams.set("page", String(target));
    return next.toString();
  };
  return HttpResponse.json({
    count: rows.length,
    next: page < totalPages ? pageUrl(page + 1) : null,
    previous: page > 1 ? pageUrl(page - 1) : null,
    results,
  });
}

/** DRF getlist + comma merge for repeatable params like expand. */
function getListParam(url: URL, name: string): string[] {
  return url.searchParams
    .getAll(name)
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

function compareValues(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  // Code-point order, like DRF/Postgres C collation — NOT locale collation.
  const left = String(a);
  const right = String(b);
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function orderRows<T extends object>(
  rows: readonly T[],
  ordering: string | null,
  allowed: readonly string[],
  fallback: string,
): T[] {
  const keys = (ordering === null || ordering.trim() === "" ? fallback : ordering)
    .split(",")
    .map((key) => key.trim())
    .filter((key) => allowed.includes(key.replace(/^-/, "")));
  const sorted = [...rows];
  if (keys.length === 0) return sorted;
  sorted.sort((a, b) => {
    for (const key of keys) {
      const descending = key.startsWith("-");
      const field = descending ? key.slice(1) : key;
      const result = compareValues(
        (a as Record<string, unknown>)[field],
        (b as Record<string, unknown>)[field],
      );
      if (result !== 0) return descending ? -result : result;
    }
    return 0;
  });
  return sorted;
}

// --- events ------------------------------------------------------------------

const EVENT_EXPAND_KEYS = ["organizer", "venue", "tags"] as const;

function expandError(key: string) {
  return HttpResponse.json(
    { expand: [`Invalid expand key "${key}". Allowed keys: ${EVENT_EXPAND_KEYS.join(", ")}.`] },
    { status: 400 },
  );
}

function serializeEvent(record: EventRecord, expand: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = { ...record };
  delete out["internal_note"]; // writeOnly: never serialized
  if (expand.includes("organizer") && record.organizer !== null) {
    out["organizer"] = mswDb.users.find((user) => user.id === record.organizer) ?? record.organizer;
  }
  if (expand.includes("venue") && record.venue !== null) {
    out["venue"] = mswDb.venues.find((venue) => venue.id === record.venue) ?? record.venue;
  }
  if (expand.includes("tags")) {
    out["tags"] = record.tags.map((id) => mswDb.tags.find((tag) => tag.id === id) ?? id);
  }
  return out;
}

function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export interface MultipartEntry {
  name: string;
  value: string;
  filename?: string;
}

/**
 * Minimal multipart/form-data parser working on the raw text body.
 *
 * Deliberately NOT `request.formData()`: Node's bundled undici constructs
 * file entries with the *global* File and then asserts its own internal
 * `isFileLike` on them — under jsdom (which replaces global File) that
 * assertion always fails, so formData() cannot parse file parts in this test
 * environment. Text-level parsing is exact for everything D2 encodes.
 * Exported so per-test `server.use(...)` overrides that receive multipart
 * bodies can decode them the same way instead of hanging on formData().
 */
export function parseMultipartEntries(raw: string, contentType: string): MultipartEntry[] {
  const boundaryMatch = /boundary="?([^";]+)"?/.exec(contentType);
  if (boundaryMatch === null) return [];
  const delimiter = `--${boundaryMatch[1] ?? ""}`;
  const entries: MultipartEntry[] = [];
  for (const chunk of raw.split(delimiter)) {
    const headerEnd = chunk.indexOf("\r\n\r\n");
    if (headerEnd === -1) continue; // preamble / closing "--"
    const headerBlock = chunk.slice(0, headerEnd);
    let value = chunk.slice(headerEnd + 4);
    if (value.endsWith("\r\n")) value = value.slice(0, -2);
    const nameMatch = /name="([^"]*)"/.exec(headerBlock);
    if (nameMatch === null) continue;
    const entry: MultipartEntry = { name: nameMatch[1] ?? "", value };
    const filenameMatch = /filename="([^"]*)"/.exec(headerBlock);
    const filename = filenameMatch?.[1];
    if (filename !== undefined) entry.filename = filename;
    entries.push(entry);
  }
  return entries;
}

/**
 * Reads a JSON or multipart body into one plain record. Multipart decoding
 * mirrors D2's encoding rules: repeated keys → arrays, `metadata` arrives
 * JSON-stringified, a `poster` file part becomes its stored media URL.
 */
async function readEventBody(request: Request): Promise<Record<string, unknown>> {
  const contentType = request.headers.get("content-type") ?? "";
  if (contentType.includes("multipart/form-data")) {
    const grouped = new Map<string, MultipartEntry[]>();
    for (const entry of parseMultipartEntries(await request.text(), contentType)) {
      const list = grouped.get(entry.name) ?? [];
      list.push(entry);
      grouped.set(entry.name, list);
    }
    const out: Record<string, unknown> = {};
    for (const [key, list] of grouped) {
      const mapped = list.map((entry) =>
        entry.filename !== undefined
          ? `http://karni.test/media/events/${entry.filename}`
          : entry.value,
      );
      out[key] = key === "tags" ? mapped : (mapped[0] ?? "");
    }
    if (typeof out["metadata"] === "string") {
      try {
        out["metadata"] = JSON.parse(out["metadata"]);
      } catch {
        // leave the raw string; DRF would 400, the fixture stays lenient
      }
    }
    return out;
  }
  const body: unknown = await request.json().catch(() => null);
  return isRecord(body) ? body : {};
}

function applyEventBody(record: EventRecord, body: Record<string, unknown>): void {
  if ("title" in body) record.title = String(body["title"] ?? "");
  if ("description" in body) record.description = String(body["description"] ?? "");
  if ("starts_at" in body) record.starts_at = String(body["starts_at"] ?? "");
  if ("capacity" in body) record.capacity = toNumberOrNull(body["capacity"]);
  if ("category" in body) {
    const value = body["category"];
    record.category =
      value === "conference" || value === "meetup" || value === "workshop" ? value : null;
  }
  if ("priority" in body) {
    const value = body["priority"];
    record.priority = value === "low" || value === "high" ? value : "";
  }
  if ("is_public" in body) {
    record.is_public = body["is_public"] === true || body["is_public"] === "true";
  }
  if ("organizer" in body) record.organizer = toNumberOrNull(body["organizer"]);
  if ("venue" in body) record.venue = toNumberOrNull(body["venue"]);
  if ("tags" in body) {
    const raw = body["tags"];
    record.tags = Array.isArray(raw)
      ? raw.map((value) => Number(value)).filter((value) => Number.isInteger(value))
      : [];
  }
  if ("poster" in body) {
    const value = body["poster"];
    record.poster = typeof value === "string" && value !== "" ? value : null;
  }
  if ("contact_email" in body) record.contact_email = String(body["contact_email"] ?? "");
  if ("website" in body) record.website = String(body["website"] ?? "");
  if ("metadata" in body) record.metadata = body["metadata"];
  if ("internal_note" in body) record.internal_note = String(body["internal_note"] ?? "");
}

function validateEventBody(
  body: Record<string, unknown>,
  partial: boolean,
): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  for (const field of ["title", "starts_at"]) {
    const present = field in body;
    const value = body[field];
    if (!present) {
      if (!partial) errors[field] = ["This field is required."];
    } else if (value === "" || value === null) {
      errors[field] = ["This field may not be blank."];
    }
  }
  const title = body["title"];
  if (typeof title === "string" && title.length > 200) {
    errors["title"] = ["Ensure this field has no more than 200 characters."];
  }
  return errors;
}

function eventFromParams(
  params: Record<string, string | readonly string[] | undefined>,
): EventRecord | null {
  const raw = params["id"];
  const id = Number(typeof raw === "string" ? raw : "");
  return mswDb.events.find((event) => event.id === id) ?? null;
}

const eventHandlers = [
  http.get("*/api/events/", ({ request }) => {
    const url = new URL(request.url);
    const expand = getListParam(url, "expand");
    for (const key of expand) {
      if (!EVENT_EXPAND_KEYS.includes(key as (typeof EVENT_EXPAND_KEYS)[number])) {
        return expandError(key);
      }
    }

    let rows = [...mswDb.events];
    const search = url.searchParams.get("search");
    if (search !== null && search.trim() !== "") {
      const needle = search.trim().toLowerCase();
      rows = rows.filter(
        (event) =>
          event.title.toLowerCase().includes(needle) ||
          event.description.toLowerCase().includes(needle),
      );
    }
    const status = url.searchParams.get("status");
    if (status !== null && status !== "") rows = rows.filter((event) => event.status === status);
    const category = url.searchParams.get("category");
    if (category !== null && category !== "") {
      rows = rows.filter((event) => event.category === category);
    }
    const isPublic = url.searchParams.get("is_public");
    if (isPublic !== null && isPublic !== "") {
      rows = rows.filter((event) => event.is_public === (isPublic === "true"));
    }
    const venue = url.searchParams.get("venue");
    if (venue !== null && venue !== "")
      rows = rows.filter((event) => event.venue === Number(venue));
    const organizer = url.searchParams.get("organizer");
    if (organizer !== null && organizer !== "") {
      rows = rows.filter((event) => event.organizer === Number(organizer));
    }

    rows = orderRows(
      rows,
      url.searchParams.get("ordering"),
      ["id", "title", "starts_at", "capacity", "created_at", "updated_at"],
      "-created_at",
    );
    const serialized = rows.map((event) => serializeEvent(event, expand));
    return paginate(url, serialized);
  }),

  http.post("*/api/events/", async ({ request }) => {
    const body = await readEventBody(request);
    const errors = validateEventBody(body, false);
    if (Object.keys(errors).length > 0) {
      return HttpResponse.json(errors, { status: 400 });
    }
    const now = new Date().toISOString();
    const record: EventRecord = {
      id: mswDb.nextEventId,
      title: "",
      description: "",
      starts_at: "",
      capacity: null,
      status: "draft",
      category: null,
      priority: "",
      is_public: false,
      organizer: null,
      venue: null,
      tags: [],
      poster: null,
      contact_email: "",
      website: "",
      metadata: null,
      internal_note: "",
      created_at: now,
      updated_at: now,
    };
    mswDb.nextEventId += 1;
    applyEventBody(record, body);
    mswDb.events.push(record);
    return HttpResponse.json(serializeEvent(record, []), { status: 201 });
  }),

  http.get("*/api/events/:id/", ({ request, params }) => {
    const record = eventFromParams(params);
    if (record === null) return notFound("Event");
    const url = new URL(request.url);
    const expand = getListParam(url, "expand");
    for (const key of expand) {
      if (!EVENT_EXPAND_KEYS.includes(key as (typeof EVENT_EXPAND_KEYS)[number])) {
        return expandError(key);
      }
    }
    return HttpResponse.json(serializeEvent(record, expand));
  }),

  http.patch("*/api/events/:id/", async ({ request, params }) => {
    const record = eventFromParams(params);
    if (record === null) return notFound("Event");
    const body = await readEventBody(request);
    const errors = validateEventBody(body, true);
    if (Object.keys(errors).length > 0) {
      return HttpResponse.json(errors, { status: 400 });
    }
    applyEventBody(record, body);
    record.updated_at = new Date().toISOString();
    return HttpResponse.json(serializeEvent(record, []));
  }),

  http.put("*/api/events/:id/", async ({ request, params }) => {
    const record = eventFromParams(params);
    if (record === null) return notFound("Event");
    const body = await readEventBody(request);
    const errors = validateEventBody(body, false);
    if (Object.keys(errors).length > 0) {
      return HttpResponse.json(errors, { status: 400 });
    }
    applyEventBody(record, body);
    record.updated_at = new Date().toISOString();
    return HttpResponse.json(serializeEvent(record, []));
  }),

  http.delete("*/api/events/:id/", ({ params }) => {
    const record = eventFromParams(params);
    if (record === null) return notFound("Event");
    mswDb.events = mswDb.events.filter((event) => event.id !== record.id);
    return new HttpResponse(null, { status: 204 });
  }),
];

// --- read-only resources (venues / tags / users) ------------------------------

function readOnlyListHandler<T extends object>(
  resource: string,
  rows: () => readonly T[],
  searchFields: ReadonlyArray<keyof T & string>,
) {
  return http.get(`*/api/${resource}/`, ({ request }) => {
    const url = new URL(request.url);
    let filtered = [...rows()];
    const search = url.searchParams.get("search");
    if (search !== null && search.trim() !== "") {
      const needle = search.trim().toLowerCase();
      filtered = filtered.filter((row) =>
        searchFields.some((field) =>
          String((row as Record<string, unknown>)[field])
            .toLowerCase()
            .includes(needle),
        ),
      );
    }
    filtered = orderRows(filtered, url.searchParams.get("ordering"), ["id", ...searchFields], "id");
    return paginate(url, filtered);
  });
}

function readOnlyDetailHandler<T extends { id: number }>(
  resource: string,
  model: string,
  rows: () => readonly T[],
) {
  return http.get(`*/api/${resource}/:id/`, ({ params }) => {
    const raw = params["id"];
    const id = Number(typeof raw === "string" ? raw : "");
    const row = rows().find((candidate) => candidate.id === id);
    return row === undefined ? notFound(model) : HttpResponse.json(row);
  });
}

const readOnlyHandlers = [
  readOnlyListHandler("venues", () => mswDb.venues, ["name", "city"]),
  readOnlyDetailHandler("venues", "Venue", () => mswDb.venues),
  readOnlyListHandler("tags", () => mswDb.tags, ["name"]),
  readOnlyDetailHandler("tags", "Tag", () => mswDb.tags),
  readOnlyListHandler("users", () => mswDb.users, ["email", "first_name", "last_name"]),
  readOnlyDetailHandler("users", "User", () => mswDb.users),
];

// --- auth --------------------------------------------------------------------

function meUser(): Record<string, unknown> {
  return {
    id: TEST_USER.id,
    email: TEST_USER.email,
    first_name: TEST_USER.first_name,
    last_name: TEST_USER.last_name,
    email_verified: true,
    date_joined: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    roles: TEST_USER.roles,
  };
}

function bearerToken(request: Request): string | null {
  const header = request.headers.get("authorization");
  if (header === null || !header.startsWith("Bearer ")) return null;
  return header.slice("Bearer ".length);
}

const authHandlers = [
  http.post("*/api/auth/login/", async ({ request }) => {
    const body: unknown = await request.json().catch(() => null);
    const email = isRecord(body) && typeof body["email"] === "string" ? body["email"] : "";
    const password = isRecord(body) && typeof body["password"] === "string" ? body["password"] : "";
    if (email === TEST_2FA_USER.email && password === TEST_2FA_USER.password) {
      return HttpResponse.json({ requires_2fa: true, ephemeral_token: TEST_EPHEMERAL_TOKEN });
    }
    if (email === TEST_USER.email && password === TEST_USER.password) {
      return HttpResponse.json(issueTokens());
    }
    return HttpResponse.json(
      { detail: "No active account found with the given credentials" },
      { status: 401 },
    );
  }),

  http.post("*/api/auth/2fa/login/", async ({ request }) => {
    const body: unknown = await request.json().catch(() => null);
    const token =
      isRecord(body) && typeof body["ephemeral_token"] === "string" ? body["ephemeral_token"] : "";
    const otp = isRecord(body) && typeof body["otp"] === "string" ? body["otp"] : "";
    if (token === TEST_EPHEMERAL_TOKEN && otp === TEST_OTP) {
      return HttpResponse.json(issueTokens());
    }
    return HttpResponse.json({ detail: "Invalid or expired two-factor code." }, { status: 400 });
  }),

  http.post("*/api/auth/refresh/", async ({ request }) => {
    const body: unknown = await request.json().catch(() => null);
    const refresh = isRecord(body) && typeof body["refresh"] === "string" ? body["refresh"] : "";
    if (refresh !== "" && refresh === authState.currentRefreshToken) {
      // Rotation: the old refresh token is dead from this point on (D6).
      return HttpResponse.json(issueTokens());
    }
    return HttpResponse.json(
      { detail: "Token is invalid or expired", code: "token_not_valid" },
      { status: 401 },
    );
  }),

  http.post("*/api/auth/logout/", () => {
    authState.currentRefreshToken = null;
    authState.validAccessTokens.clear();
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/api/auth/me/", ({ request }) => {
    const token = bearerToken(request);
    if (token === null) {
      return HttpResponse.json(
        { detail: "Authentication credentials were not provided." },
        { status: 401 },
      );
    }
    if (!authState.validAccessTokens.has(token)) {
      return HttpResponse.json(
        { detail: "Given token not valid for any token type", code: "token_not_valid" },
        { status: 401 },
      );
    }
    return HttpResponse.json(meUser());
  }),

  http.get(
    "*/api/auth/csrf/",
    () =>
      new HttpResponse(null, {
        status: 204,
        headers: { "set-cookie": `csrftoken=${TEST_CSRF_TOKEN}; Path=/` },
      }),
  ),
];

// --- schema + export ---------------------------------------------------------

const schemaHandler = http.get("*/api/schema/", () => HttpResponse.json(openApiFixture));

export const handlers = [schemaHandler, ...eventHandlers, ...readOnlyHandlers, ...authHandlers];
