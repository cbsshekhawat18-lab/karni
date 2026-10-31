/**
 * TreeView's `access` mode (experimental) against the simulated backend: the
 * requester's access forest from `access/`, granted nodes and the nodes below
 * them selectable, ancestors and other roots greyed.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { useResourceAccessForest } from "../../../hooks/useResourceTree";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { treeBackend, type TreeBackend, type TreeBackendOptions } from "./tree-backend";
import { TreeView } from "./TreeView";

function providers(options: TreeBackendOptions): {
  backend: TreeBackend;
  wrapper: React.FC<{ children: React.ReactNode }>;
} {
  const backend = treeBackend(options);
  server.use(...backend.handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  return { backend, wrapper };
}

function accessRequests(backend: TreeBackend): URL[] {
  return backend.requests.filter((url) => url.pathname.endsWith("/regions/access/"));
}

describe("useResourceAccessForest", () => {
  it("loads the forest and sends the permission", async () => {
    const { backend, wrapper } = providers({ granted: { regions: [2, 9] } });
    const { result } = renderHook(
      () => useResourceAccessForest("regions", { permission: "shop.order:view" }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBeDefined());
    const [europe, asia, americas] = result.current.data?.results ?? [];
    expect(europe).toMatchObject({ label: "Europe", granted: false, has_children: true });
    expect(europe?.children?.[0]).toMatchObject({
      label: "Nordics",
      granted: true,
      children: null,
    });
    expect(asia?.children?.[0]).toMatchObject({ label: "Japan", granted: true });
    expect(americas).toMatchObject({ label: "Americas", granted: false, children: [] });
    expect(result.current.data?.all).toBe(false);
    expect(accessRequests(backend)[0]?.searchParams.get("permission")).toBe("shop.order:view");
  });
});

describe("TreeView with access", () => {
  it("lets the granted nodes and the nodes below them be chosen, and greys the rest", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { backend, wrapper } = providers({ granted: { regions: [2] } });
    render(<TreeView resource="regions" access onChange={onChange} searchable={false} />, {
      wrapper,
    });
    const europe = await screen.findByRole("treeitem", { name: "Europe" });
    expect(europe).toHaveAttribute("aria-disabled", "true");
    expect(await screen.findByRole("treeitem", { name: "Americas" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(backend.treeRequests()).toHaveLength(0); // the whole tree is never asked for
    // A greyed ancestor opens on a click instead of being chosen.
    await user.click(europe);
    expect(onChange).not.toHaveBeenCalled();
    const nordics = await screen.findByRole("treeitem", { name: "Nordics" });
    expect(nordics).not.toHaveAttribute("aria-disabled");
    await user.click(nordics);
    expect(onChange).toHaveBeenLastCalledWith(2, expect.objectContaining({ label: "Nordics" }));
    // Below a granted node: loaded from tree/?root= when opened, and choosable too.
    nordics.focus();
    await user.keyboard("{ArrowRight}");
    const norway = await screen.findByRole("treeitem", { name: "Norway" });
    expect(norway).not.toHaveAttribute("aria-disabled");
    expect(backend.treeRequests()[0]?.searchParams.get("root")).toBe("2");
    await user.click(norway);
    expect(onChange).toHaveBeenLastCalledWith(3, expect.objectContaining({ name: "Norway" }));
  });

  it("asks for one permission and treats all as every node granted", async () => {
    const onChange = vi.fn();
    const { backend, wrapper } = providers({ accessAll: true });
    render(
      <TreeView
        resource="regions"
        access={{ permission: "shop.order:view" }}
        onChange={onChange}
        searchable={false}
      />,
      { wrapper },
    );
    const asia = await screen.findByRole("treeitem", { name: "Asia" });
    expect(asia).not.toHaveAttribute("aria-disabled");
    await userEvent.setup().click(asia);
    expect(onChange).toHaveBeenCalledWith(8, expect.anything());
    expect(accessRequests(backend)[0]?.searchParams.get("permission")).toBe("shop.order:view");
  });
});
