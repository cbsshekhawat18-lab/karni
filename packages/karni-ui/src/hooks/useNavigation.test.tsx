/** useNavigation (experimental): the menu from GET /navigation/, cached per signed-in user. */
import { QueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../auth/provider";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { karniKeys } from "./keys";
import { useNavigation, type NavigationMenu } from "./useNavigation";

const BASE = "http://karni.test/api";
const MENU: NavigationMenu = {
  items: [{ label: "Home", icon: "home", route: "/", children: [] }],
};

function setup(auth: AuthContextValue | null = null) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
    </KarniProvider>
  );
  return { queryClient, wrapper };
}

function auth(status: AuthContextValue["status"], id: string | null): AuthContextValue {
  return {
    status,
    user: id === null ? null : { id, email: `${id}@example.com`, roles: [] },
  } as unknown as AuthContextValue;
}

describe("useNavigation", () => {
  it("reads GET /navigation/ and caches it per user", async () => {
    let calls = 0;
    server.use(
      http.get(`${BASE}/navigation/`, () => {
        calls += 1;
        return HttpResponse.json(MENU);
      }),
    );
    const { queryClient, wrapper } = setup(auth("authenticated", "u1"));
    const { result } = renderHook(() => useNavigation(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(MENU);
    expect(calls).toBe(1);
    expect(queryClient.getQueryData(karniKeys.navigation("u1"))).toEqual(MENU);
    expect(queryClient.getQueryData(karniKeys.navigation(null))).toBeUndefined();
  });

  it("waits while the session is loading, and keys a visitor with no user", async () => {
    server.use(http.get(`${BASE}/navigation/`, () => HttpResponse.json(MENU)));
    const loading = setup(auth("loading", null));
    const waiting = renderHook(() => useNavigation(), { wrapper: loading.wrapper });
    expect(waiting.result.current.fetchStatus).toBe("idle");
    const visitor = setup(auth("anonymous", null));
    const { result } = renderHook(() => useNavigation(), { wrapper: visitor.wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(visitor.queryClient.getQueryData(karniKeys.navigation(null))).toEqual(MENU);
  });

  it("works outside AuthProvider", async () => {
    server.use(http.get(`${BASE}/navigation/`, () => HttpResponse.json(MENU)));
    const { wrapper } = setup(null);
    const { result } = renderHook(() => useNavigation(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(MENU));
  });

  it("keys differ by user", () => {
    expect(karniKeys.navigation(1)).toEqual(["karni", "$navigation", "1"]);
    expect(karniKeys.navigation()).toEqual(["karni", "$navigation", null]);
  });
});
