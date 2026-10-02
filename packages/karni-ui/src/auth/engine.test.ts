/**
 * AuthEngine tests (contract "Hooks + auth" + D6), driven through the REAL
 * KarniClient against msw so the 401 → single-flight refresh → retry flow is
 * exercised end to end: persist-before-resolve, failure → anonymous, no
 * re-entrant refresh, session CSRF pins, and mode resolution.
 */
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { AuthEngine, normalizeUser, readAuthMode } from "./engine";
import { createMemoryTokenStorage } from "./storage";

const BASE = "http://karni.test/api";
const USER = { id: 1, email: "ada@example.com", roles: ["admin"] };

function makeEngine(options?: { mode?: "jwt" | "session"; readCachedSchema?: () => unknown }) {
  const client = createKarniClient({ baseUrl: BASE });
  const storage = createMemoryTokenStorage();
  const engine = new AuthEngine({
    client,
    tokenStorage: storage,
    ...(options?.mode !== undefined ? { modeOverride: options.mode } : {}),
    ...(options?.readCachedSchema !== undefined
      ? { readCachedSchema: options.readCachedSchema }
      : {}),
  });
  return { client, storage, engine };
}

function clearCookie(name: string): void {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

describe("AuthEngine bootstrap (jwt)", () => {
  it("restores a session: refresh with the stored token, rotate, fetch me", async () => {
    const { storage, engine } = makeEngine({ mode: "jwt" });
    storage.set("r1");
    const refreshLog: string[] = [];
    const bearers: Array<string | null> = [];
    server.use(
      http.post(`${BASE}/auth/refresh/`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        refreshLog.push(String(body.refresh));
        // The refresh request itself must not carry a (stale) Bearer header.
        expect(request.headers.get("authorization")).toBeNull();
        return HttpResponse.json({ access: "a1", refresh: "r2" });
      }),
      http.get(`${BASE}/auth/me/`, ({ request }) => {
        bearers.push(request.headers.get("authorization"));
        return HttpResponse.json(USER);
      }),
    );

    await engine.ensureInitialized();
    expect(refreshLog).toEqual(["r1"]);
    expect(storage.get()).toBe("r2");
    expect(bearers).toEqual(["Bearer a1"]);
    expect(engine.getSnapshot()).toMatchObject({
      status: "authenticated",
      mode: "jwt",
      user: { email: "ada@example.com", roles: ["admin"] },
    });
  });

  it("is anonymous without a stored refresh token (no network)", async () => {
    const { engine } = makeEngine({ mode: "jwt" });
    await engine.ensureInitialized();
    expect(engine.getSnapshot()).toMatchObject({ status: "anonymous", user: null });
  });
});

describe("AuthEngine 401 → refresh → retry (D6)", () => {
  it("shares ONE in-flight refresh and persists the rotated token before retries", async () => {
    const { client, storage, engine } = makeEngine({ mode: "jwt" });
    storage.set("r1");
    let refreshCalls = 0;
    const storageAtRetry: Array<string | null> = [];
    const protectedHandler = (name: string) =>
      http.get(`${BASE}/${name}/`, ({ request }) => {
        if (request.headers.get("authorization") === "Bearer a2") {
          // D6: by the time a queued retry runs, the rotation is persisted.
          storageAtRetry.push(storage.get());
          return HttpResponse.json({ ok: name });
        }
        return HttpResponse.json({ detail: "Token expired" }, { status: 401 });
      });
    server.use(
      http.post(`${BASE}/auth/refresh/`, async ({ request }) => {
        refreshCalls += 1;
        const body = (await request.json()) as Record<string, unknown>;
        if (refreshCalls === 1) {
          expect(body.refresh).toBe("r1");
          return HttpResponse.json({ access: "a1", refresh: "r2" });
        }
        expect(body.refresh).toBe("r2");
        await delay(50); // keep the refresh in flight while both 401s queue
        return HttpResponse.json({ access: "a2", refresh: "r3" });
      }),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
      protectedHandler("events"),
      protectedHandler("widgets"),
    );

    await engine.ensureInitialized();
    const [events, widgets] = await Promise.all([
      client.request<{ ok: string }>("/events/"),
      client.request<{ ok: string }>("/widgets/"),
    ]);

    expect(events.ok).toBe("events");
    expect(widgets.ok).toBe("widgets");
    expect(refreshCalls).toBe(2); // one bootstrap + ONE shared race refresh
    expect(storage.get()).toBe("r3");
    expect(storageAtRetry).toEqual(["r3", "r3"]);
  });

  it("clears storage and goes anonymous when the refresh fails; the 401 surfaces", async () => {
    const { client, storage, engine } = makeEngine({ mode: "jwt" });
    storage.set("r1");
    let refreshCalls = 0;
    server.use(
      http.post(`${BASE}/auth/refresh/`, () => {
        refreshCalls += 1;
        if (refreshCalls === 1) return HttpResponse.json({ access: "a1", refresh: "r2" });
        return HttpResponse.json({ detail: "Token is blacklisted" }, { status: 401 });
      }),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
      http.get(`${BASE}/events/`, () =>
        HttpResponse.json({ detail: "Token expired" }, { status: 401 }),
      ),
    );

    await engine.ensureInitialized();
    await expect(client.request("/events/")).rejects.toMatchObject({ status: 401 });
    expect(refreshCalls).toBe(2);
    expect(storage.get()).toBeNull();
    expect(engine.getSnapshot()).toMatchObject({ status: "anonymous", user: null });
  });

  it("surfaces a 401 that follows a successful refresh — never re-triggers refresh", async () => {
    const { client, storage, engine } = makeEngine({ mode: "jwt" });
    storage.set("r1");
    let refreshCalls = 0;
    server.use(
      http.post(`${BASE}/auth/refresh/`, () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access: refreshCalls === 1 ? "a1" : "a2",
          refresh: refreshCalls === 1 ? "r2" : "r3",
        });
      }),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
      // Permanently 401s, whatever the token: the retry must surface, not loop.
      http.get(`${BASE}/events/`, () => HttpResponse.json({ detail: "Nope" }, { status: 401 })),
    );

    await engine.ensureInitialized();
    await expect(client.request("/events/")).rejects.toMatchObject({ status: 401 });
    expect(refreshCalls).toBe(2); // bootstrap + exactly one refresh for the 401
    // The refresh itself succeeded, so the session survives the surfaced 401.
    expect(engine.getSnapshot().status).toBe("authenticated");
  });

  it("surfaces 401s directly when anonymous (no refresh token, no refresh call)", async () => {
    const { client, engine } = makeEngine({ mode: "jwt" });
    server.use(
      http.get(`${BASE}/events/`, () =>
        HttpResponse.json({ detail: "Auth required" }, { status: 401 }),
      ),
    );
    await engine.ensureInitialized();
    // No /auth/refresh/ handler exists: a refresh attempt would fail the test
    // via onUnhandledRequest: "error".
    await expect(client.request("/events/")).rejects.toMatchObject({ status: 401 });
  });
});

describe("AuthEngine login/logout (jwt)", () => {
  it("logs in, persists tokens, fetches me, and mirrors authenticated state", async () => {
    const { storage, engine } = makeEngine({ mode: "jwt" });
    const loginBodies: unknown[] = [];
    server.use(
      http.post(`${BASE}/auth/login/`, async ({ request }) => {
        loginBodies.push(await request.json());
        return HttpResponse.json({ access: "a1", refresh: "r1" });
      }),
      http.get(`${BASE}/auth/me/`, ({ request }) => {
        expect(request.headers.get("authorization")).toBe("Bearer a1");
        return HttpResponse.json(USER);
      }),
    );

    const result = await engine.login("ada@example.com", "pw");
    expect(loginBodies).toEqual([{ email: "ada@example.com", password: "pw" }]);
    expect(result).toEqual({ ok: true, user: USER });
    expect(storage.get()).toBe("r1");
    expect(engine.getSnapshot().status).toBe("authenticated");
  });

  it("resolves the 2FA variant without touching tokens or state", async () => {
    const { storage, engine } = makeEngine({ mode: "jwt" });
    server.use(
      http.post(`${BASE}/auth/login/`, () =>
        HttpResponse.json({ requires_2fa: true, ephemeral_token: "et-1" }),
      ),
    );
    const result = await engine.login("ada@example.com", "pw");
    expect(result).toEqual({ requires2fa: true, ephemeralToken: "et-1" });
    expect(storage.get()).toBeNull();
    expect(engine.getSnapshot().status).toBe("anonymous");
  });

  it("throws a descriptive mismatch error on an unexpected login payload", async () => {
    const { engine } = makeEngine({ mode: "jwt" });
    server.use(http.post(`${BASE}/auth/login/`, () => HttpResponse.json({ token: "x" })));
    await expect(engine.login("ada@example.com", "pw")).rejects.toThrow(
      /unexpected response .* \{ access, refresh \}/,
    );
  });

  it("passes DRF login failures through (status + data)", async () => {
    const { engine } = makeEngine({ mode: "jwt" });
    server.use(
      http.post(`${BASE}/auth/login/`, () =>
        HttpResponse.json({ detail: "No active account" }, { status: 401 }),
      ),
    );
    await expect(engine.login("ada@example.com", "bad")).rejects.toMatchObject({
      status: 401,
      data: { detail: "No active account" },
    });
  });

  it("logs out: blacklists the refresh token server-side, then clears locally", async () => {
    const { storage, engine } = makeEngine({ mode: "jwt" });
    const logoutBodies: unknown[] = [];
    server.use(
      http.post(`${BASE}/auth/login/`, () => HttpResponse.json({ access: "a1", refresh: "r1" })),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
      http.post(`${BASE}/auth/logout/`, async ({ request }) => {
        logoutBodies.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await engine.login("ada@example.com", "pw");
    await engine.logout();
    expect(logoutBodies).toEqual([{ refresh: "r1" }]);
    expect(storage.get()).toBeNull();
    expect(engine.getSnapshot()).toMatchObject({ status: "anonymous", user: null });
  });
});

describe("AuthEngine session mode (A4 pins)", () => {
  it("sends the CSRF cookie value in the X-CSRFToken header on unsafe requests", async () => {
    document.cookie = "csrftoken=tok123; path=/";
    try {
      const { client, engine } = makeEngine({ mode: "session" });
      const csrfHeaders: Array<string | null> = [];
      server.use(
        http.get(`${BASE}/auth/me/`, ({ request }) => {
          expect(request.headers.get("authorization")).toBeNull();
          return HttpResponse.json(USER);
        }),
        http.post(`${BASE}/events/`, ({ request }) => {
          csrfHeaders.push(request.headers.get("x-csrftoken"));
          return HttpResponse.json({ id: 1 }, { status: 201 });
        }),
      );
      await engine.ensureInitialized();
      expect(engine.getSnapshot()).toMatchObject({ status: "authenticated", mode: "session" });
      await client.request("/events/", { method: "POST", body: { title: "x" } });
      expect(csrfHeaders).toEqual(["tok123"]);
    } finally {
      clearCookie("csrftoken");
    }
  });

  it("bootstraps the CSRF cookie via GET /auth/csrf/ when absent, then logs in", async () => {
    clearCookie("csrftoken");
    try {
      const { engine } = makeEngine({ mode: "session" });
      let csrfCalls = 0;
      server.use(
        http.get(`${BASE}/auth/csrf/`, () => {
          csrfCalls += 1;
          document.cookie = "csrftoken=boot; path=/"; // what ensure_csrf_cookie does
          return new HttpResponse(null, { status: 204 });
        }),
        http.get(`${BASE}/auth/me/`, () =>
          HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
        ),
        http.post(`${BASE}/auth/login/`, ({ request }) => {
          expect(request.headers.get("x-csrftoken")).toBe("boot");
          return HttpResponse.json(USER);
        }),
      );
      await engine.ensureInitialized();
      expect(engine.getSnapshot().status).toBe("anonymous");
      expect(csrfCalls).toBe(1);

      const result = await engine.login("ada@example.com", "pw");
      expect(result).toEqual({ ok: true, user: USER });
      expect(engine.getSnapshot().status).toBe("authenticated");
    } finally {
      clearCookie("csrftoken");
    }
  });

  it("flips to anonymous when a session request 401s (session evaporated)", async () => {
    document.cookie = "csrftoken=tok123; path=/";
    try {
      const { client, engine } = makeEngine({ mode: "session" });
      let authenticatedOnce = false;
      server.use(
        http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
        http.get(`${BASE}/events/`, () =>
          HttpResponse.json({ detail: "Session expired" }, { status: 401 }),
        ),
      );
      await engine.ensureInitialized();
      authenticatedOnce = engine.getSnapshot().status === "authenticated";
      await expect(client.request("/events/")).rejects.toMatchObject({ status: 401 });
      expect(authenticatedOnce).toBe(true);
      expect(engine.getSnapshot().status).toBe("anonymous");
    } finally {
      clearCookie("csrftoken");
    }
  });
});

describe("AuthEngine mode resolution", () => {
  it("prefers the cached parsed schema's authMode (no schema fetch)", async () => {
    document.cookie = "csrftoken=cached; path=/";
    try {
      const { engine } = makeEngine({ readCachedSchema: () => ({ authMode: "session" }) });
      server.use(
        http.get(`${BASE}/auth/me/`, () =>
          HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
        ),
      );
      // No /schema/ handler: fetching it would fail via onUnhandledRequest.
      await engine.ensureInitialized();
      expect(engine.getSnapshot().mode).toBe("session");
    } finally {
      clearCookie("csrftoken");
    }
  });

  it("falls back to the schema document's root x-karni-auth-mode", async () => {
    clearCookie("csrftoken");
    const { engine } = makeEngine();
    server.use(
      http.get(`${BASE}/schema/`, () =>
        HttpResponse.json({ openapi: "3.0.3", "x-karni-auth-mode": "session" }),
      ),
      http.get(`${BASE}/auth/csrf/`, () => new HttpResponse(null, { status: 204 })),
      http.get(`${BASE}/auth/me/`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
      ),
    );
    await engine.ensureInitialized();
    expect(engine.getSnapshot().mode).toBe("session");
  });

  it("defaults to jwt when the schema cannot be fetched", async () => {
    const { engine } = makeEngine();
    server.use(
      http.get(`${BASE}/schema/`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    );
    await engine.ensureInitialized();
    expect(engine.getSnapshot()).toMatchObject({ mode: "jwt", status: "anonymous" });
  });
});

describe("AuthEngine.refresh() (public)", () => {
  it("rotates tokens and re-syncs the user in jwt mode", async () => {
    const { storage, engine } = makeEngine({ mode: "jwt" });
    storage.set("r1");
    let refreshCalls = 0;
    server.use(
      http.post(`${BASE}/auth/refresh/`, () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access: `a${refreshCalls}`,
          refresh: `r${refreshCalls + 1}`,
        });
      }),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
    );
    await engine.ensureInitialized();
    await engine.refresh();
    expect(refreshCalls).toBe(2);
    expect(storage.get()).toBe("r3");
    expect(engine.getSnapshot().status).toBe("authenticated");
  });

  it("only re-fetches /me/ in session mode (A3: /refresh/ is 405 there)", async () => {
    document.cookie = "csrftoken=tok; path=/";
    try {
      const { engine } = makeEngine({ mode: "session" });
      let meCalls = 0;
      server.use(
        http.get(`${BASE}/auth/me/`, () => {
          meCalls += 1;
          return HttpResponse.json(USER);
        }),
      );
      await engine.ensureInitialized();
      await engine.refresh(); // a POST /auth/refresh/ would be unhandled → error
      expect(meCalls).toBe(2);
    } finally {
      clearCookie("csrftoken");
    }
  });
});

describe("normalizeUser / readAuthMode guards", () => {
  it("normalizes valid users and defaults roles to []", () => {
    expect(normalizeUser({ id: 1, email: "a@b.c" })).toEqual({ id: 1, email: "a@b.c", roles: [] });
    expect(normalizeUser({ id: "u", email: "a@b.c", roles: ["x", 1] })).toEqual({
      id: "u",
      email: "a@b.c",
      roles: ["x"],
    });
    expect(normalizeUser({ email: "a@b.c" })).toBeNull();
    expect(normalizeUser("nope")).toBeNull();
  });

  it("reads both ParsedSchema.authMode and raw x-karni-auth-mode", () => {
    expect(readAuthMode({ authMode: "session" })).toBe("session");
    expect(readAuthMode({ "x-karni-auth-mode": "jwt" })).toBe("jwt");
    expect(readAuthMode({ "x-karni-auth-mode": "weird" })).toBeUndefined();
    expect(readAuthMode(null)).toBeUndefined();
  });
});
