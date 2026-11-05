/**
 * The tree hooks (experimental) against the simulated tree backend: the
 * requests they send, the shapes they return and the refresh after a write.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { server } from "../../tests/msw/server";
import { treeBackend, type TreeBackend } from "../components/resource/tree/tree-backend";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { karniKeys } from "./keys";
import {
  useResourceAncestors,
  useResourceChildren,
  useResourceTree,
  useTreeMutations,
} from "./useResourceTree";

function setup(): {
  backend: TreeBackend;
  wrapper: React.FC<{ children: React.ReactNode }>;
  queryClient: QueryClient;
} {
  const backend = treeBackend();
  server.use(...backend.handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  return { backend, wrapper, queryClient };
}

describe("tree hooks", () => {
  it("useResourceTree loads the roots and nested children", async () => {
    const { backend, wrapper } = setup();
    const { result } = renderHook(() => useResourceTree("regions", { depth: 2 }), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    const europe = result.current.data?.results[0];
    expect(europe).toMatchObject({ id: 1, name: "Europe", has_children: true });
    expect(europe?.children?.map((node) => node.name)).toEqual(["Nordics", "Iberia"]);
    expect(europe?.children?.[0]?.children).toBeNull();
    expect(result.current.data?.truncated).toBe(false);
    expect(backend.treeRequests()[0]?.searchParams.get("depth")).toBe("2");
  });

  it("useResourceTree asks below a root, and waits while disabled", async () => {
    const { backend, wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useResourceTree("regions", { root: 2, enabled }),
      { wrapper, initialProps: { enabled: false } },
    );
    expect(backend.treeRequests()).toHaveLength(0);
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.results.map((node) => node.name)).toEqual(["Norway", "Sweden"]);
    expect(backend.treeRequests()[0]?.searchParams.get("root")).toBe("2");
  });

  it("useResourceChildren and useResourceAncestors", async () => {
    const { wrapper } = setup();
    const children = renderHook(() => useResourceChildren("regions", 1, { pageSize: 1 }), {
      wrapper,
    });
    await waitFor(() => expect(children.result.current.data).toBeDefined());
    expect(children.result.current.data?.count).toBe(2);
    expect(children.result.current.data?.results.map((node) => node.name)).toEqual(["Nordics"]);
    const ancestors = renderHook(() => useResourceAncestors("regions", 10), { wrapper });
    await waitFor(() => expect(ancestors.result.current.data).toBeDefined());
    expect(ancestors.result.current.data?.map((node) => node.name)).toEqual(["Asia", "Japan"]);
  });

  it("useTreeMutations moves a node and deletes a branch, then refreshes the resource", async () => {
    const { backend, wrapper, queryClient } = setup();
    const { result } = renderHook(() => useTreeMutations("categories"), { wrapper });
    queryClient.setQueryData(karniKeys.tree("categories"), { results: [], truncated: false });
    await act(async () => {
      await result.current.move.mutateAsync({ id: 3, parent: null, position: 0 });
    });
    expect(backend.bodies.at(-1)?.body).toEqual({ parent: null, position: 0 });
    expect(backend.categories.find((row) => row.id === 3)).toMatchObject({
      parent: null,
      position: 0,
    });
    expect(queryClient.getQueryState(karniKeys.tree("categories"))?.isInvalidated).toBe(true);
    await act(async () => {
      await result.current.removeBranch.mutateAsync(4);
    });
    const deleted = backend.requests.at(-1);
    expect(deleted?.pathname).toBe("/api/categories/4/");
    expect(deleted?.searchParams.get("branch")).toBe("true");
    expect(backend.categories.filter((row) => row.deleted === true).map((row) => row.id)).toEqual([
      4, 5,
    ]);
  });

  it("move without a position sends only the parent", async () => {
    const { backend, wrapper } = setup();
    const { result } = renderHook(() => useTreeMutations("regions"), { wrapper });
    await act(async () => {
      await result.current.move.mutateAsync({ id: 12, parent: 1 });
    });
    expect(backend.bodies.at(-1)?.body).toEqual({ parent: 1 });
  });

  it("a cycle comes back as the server's 400", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useTreeMutations("regions"), { wrapper });
    await act(async () => {
      await expect(result.current.move.mutateAsync({ id: 1, parent: 3 })).rejects.toMatchObject({
        status: 400,
      });
    });
  });
});
