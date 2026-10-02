/**
 * <AuthProvider> / useAuth / usePermission tests: React state mirroring over
 * the auth engine, through the real KarniProvider + client against msw.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthProvider, useAuth } from "./provider";
import { createMemoryTokenStorage, type TokenStorage } from "./storage";
import { usePermission } from "./usePermission";

const BASE = "http://karni.test/api";
const USER = { id: 1, email: "ada@example.com", roles: ["admin"] };

function setup(options?: { storage?: TokenStorage }) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const storage = options?.storage ?? createMemoryTokenStorage();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={storage}>
        {children}
      </AuthProvider>
    </KarniProvider>
  );
  return { client, queryClient, storage, wrapper };
}

describe("AuthProvider + useAuth", () => {
  it("resolves anonymous without a stored token (no loading flash)", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useAuth(), { wrapper });
    // "loading" covers the initial session RESTORE only (src/auth/types.ts);
    // with the mode pinned and the storage empty there is nothing to restore,
    // so the mount effect resolves "anonymous" synchronously — no flash.
    expect(result.current.status).toBe("anonymous");
    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    expect(result.current.user).toBeNull();
    expect(result.current.roles).toEqual([]);
  });

  it("restores an existing session from the token storage", async () => {
    const storage = createMemoryTokenStorage();
    storage.set("r1");
    server.use(
      http.post(`${BASE}/auth/refresh/`, () => HttpResponse.json({ access: "a1", refresh: "r2" })),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
    );
    const { wrapper } = setup({ storage });
    const { result } = renderHook(() => useAuth(), { wrapper });
    // A stored token means an actual async restore — THIS is the loading tick.
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.user?.email).toBe("ada@example.com");
    expect(result.current.roles).toEqual(["admin"]);
  });

  it("mirrors login and logout into React state", async () => {
    server.use(
      http.post(`${BASE}/auth/login/`, () => HttpResponse.json({ access: "a1", refresh: "r1" })),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
      http.post(`${BASE}/auth/logout/`, () => new HttpResponse(null, { status: 204 })),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));

    await act(async () => {
      const login = await result.current.login("ada@example.com", "pw");
      expect(login).toEqual({ ok: true, user: USER });
    });
    expect(result.current.status).toBe("authenticated");
    expect(result.current.user?.id).toBe(1);

    await act(async () => {
      await result.current.logout();
    });
    expect(result.current.status).toBe("anonymous");
    expect(result.current.user).toBeNull();
  });

  it("throws a descriptive error outside <AuthProvider>", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      expect(() => renderHook(() => useAuth())).toThrow(/within an <AuthProvider>/);
    } finally {
      spy.mockRestore();
    }
  });
});

describe("usePermission", () => {
  it("exposes hasRole / isAuthenticated over the user's roles", async () => {
    server.use(
      http.post(`${BASE}/auth/login/`, () => HttpResponse.json({ access: "a1", refresh: "r1" })),
      http.get(`${BASE}/auth/me/`, () => HttpResponse.json(USER)),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ auth: useAuth(), perm: usePermission() }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.auth.status).toBe("anonymous"));
    expect(result.current.perm.isAuthenticated).toBe(false);
    expect(result.current.perm.hasRole("admin")).toBe(false);

    await act(async () => {
      await result.current.auth.login("ada@example.com", "pw");
    });
    expect(result.current.perm.isAuthenticated).toBe(true);
    expect(result.current.perm.hasRole("admin")).toBe(true);
    expect(result.current.perm.hasRole("editor", "admin")).toBe(true); // any-of
    expect(result.current.perm.hasRole("editor")).toBe(false);
    expect(result.current.perm.hasRole()).toBe(false); // "at least one of" nothing
  });
});
