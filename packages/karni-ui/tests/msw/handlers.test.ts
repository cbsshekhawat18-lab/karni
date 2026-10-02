/**
 * Behavior lock for the simulated backend (tests/msw/handlers.ts): the table,
 * form and auth suites all build on these exact semantics — DRF pagination
 * (404 on page overflow), search/ordering/filters, expand validation and
 * expansion, multipart bodies, and the rotating-refresh JWT flow (D6).
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  authTestControls,
  mswDb,
  resetMswData,
  TEST_2FA_USER,
  TEST_EPHEMERAL_TOKEN,
  TEST_OTP,
  TEST_USER,
} from "./server";

const BASE = "http://karni.test";

interface Page {
  count: number;
  next: string | null;
  previous: string | null;
  results: Array<Record<string, unknown>>;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  expect(response.ok, `${path} should succeed, got ${response.status}`).toBe(true);
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown, headers?: Record<string, string>) {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  return { response, data: (await response.json().catch(() => undefined)) as T };
}

beforeEach(() => {
  resetMswData();
});

describe("events list", () => {
  it("serves the OpenAPI document at /api/schema/", async () => {
    const doc = await getJson<Record<string, unknown>>("/api/schema/");
    expect(doc["openapi"]).toBe("3.0.3");
    expect(doc["x-karni-auth-mode"]).toBe("jwt");
  });

  it("paginates with count/next/previous and a page_size cap", async () => {
    const page1 = await getJson<Page>("/api/events/?page_size=5");
    expect(page1.count).toBe(12);
    expect(page1.results).toHaveLength(5);
    expect(page1.previous).toBeNull();
    expect(page1.next).toContain("page=2");

    const page3 = await getJson<Page>("/api/events/?page_size=5&page=3");
    expect(page3.results).toHaveLength(2);
    expect(page3.next).toBeNull();
    expect(page3.previous).toContain("page=2");
  });

  it("404s on a page past the end (the D5 page-decrement scenario)", async () => {
    const response = await fetch(`${BASE}/api/events/?page_size=5&page=9`);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "Invalid page." });
  });

  it("searches title and description, case-insensitively", async () => {
    const page = await getJson<Page>("/api/events/?search=LAUNCH");
    expect(page.count).toBe(1);
    expect(page.results[0]?.["title"]).toBe("Launch Party");
  });

  it("orders by field with the - prefix, defaulting to -created_at", async () => {
    const titles = (await getJson<Page>("/api/events/?ordering=title&page_size=3")).results.map(
      (row) => row["title"],
    );
    expect(titles).toEqual(["API Workshop", "Annual Conference", "Community Picnic"]);

    const byDefault = await getJson<Page>("/api/events/?page_size=1");
    expect(byDefault.results[0]?.["id"]).toBe(12); // newest created_at first

    const descending = await getJson<Page>("/api/events/?ordering=-id&page_size=1");
    expect(descending.results[0]?.["id"]).toBe(12);
  });

  it("applies declared filters exactly", async () => {
    const published = await getJson<Page>("/api/events/?status=published");
    expect(published.count).toBeGreaterThan(0);
    expect(published.results.every((row) => row["status"] === "published")).toBe(true);

    const hidden = await getJson<Page>("/api/events/?is_public=false");
    expect(hidden.results.every((row) => row["is_public"] === false)).toBe(true);

    const atVenue = await getJson<Page>("/api/events/?venue=2");
    expect(atVenue.results.every((row) => row["venue"] === 2)).toBe(true);
  });

  it("never serializes the writeOnly internal_note", async () => {
    const page = await getJson<Page>("/api/events/");
    expect(page.results.every((row) => !("internal_note" in row))).toBe(true);
  });
});

describe("events expand (B9 semantics)", () => {
  it("expands organizer/venue/tags into objects, merging repeated and comma params", async () => {
    const event = await getJson<Record<string, unknown>>("/api/events/2/?expand=organizer,venue");
    expect(event["organizer"]).toMatchObject({ email: "ada@example.com" });
    expect(event["venue"]).toMatchObject({ name: expect.any(String) as unknown });

    const viaList = await getJson<Page>("/api/events/?expand=venue&expand=tags&search=Design");
    const row = viaList.results[0];
    expect(row?.["venue"]).toMatchObject({ id: expect.any(Number) as unknown });
    expect(Array.isArray(row?.["tags"])).toBe(true);
  });

  it("400s on an unknown expand key, listing the allowed keys", async () => {
    const response = await fetch(`${BASE}/api/events/?expand=bogus`);
    expect(response.status).toBe(400);
    const body = (await response.json()) as { expand: string[] };
    expect(body.expand[0]).toContain('"bogus"');
    expect(body.expand[0]).toContain("organizer, venue, tags");
  });
});

describe("events create/update", () => {
  it("creates from JSON with DRF-shaped validation errors", async () => {
    const bad = await postJson<Record<string, string[]>>("/api/events/", {});
    expect(bad.response.status).toBe(400);
    expect(bad.data).toEqual({
      title: ["This field is required."],
      starts_at: ["This field is required."],
    });

    const good = await postJson<Record<string, unknown>>("/api/events/", {
      title: "Created",
      starts_at: "2026-12-24T18:00:00Z",
      tags: [1, 2],
      metadata: { seats: [1, 2] },
    });
    expect(good.response.status).toBe(201);
    expect(good.data["tags"]).toEqual([1, 2]);
    expect(good.data["status"]).toBe("draft");
  });

  it("accepts multipart bodies per the D2 encoding rules", async () => {
    // Raw multipart payload: jsdom's FormData and Node's undici fetch cannot
    // serialize each other in this environment, but the wire format (which is
    // what the handler parses with request.formData()) is identical.
    const boundary = "----karni-test-boundary";
    const part = (headers: string, value: string): string =>
      `--${boundary}\r\n${headers}\r\n\r\n${value}`;
    const body = [
      part('Content-Disposition: form-data; name="title"', "Multipart Event"),
      part('Content-Disposition: form-data; name="starts_at"', "2026-12-01T10:00:00Z"),
      part('Content-Disposition: form-data; name="tags"', "1"),
      part('Content-Disposition: form-data; name="tags"', "3"),
      part('Content-Disposition: form-data; name="metadata"', '{"from":"form"}'),
      part(
        'Content-Disposition: form-data; name="poster"; filename="flyer.png"\r\nContent-Type: image/png',
        "img-bytes",
      ),
      `--${boundary}--`,
      "",
    ].join("\r\n");
    const response = await fetch(`${BASE}/api/events/`, {
      method: "POST",
      headers: { "content-type": `multipart/form-data; boundary=${boundary}` },
      body,
    });
    expect(response.status).toBe(201);
    const created = (await response.json()) as Record<string, unknown>;
    expect(created["tags"]).toEqual([1, 3]);
    expect(created["metadata"]).toEqual({ from: "form" });
    expect(created["poster"]).toBe("http://karni.test/media/events/flyer.png");
  });

  it("PATCHes only the provided fields and rejects blanked required ones", async () => {
    const patch = await fetch(`${BASE}/api/events/1/`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ capacity: null, title: "Renamed" }),
    });
    expect(patch.status).toBe(200);
    const updated = (await patch.json()) as Record<string, unknown>;
    expect(updated["title"]).toBe("Renamed");
    expect(updated["capacity"]).toBeNull();
    expect(updated["starts_at"]).toBe(mswDb.events[0]?.starts_at); // untouched

    const blanked = await fetch(`${BASE}/api/events/1/`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "" }),
    });
    expect(blanked.status).toBe(400);
  });

  it("deletes with 204 and then 404s", async () => {
    const del = await fetch(`${BASE}/api/events/1/`, { method: "DELETE" });
    expect(del.status).toBe(204);
    const gone = await fetch(`${BASE}/api/events/1/`);
    expect(gone.status).toBe(404);
  });
});

describe("read-only resources", () => {
  it("searches venues for ResourceSelect", async () => {
    const page = await getJson<Page>("/api/venues/?search=river");
    expect(page.count).toBe(1);
    expect(page.results[0]?.["name"]).toBe("Riverside Pavilion");
    const detail = await getJson<Record<string, unknown>>("/api/venues/2/");
    expect(detail["name"]).toBe("Riverside Pavilion");
  });
});

describe("auth flow (D6)", () => {
  it("logs in, serves /me with the Bearer token, and 401s without it", async () => {
    const login = await postJson<{ access: string; refresh: string }>("/api/auth/login/", {
      email: TEST_USER.email,
      password: TEST_USER.password,
    });
    expect(login.response.status).toBe(200);

    const me = await fetch(`${BASE}/api/auth/me/`, {
      headers: { authorization: `Bearer ${login.data.access}` },
    });
    expect(me.status).toBe(200);
    const user = (await me.json()) as Record<string, unknown>;
    expect(user["email"]).toBe(TEST_USER.email);
    expect(user["roles"]).toEqual(TEST_USER.roles); // A15: roles on /me

    const anonymous = await fetch(`${BASE}/api/auth/me/`);
    expect(anonymous.status).toBe(401);
  });

  it("rejects bad credentials with a DRF detail", async () => {
    const bad = await postJson<{ detail: string }>("/api/auth/login/", {
      email: TEST_USER.email,
      password: "wrong",
    });
    expect(bad.response.status).toBe(401);
    expect(bad.data.detail).toContain("No active account");
  });

  it("gates the 2FA user behind an ephemeral token exchange", async () => {
    const gate = await postJson<{ requires_2fa: boolean; ephemeral_token: string }>(
      "/api/auth/login/",
      { email: TEST_2FA_USER.email, password: TEST_2FA_USER.password },
    );
    expect(gate.data).toEqual({ requires_2fa: true, ephemeral_token: TEST_EPHEMERAL_TOKEN });

    const exchanged = await postJson<{ access: string }>("/api/auth/2fa/login/", {
      ephemeral_token: gate.data.ephemeral_token,
      otp: TEST_OTP,
    });
    expect(exchanged.response.status).toBe(200);
    expect(exchanged.data.access).toMatch(/^access-/);
  });

  it("rotates the refresh token and kills the old one", async () => {
    const login = await postJson<{ access: string; refresh: string }>("/api/auth/login/", {
      email: TEST_USER.email,
      password: TEST_USER.password,
    });

    const refreshed = await postJson<{ access: string; refresh: string }>("/api/auth/refresh/", {
      refresh: login.data.refresh,
    });
    expect(refreshed.response.status).toBe(200);
    expect(refreshed.data.refresh).not.toBe(login.data.refresh);

    const replayed = await postJson<{ code: string }>("/api/auth/refresh/", {
      refresh: login.data.refresh, // rotated away
    });
    expect(replayed.response.status).toBe(401);
    expect(replayed.data.code).toBe("token_not_valid");
  });

  it("lets suites stage expiry via authTestControls", async () => {
    const login = await postJson<{ access: string; refresh: string }>("/api/auth/login/", {
      email: TEST_USER.email,
      password: TEST_USER.password,
    });
    authTestControls.invalidateAccessTokens();
    const stale = await fetch(`${BASE}/api/auth/me/`, {
      headers: { authorization: `Bearer ${login.data.access}` },
    });
    expect(stale.status).toBe(401);
    expect(((await stale.json()) as { code: string }).code).toBe("token_not_valid");

    // The refresh token still works → the refresh path recovers the session.
    const recovered = await postJson<{ access: string }>("/api/auth/refresh/", {
      refresh: login.data.refresh,
    });
    expect(recovered.response.status).toBe(200);

    authTestControls.invalidateRefreshToken();
    const dead = await postJson<unknown>("/api/auth/refresh/", { refresh: recovered.data.access });
    expect(dead.response.status).toBe(401);
    expect(authTestControls.snapshot().currentRefreshToken).toBeNull();
  });
});
