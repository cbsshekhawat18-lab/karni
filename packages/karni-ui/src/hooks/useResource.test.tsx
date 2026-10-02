/**
 * useResourceList / useResourceItem / useResourceMutations integration tests
 * (contract "Hooks" + D4/D11): request shapes, DRF page passthrough, and
 * invalidation discipline — through the real KarniClient against msw.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { karniKeys } from "./keys";
import type { Paginated } from "./types";
import { useResourceItem } from "./useResourceItem";
import { useResourceList } from "./useResourceList";
import { useResourceMutations } from "./useResourceMutations";

const BASE = "http://karni.test/api";

interface EventRow {
  id: number;
  title: string;
  [extra: string]: unknown;
}

function page(results: EventRow[]): Paginated<EventRow> {
  return { count: results.length, next: null, previous: null, results };
}

function setup() {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  return { client, queryClient, wrapper };
}

describe("useResourceList", () => {
  it("fetches the DRF page with the full query-param mapping", async () => {
    const { wrapper } = setup();
    const seen: URL[] = [];
    server.use(
      http.get(`${BASE}/events/`, ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json(page([{ id: 1, title: "PyCon" }]));
      }),
    );

    const { result } = renderHook(
      () =>
        useResourceList<EventRow>("events", {
          page: 2,
          pageSize: 10,
          ordering: "-starts_at",
          search: "conf",
          expand: ["venue", "organizer"],
          filters: { status: "published", tag: ["a", "b"] },
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.results[0]?.title).toBe("PyCon");
    expect(result.current.data?.count).toBe(1);

    const params = seen[0]?.searchParams;
    expect(params?.get("page")).toBe("2");
    expect(params?.get("page_size")).toBe("10");
    expect(params?.get("ordering")).toBe("-starts_at");
    expect(params?.get("search")).toBe("conf");
    expect(params?.get("expand")).toBe("venue,organizer");
    expect(params?.get("status")).toBe("published");
    expect(params?.getAll("tag")).toEqual(["a", "b"]); // arrays → repeated keys
  });

  it("caches under karniKeys.list so manual cache work lines up", async () => {
    const { queryClient, wrapper } = setup();
    server.use(http.get(`${BASE}/events/`, () => HttpResponse.json(page([]))));

    const params = { search: "x" };
    const { result } = renderHook(() => useResourceList("events", params), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(karniKeys.list("events", params))).toBeDefined();
  });

  it("surfaces DRF errors through the query error state", async () => {
    const { wrapper } = setup();
    server.use(
      http.get(`${BASE}/events/`, () =>
        HttpResponse.json({ detail: "Server exploded" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useResourceList("events"), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 500 });
  });
});

describe("useResourceItem", () => {
  it("fetches the detail path with expand and a stringified id", async () => {
    const { wrapper } = setup();
    const seen: URL[] = [];
    server.use(
      http.get(`${BASE}/events/5/`, ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json({ id: 5, title: "DjangoCon" });
      }),
    );

    const { result } = renderHook(
      () => useResourceItem<EventRow>("events", 5, { expand: ["venue"] }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.title).toBe("DjangoCon");
    expect(seen[0]?.searchParams.get("expand")).toBe("venue");
  });
});

describe("useResourceMutations", () => {
  it("creates via POST and invalidates the resource's list queries", async () => {
    const { wrapper } = setup();
    let listCalls = 0;
    const posted: unknown[] = [];
    server.use(
      http.get(`${BASE}/events/`, () => {
        listCalls += 1;
        return HttpResponse.json(page([{ id: 1, title: "A" }]));
      }),
      http.post(`${BASE}/events/`, async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({ id: 2, title: "B" }, { status: 201 });
      }),
    );

    const { result } = renderHook(
      () => ({
        list: useResourceList<EventRow>("events"),
        mutations: useResourceMutations<EventRow>("events"),
      }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
    expect(listCalls).toBe(1);

    await act(async () => {
      const created = await result.current.mutations.create.mutateAsync({ title: "B" });
      expect(created.id).toBe(2);
    });

    expect(posted).toEqual([{ title: "B" }]);
    // invalidateQueries refetches the active list before mutateAsync resolves.
    expect(listCalls).toBe(2);
  });

  it("updates via PATCH on the detail path", async () => {
    const { wrapper } = setup();
    const patched: unknown[] = [];
    server.use(
      http.patch(`${BASE}/events/5/`, async ({ request }) => {
        patched.push(await request.json());
        return HttpResponse.json({ id: 5, title: "New" });
      }),
    );

    const { result } = renderHook(() => useResourceMutations<EventRow>("events"), { wrapper });
    await act(async () => {
      const updated = await result.current.update.mutateAsync({
        id: 5,
        values: { title: "New" },
      });
      expect(updated.title).toBe("New");
    });
    expect(patched).toEqual([{ title: "New" }]);
  });

  it("removes via DELETE and resolves void on 204", async () => {
    const { wrapper } = setup();
    server.use(http.delete(`${BASE}/events/5/`, () => new HttpResponse(null, { status: 204 })));
    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await expect(result.current.remove.mutateAsync(5)).resolves.toBeUndefined();
    });
  });

  it("invalidates extra invalidateKeys but never the schema entry", async () => {
    const { queryClient, wrapper } = setup();
    server.use(http.post(`${BASE}/events/`, () => HttpResponse.json({ id: 9 }, { status: 201 })));
    queryClient.setQueryData(["custom", "stats"], { total: 1 });
    queryClient.setQueryData(karniKeys.schema(), { sentinel: true });

    const { result } = renderHook(
      () => useResourceMutations("events", { invalidateKeys: [["custom", "stats"]] }),
      { wrapper },
    );
    await act(async () => {
      await result.current.create.mutateAsync({ title: "x" });
    });

    expect(queryClient.getQueryState(["custom", "stats"])?.isInvalidated).toBe(true);
    // D4: ["karni", resource] is the invalidation root, never bare ["karni"],
    // so the cached schema stays untouched.
    expect(queryClient.getQueryState(karniKeys.schema())?.isInvalidated).toBe(false);
  });

  it("surfaces DRF field errors (error.data passthrough) on failure", async () => {
    const { wrapper } = setup();
    server.use(
      http.post(`${BASE}/events/`, () =>
        HttpResponse.json({ title: ["This field is required."] }, { status: 400 }),
      ),
    );
    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await expect(result.current.create.mutateAsync({})).rejects.toMatchObject({
        status: 400,
        data: { title: ["This field is required."] },
      });
    });
  });
});
