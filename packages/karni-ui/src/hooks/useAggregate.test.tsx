/**
 * useAggregate (experimental): the request it builds, the cache key it uses and
 * the invalidation it shares with the resource, through the real KarniClient
 * against msw.
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
import {
  aggregateKey,
  buildAggregateQuery,
  useAggregate,
  type AggregateResult,
} from "./useAggregate";

const BASE = "http://karni.test/api";

const result: AggregateResult = {
  group_by: "region",
  metric: "sum",
  value: "price",
  split: null,
  stacked: false,
  top: null,
  categories: [{ key: "eu", label: "Europe", other: false }],
  series: [{ key: null, label: "Sum of price", values: [125] }],
};

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

describe("useAggregate", () => {
  it("sends the aggregate's parameters with the list's filters and search", async () => {
    const { wrapper } = setup();
    const seen: URL[] = [];
    server.use(
      http.get(`${BASE}/products/aggregate/`, ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json(result);
      }),
    );
    const { result: hook } = renderHook(
      () =>
        useAggregate("products", {
          groupBy: "launched_on:year",
          metric: "sum",
          value: "price",
          top: 5,
          stack: "channel",
          filters: { featured: true, channel: ["online", "store"], empty: null },
          search: "lamp",
        }),
      { wrapper },
    );
    await waitFor(() => expect(hook.current.isSuccess).toBe(true));
    expect(hook.current.data).toEqual(result);
    const url = seen[0];
    expect(url?.searchParams.get("group_by")).toBe("launched_on:year");
    expect(url?.searchParams.get("metric")).toBe("sum");
    expect(url?.searchParams.get("value")).toBe("price");
    expect(url?.searchParams.get("top")).toBe("5");
    expect(url?.searchParams.get("stack")).toBe("channel");
    expect(url?.searchParams.has("series")).toBe(false);
    expect(url?.searchParams.get("featured")).toBe("true");
    expect(url?.searchParams.getAll("channel")).toEqual(["online", "store"]);
    expect(url?.searchParams.get("search")).toBe("lamp");
    expect(url?.searchParams.has("empty")).toBe(false);
  });

  it("leaves out what is not set", () => {
    expect(buildAggregateQuery({ groupBy: "region" })).toEqual({ group_by: "region" });
    expect(buildAggregateQuery({ groupBy: "region", value: "", series: "channel" })).toEqual({
      group_by: "region",
      series: "channel",
    });
  });

  it("caches under the resource, so a mutation's invalidation refreshes it", () => {
    const key = aggregateKey("products", { groupBy: "region", metric: "count" });
    expect(key.slice(0, 2)).toEqual([...karniKeys.resource("products")]);
    expect(key[2]).toBe("aggregate");
    expect(aggregateKey("products", { metric: "count", groupBy: "region" })).toEqual(key);
  });

  it("surfaces the server's refusal with its code", async () => {
    const { wrapper } = setup();
    server.use(
      http.get(`${BASE}/products/aggregate/`, () =>
        HttpResponse.json(
          { code: "E382", detail: "group_by='name' is not declared" },
          { status: 400 },
        ),
      ),
    );
    const { result: hook } = renderHook(() => useAggregate("products", { groupBy: "name" }), {
      wrapper,
    });
    await waitFor(() => expect(hook.current.isError).toBe(true));
    expect(String(hook.current.error)).toContain("not declared");
  });
});
