/**
 * useGlobalSearch (experimental) against the msw backend's GET /api/search/:
 * the query it sends, the short-query rule, the key and the typed result.
 */
import { QueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { karniKeys } from "./keys";
import { globalSearchQuery, useGlobalSearch, type GlobalSearchResult } from "./useGlobalSearch";

const BASE = "http://karni.test/api";

function setup() {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  return { queryClient, wrapper };
}

describe("useGlobalSearch", () => {
  it("asks GET /search/ and returns the groups, best first", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useGlobalSearch({ q: " hall " }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const data = result.current.data as GlobalSearchResult;
    expect(data.query).toBe("hall");
    expect(data.groups.map((group) => group.resource)).toEqual(["venues", "events"]);
    expect(data.groups[0]?.hits[0]).toEqual({
      resource: "venues",
      id: 1,
      title: "Grand Hall",
      subtitle: "Jaipur",
      score: 1,
    });
  });

  it("sends models comma-joined and the limit", async () => {
    const { wrapper } = setup();
    const seen: URL[] = [];
    server.use(
      http.get(`${BASE}/search/`, ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json({ query: "x", groups: [] });
      }),
    );
    const { result } = renderHook(
      () =>
        useGlobalSearch<"events" | "venues">({ q: "hall", models: ["venues", "events"], limit: 3 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toHaveLength(1);
    expect(seen[0]?.searchParams.get("q")).toBe("hall");
    expect(seen[0]?.searchParams.get("models")).toBe("venues,events");
    expect(seen[0]?.searchParams.get("limit")).toBe("3");
  });

  it("sends nothing for a query shorter than minLength", async () => {
    const { wrapper } = setup();
    let calls = 0;
    server.use(
      http.get(`${BASE}/search/`, () => {
        calls += 1;
        return HttpResponse.json({ query: "", groups: [] });
      }),
    );
    const { result, rerender } = renderHook(
      ({ q }: { q: string }) => useGlobalSearch({ q }, { minLength: 3 }),
      { wrapper, initialProps: { q: "ha" } },
    );
    expect(result.current.fetchStatus).toBe("idle");
    rerender({ q: "hal" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls).toBe(1);
  });

  it("passes the server's refusal on as the error", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useGlobalSearch({ q: "hall", models: ["rooms"] }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as { data?: { code?: string } }).data?.code).toBe("E431");
  });

  it("keys each search under karni.$search, whatever the order of its params", () => {
    expect(karniKeys.search(globalSearchQuery({ q: "a", limit: 2 }))).toEqual(
      karniKeys.search({ limit: "2", q: "a" }),
    );
    expect(karniKeys.search({ q: "a" })[1]).toBe("$search");
    expect(globalSearchQuery({ q: " a ", models: [] })).toEqual({ q: "a" });
  });
});
