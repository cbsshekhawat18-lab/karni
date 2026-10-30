/**
 * TreeBreadcrumb, and the path ResourceDetail shows above a tree resource's
 * record, against the simulated tree backend (msw).
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { ResourceDetail } from "../detail/ResourceDetail";
import { treeBackend, type TreeBackend, type TreeBackendOptions } from "./tree-backend";
import { TreeBreadcrumb } from "./TreeBreadcrumb";

function mount(ui: React.ReactElement, options: TreeBackendOptions = {}): TreeBackend {
  const backend = treeBackend(options);
  server.use(...backend.handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
  return backend;
}

describe("TreeBreadcrumb", () => {
  it("lists the ancestors root first and ends with the node", async () => {
    mount(<TreeBreadcrumb resource="regions" id={10} item={{ id: 10, name: "Kyoto" }} />);
    const nav = await screen.findByRole("navigation", { name: "Region path" });
    const items = within(nav).getAllByRole("listitem");
    expect(items.map((entry) => entry.textContent)).toEqual(["Asia/", "Japan/", "Kyoto"]);
    expect(within(nav).getByText("Kyoto")).toHaveAttribute("aria-current", "page");
  });

  it("links the ancestors and navigates on the client", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    mount(
      <TreeBreadcrumb
        resource="regions"
        id={3}
        href={(node) => `/regions/${String(node["id"])}`}
        onNavigate={onNavigate}
      />,
    );
    const europe = await screen.findByRole("link", { name: "Europe" });
    expect(europe).toHaveAttribute("href", "/regions/1");
    await user.click(screen.getByRole("link", { name: "Nordics" }));
    expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ id: 2, name: "Nordics" }));
  });

  it("uses buttons when only onNavigate is given", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    mount(<TreeBreadcrumb resource="regions" id={3} onNavigate={onNavigate} />);
    await user.click(await screen.findByRole("button", { name: "Europe" }));
    expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it("renders nothing for a root", async () => {
    const backend = mount(<TreeBreadcrumb resource="regions" id={1} />);
    await vi.waitFor(() =>
      expect(backend.requests.some((url) => url.pathname.endsWith("/1/ancestors/"))).toBe(true),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("says when the path cannot be loaded and tries again", async () => {
    const user = userEvent.setup();
    mount(<TreeBreadcrumb resource="regions" id={10} />, { ancestorsFailure: 500 });
    expect(
      await screen.findByText("Couldn't load where this region sits in the tree."),
    ).toBeInTheDocument();
    server.use(...treeBackend().handlers);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("navigation", { name: "Region path" })).toBeInTheDocument();
  });
});

describe("ResourceDetail of a tree resource", () => {
  it("shows the path above the record", async () => {
    mount(<ResourceDetail resource="regions" id={4} title={(item) => String(item["name"])} />);
    const nav = await screen.findByRole("navigation", { name: "Region path" });
    expect(
      within(nav)
        .getAllByRole("listitem")
        .map((entry) => entry.textContent),
    ).toEqual(["Europe/", "Nordics/", "Sweden"]);
    expect(await screen.findByRole("heading", { name: "Sweden" })).toBeInTheDocument();
  });

  it("gives the ancestors links, or hides the path", async () => {
    mount(
      <>
        <ResourceDetail
          resource="regions"
          id={6}
          breadcrumb={{ href: (node) => `/regions/${String(node["id"])}` }}
        />
        <ResourceDetail resource="categories" id={2} breadcrumb={false} />
      </>,
    );
    expect(await screen.findByRole("link", { name: "Iberia" })).toHaveAttribute(
      "href",
      "/regions/5",
    );
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
  });

  it("shows no path for a resource that is not a tree", async () => {
    mount(<ResourceDetail resource="products" id={1} title="Product" />);
    expect(await screen.findByText("Trowel")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
