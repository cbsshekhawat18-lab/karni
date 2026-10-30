import { QueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { useResourceCounts } from "./useResourceCounts";

function Wrapper({ children }: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: "http://localhost/api" }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      {children}
    </KarniProvider>
  );
}

describe("useResourceCounts", () => {
  it("counts each resource with one page_size=1 request, as chart points", async () => {
    const asked: string[] = [];
    server.events.on("request:start", ({ request }) => asked.push(request.url));
    const { result } = renderHook(
      () =>
        useResourceCounts([
          "events",
          { resource: "events", label: "Published", filters: { status: "published" } },
          "venues",
        ]),
      { wrapper: Wrapper },
    );
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual([
      { resource: "events", label: "Events", value: 12 },
      { resource: "events", label: "Published", value: 6 },
      { resource: "venues", label: "Venues", value: 3 },
    ]);
    expect(result.current.error).toBeNull();
    expect(asked.every((url) => new URL(url).searchParams.get("page_size") === "1")).toBe(true);
    server.events.removeAllListeners();
  });

  it("leaves out a resource the user may not list, and reports other failures", async () => {
    server.use(
      http.get("*/api/tags/", () => HttpResponse.json({ detail: "No." }, { status: 403 })),
      http.get("*/api/users/", () => HttpResponse.json({ detail: "Boom" }, { status: 500 })),
    );
    const { result } = renderHook(() => useResourceCounts(["tags", "venues", "users"]), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data.map((point) => point.resource)).toEqual(["venues"]);
    expect(result.current.error).toMatchObject({ status: 500 });
  });
});
