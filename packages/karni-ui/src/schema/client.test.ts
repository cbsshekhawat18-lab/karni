/**
 * createKarniClient suite (contract "Schema client" + D6): URL joining, query
 * serialization, JSON/multipart bodies, Bearer injection, DRF error
 * passthrough, and the 401 → onUnauthorized → single-retry contract the auth
 * layer builds its refresh machinery on.
 */
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mswDb, resetMswData, server } from "../../tests/msw/server";
import { createKarniClient, KarniApiError } from "./client";
import type { Paginated } from "../hooks/types";

const BASE = "http://karni.test";

interface EventPayload {
  id: number;
  title: string;
  [key: string]: unknown;
}

beforeEach(() => {
  resetMswData();
});

/** Awaits a rejection and asserts + returns it as KarniApiError. */
async function captureError(promise: Promise<unknown>): Promise<KarniApiError> {
  try {
    await promise;
  } catch (caught) {
    expect(caught).toBeInstanceOf(KarniApiError);
    return caught as KarniApiError;
  }
  throw new Error("expected the request to reject");
}

describe("createKarniClient — URLs and queries", () => {
  it("joins baseUrl and path, and defaults schemaUrl", () => {
    const client = createKarniClient({ baseUrl: BASE });
    expect(client.baseUrl).toBe(BASE);
    expect(client.schemaUrl).toBe("/api/schema/");
  });

  it("does not double a base path the request path already carries", async () => {
    const seen: string[] = [];
    server.use(
      http.get("http://karni.test/api/events/", ({ request }) => {
        seen.push(new URL(request.url).pathname);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );
    await createKarniClient({ baseUrl: `${BASE}/api` }).request("/api/events/");
    await createKarniClient({ baseUrl: BASE }).request("/api/events/");
    await createKarniClient({ baseUrl: `${BASE}/api/` }).request("events/");
    expect(seen).toEqual(["/api/events/", "/api/events/", "/api/events/"]);
  });

  it("serializes query params, arrays as repeated keys, dropping null/undefined", async () => {
    let search = "";
    server.use(
      http.get(`${BASE}/api/echo/`, ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json({});
      }),
    );
    const client = createKarniClient({ baseUrl: BASE });
    await client.request("/api/echo/", {
      query: { page: 2, expand: ["organizer", "venue"], search: "x y", gone: null, off: undefined },
    });
    expect(search).toBe("?page=2&expand=organizer&expand=venue&search=x+y");
  });
});

describe("createKarniClient — bodies and responses", () => {
  it("performs JSON CRUD against the simulated backend", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const page = await client.request<Paginated<EventPayload>>("/api/events/", {
      query: { page_size: 5 },
    });
    expect(page.count).toBe(mswDb.events.length);
    expect(page.results).toHaveLength(5);

    const created = await client.request<EventPayload>("/api/events/", {
      method: "POST",
      body: { title: "From client", starts_at: "2026-12-01T10:00:00Z" },
    });
    expect(created.title).toBe("From client");
    expect(mswDb.events.some((event) => event.id === created.id)).toBe(true);

    const removed = await client.request<undefined>(`/api/events/${created.id}/`, {
      method: "DELETE",
    });
    expect(removed).toBeUndefined(); // 204 → undefined
  });

  it("passes FormData through untouched, without a manual Content-Type (D2)", async () => {
    // Asserted against a stub fetch: jsdom's FormData/File and Node's undici
    // fetch cannot serialize each other, so a real round-trip would hang in
    // this environment. The boundary header is the runtime's job — the
    // client's contract is "do not JSON-encode, do not set Content-Type".
    let seenBody: unknown;
    let seenHeaders: Headers | undefined;
    const stubFetch: typeof globalThis.fetch = async (_input, init) => {
      seenBody = init?.body;
      seenHeaders = new Headers(init?.headers);
      return new Response(JSON.stringify({ ok: true }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    };
    const form = new FormData();
    form.append("title", "Multipart");
    form.append("poster", new File(["img"], "poster.png", { type: "image/png" }));
    const client = createKarniClient({ baseUrl: BASE, fetch: stubFetch });
    expect(await client.request("/api/upload/", { method: "POST", body: form })).toEqual({
      ok: true,
    });
    expect(seenBody).toBe(form); // the exact instance, not a JSON string
    expect(seenHeaders?.has("content-type")).toBe(false);

    // A JSON body on the same client DOES get the content type.
    await client.request("/api/upload/", { method: "POST", body: { a: 1 } });
    expect(seenBody).toBe(JSON.stringify({ a: 1 }));
    expect(seenHeaders?.get("content-type")).toBe("application/json");
  });

  it("throws KarniApiError carrying the DRF error body verbatim", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const error = await captureError(
      client.request("/api/events/", { method: "POST", body: { title: "" } }),
    );
    expect(error.status).toBe(400);
    expect(error.data).toEqual({
      title: ["This field may not be blank."],
      starts_at: ["This field is required."],
    });
  });

  it("uses the DRF detail as the error message when present", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const error = await captureError(client.request("/api/events/999/"));
    expect(error.status).toBe(404);
    expect(error.message).toBe("No Event matches the given query.");
  });
});

describe("createKarniClient — auth hook points (D6)", () => {
  function protectedEndpoint(validTokens: readonly string[]): void {
    server.use(
      http.get(`${BASE}/api/protected/`, ({ request }) => {
        const token = request.headers.get("authorization")?.replace("Bearer ", "") ?? "";
        if (!validTokens.includes(token)) {
          return HttpResponse.json({ detail: "token expired" }, { status: 401 });
        }
        return HttpResponse.json({ token });
      }),
    );
  }

  it("injects the Bearer token from getAccessToken on every request", async () => {
    protectedEndpoint(["t-1"]);
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => "t-1" });
    expect(await client.request("/api/protected/")).toEqual({ token: "t-1" });
  });

  it("sends no Authorization header when the getter returns null", async () => {
    let header: string | null = "sentinel";
    server.use(
      http.get(`${BASE}/api/open/`, ({ request }) => {
        header = request.headers.get("authorization");
        return HttpResponse.json({});
      }),
    );
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => null });
    await client.request("/api/open/");
    expect(header).toBeNull();
  });

  it("merges getHeaders output (session-mode CSRF) under per-request headers", async () => {
    const seen: Record<string, string | null> = {};
    server.use(
      http.post(`${BASE}/api/csrf-check/`, ({ request }) => {
        seen["csrf"] = request.headers.get("x-csrftoken");
        seen["custom"] = request.headers.get("x-custom");
        return HttpResponse.json({});
      }),
    );
    const client = createKarniClient({ baseUrl: BASE });
    client.setAuthHooks({ getHeaders: () => ({ "X-CSRFToken": "csrf-1", "X-Custom": "hook" }) });
    await client.request("/api/csrf-check/", {
      method: "POST",
      body: {},
      headers: { "X-Custom": "request-wins" },
    });
    expect(seen).toEqual({ csrf: "csrf-1", custom: "request-wins" });
  });

  it("on 401 calls onUnauthorized once and retries once with fresh credentials", async () => {
    protectedEndpoint(["t-2"]);
    let token = "t-1-stale";
    const onUnauthorized = vi.fn(async (error: KarniApiError) => {
      expect(error.status).toBe(401);
      token = "t-2"; // "refresh" succeeded
      return true;
    });
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => token });
    client.setAuthHooks({ onUnauthorized });
    expect(await client.request("/api/protected/")).toEqual({ token: "t-2" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("surfaces the error without retrying when onUnauthorized returns false", async () => {
    protectedEndpoint(["anything-valid"]);
    const onUnauthorized = vi.fn(async () => false);
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => "stale" });
    client.setAuthHooks({ onUnauthorized });
    const error = await captureError(client.request("/api/protected/"));
    expect(error.status).toBe(401);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 401 on the retried request instead of refreshing again (D6)", async () => {
    protectedEndpoint([]); // nothing is ever valid
    const onUnauthorized = vi.fn(async () => true);
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => "always-stale" });
    client.setAuthHooks({ onUnauthorized });
    const error = await captureError(client.request("/api/protected/"));
    expect(error.status).toBe(401);
    expect(onUnauthorized).toHaveBeenCalledTimes(1); // never re-triggered
  });

  it("skips the 401 cycle entirely for skipAuthRefresh requests", async () => {
    protectedEndpoint([]);
    const onUnauthorized = vi.fn(async () => true);
    const client = createKarniClient({ baseUrl: BASE });
    client.setAuthHooks({ onUnauthorized });
    await expect(
      client.request("/api/protected/", { skipAuthRefresh: true }),
    ).rejects.toBeInstanceOf(KarniApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("lets setAuthHooks replace and clear individual hooks", async () => {
    protectedEndpoint(["from-hooks"]);
    const client = createKarniClient({ baseUrl: BASE, getAccessToken: () => "initial" });
    client.setAuthHooks({ getAccessToken: () => "from-hooks" });
    expect(await client.request("/api/protected/")).toEqual({ token: "from-hooks" });
    client.setAuthHooks({ getAccessToken: undefined }); // explicit undefined clears
    await expect(client.request("/api/protected/")).rejects.toMatchObject({ status: 401 });
  });

  it("uses a custom fetch implementation when given", async () => {
    const customFetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ via: "custom" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createKarniClient({ baseUrl: BASE, fetch: customFetch });
    expect(await client.request("/api/anything/")).toEqual({ via: "custom" });
    expect(customFetch).toHaveBeenCalledTimes(1);
  });
});
