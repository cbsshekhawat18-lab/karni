/**
 * FacetPanel and ResourceTable's `facets` (experimental), through the real
 * schema pipeline and the simulated catalog backend (msw): `regions` is a
 * taxonomy of `products` (`x-karni-taxonomy`), with `facets/` and the list
 * filters `?regions=` and `?regions_descendants=`.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { parseOpenApi } from "../../../schema/parse";
import { KarniProvider } from "../../../schema/provider";
import { ResourceForm } from "../form/ResourceForm";
import { ResourceTable } from "../table/ResourceTable";
import { treeBackend, treeOpenApi, type ProductRow, type TreeBackend } from "../tree/tree-backend";
import { FacetPanel, facetRows } from "./FacetPanel";

/** Europe > Nordics > Norway, Sweden; Europe > Iberia > Spain; Asia > Japan; Americas. */
function products(): ProductRow[] {
  return [
    { id: 1, name: "Trowel", category: 2, regions: [3] },
    { id: 2, name: "Rake", category: 2, regions: [3, 4] },
    { id: 3, name: "Seeds", category: 3, regions: [7] },
    { id: 4, name: "Knife", category: 5, regions: [9] },
    { id: 5, name: "Hose", category: 2, regions: [] },
  ];
}

function mount(ui: React.ReactElement, options: { facetsFailure?: 500 } = {}): TreeBackend {
  const backend = treeBackend({ taxonomy: true, products: products(), ...options });
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

function facetRequests(backend: TreeBackend): URL[] {
  return backend.requests.filter((url) => url.pathname.endsWith("/products/facets/"));
}

describe("the schema", () => {
  it("marks a taxonomy's relation and the facets operation", () => {
    const parsed = parseOpenApi(treeOpenApi({ taxonomy: true }));
    const product = parsed.resources["products"];
    expect(product?.operations.facets?.path).toBe("/api/products/facets/");
    const regions = product?.fields.find((field) => field.name === "regions");
    expect(regions?.taxonomy).toBe("regions");
    expect(regions?.tree).toEqual({ parent: "parent", ordered: false });
    const category = product?.fields.find((field) => field.name === "category");
    expect(category?.taxonomy).toBeUndefined();
    const plain = parseOpenApi(treeOpenApi()).resources["products"];
    expect(plain?.operations.facets).toBeUndefined();
  });
});

describe("facetRows", () => {
  it("nests each node under its counted parent and starts the others at the top", () => {
    const rows = facetRows([
      { id: 1, label: "Europe", parent: null, count: 3 },
      { id: 2, label: "Nordics", parent: 1, count: 2 },
      { id: 3, label: "Norway", parent: 2, count: 2 },
      { id: 9, label: "Japan", parent: 8, count: 1 },
    ]);
    expect(rows.map((row) => [row.label, row.depth])).toEqual([
      ["Europe", 0],
      ["Nordics", 1],
      ["Norway", 2],
      ["Japan", 0],
    ]);
  });
});

describe("FacetPanel", () => {
  it("shows each node's count, rolled up, and calls onChange when one is ticked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const backend = mount(
      <FacetPanel
        resource="products"
        taxonomy="regions"
        label="Regions"
        value={[]}
        onChange={onChange}
        query={{ search: "e" }}
      />,
    );
    const panel = await screen.findByRole("region", { name: "Regions" });
    const europe = await within(panel).findByRole("checkbox", { name: "Europe 3" });
    expect(within(panel).getByRole("checkbox", { name: "Norway 2" })).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: "Asia 1" })).toBeInTheDocument();
    expect(within(panel).queryByText("Americas")).not.toBeInTheDocument();
    const request = facetRequests(backend)[0];
    expect(request?.searchParams.get("taxonomy")).toBe("regions");
    expect(request?.searchParams.get("rollup")).toBe("true");
    expect(request?.searchParams.get("search")).toBe("e");
    await user.click(europe);
    expect(onChange).toHaveBeenCalledWith([1]);
  });

  it("unticks a chosen node and clears the choice", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mount(
      <FacetPanel
        resource="products"
        taxonomy="regions"
        value={[3, 9]}
        onChange={onChange}
        rollup={false}
      />,
    );
    const norway = await screen.findByRole("checkbox", { name: "Norway 2" });
    expect(norway).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /Europe/ })).not.toBeInTheDocument();
    await user.click(norway);
    expect(onChange).toHaveBeenLastCalledWith([9]);
    await user.click(screen.getByRole("button", { name: "Clear regions" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("says when no node counts a row, and when the counts cannot load", async () => {
    mount(
      <FacetPanel
        resource="products"
        taxonomy="regions"
        value={[]}
        onChange={() => undefined}
        query={{ search: "nothing" }}
      />,
    );
    expect(await screen.findByText("No regions counts a row here.")).toBeInTheDocument();
  });

  it("offers to try again when the counts fail", async () => {
    mount(
      <FacetPanel resource="products" taxonomy="regions" value={[]} onChange={() => undefined} />,
      { facetsFailure: 500 },
    );
    expect(await screen.findByRole("button", { name: /Try again|Retry/ })).toBeInTheDocument();
  });
});

describe("ResourceTable facets", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("filters the table to the rows under the chosen nodes", async () => {
    const user = userEvent.setup();
    const backend = mount(<ResourceTable resource="products" facets syncUrl={false} />);
    expect(await screen.findByText("Knife")).toBeInTheDocument();
    const panel = await screen.findByRole("region", { name: "Regions" });
    await user.click(await within(panel).findByRole("checkbox", { name: "Nordics 2" }));
    await waitFor(() => expect(screen.queryByText("Knife")).not.toBeInTheDocument());
    expect(screen.getByText("Trowel")).toBeInTheDocument();
    expect(screen.getByText("Rake")).toBeInTheDocument();
    const lists = backend.requests.filter((url) => url.pathname === "/api/products/");
    const last = lists[lists.length - 1];
    expect(last?.searchParams.getAll("regions")).toEqual(["2"]);
    expect(last?.searchParams.get("regions_descendants")).toBe("true");
    // The panel's own counts leave its own filter out: every node stays a choice.
    const facets = facetRequests(backend);
    expect(facets[facets.length - 1]?.searchParams.has("regions")).toBe(false);
    expect(within(panel).getByRole("checkbox", { name: "Asia 1" })).not.toBeChecked();
    expect(within(panel).getByRole("checkbox", { name: "Nordics 2" })).toBeChecked();
  });

  it("keeps the choice in the URL and shows no panel without facets", async () => {
    const user = userEvent.setup();
    mount(<ResourceTable resource="products" facets={["regions"]} />);
    const panel = await screen.findByRole("region", { name: "Regions" });
    await user.click(await within(panel).findByRole("checkbox", { name: "Japan 1" }));
    await waitFor(() => expect(window.location.search).toContain("products.regions=9"));
    expect(window.location.search).toContain("products.regions_descendants=true");
  });

  it("shows no panel unless asked", async () => {
    mount(<ResourceTable resource="products" />);
    expect(await screen.findByText("Knife")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Regions" })).not.toBeInTheDocument();
  });
});

describe("ResourceForm and a taxonomy", () => {
  it("edits the tags with TreeSelect", async () => {
    mount(<ResourceForm resource="products" />);
    const regions = await screen.findByRole("button", { name: /^Regions/ });
    expect(regions).toHaveAttribute("aria-haspopup", "dialog");
  });
});

describe("FacetPanel passes axe", () => {
  it("with counts and a choice, in a table", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    mount(
      <>
        <FacetPanel resource="products" taxonomy="regions" value={[2]} onChange={() => undefined} />
        <ResourceTable resource="products" facets syncUrl={false} />
      </>,
    );
    await screen.findByRole("checkbox", { name: "Japan 1" });
    await screen.findByText("Knife");
    const results = await axe.run(document.body, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(
      results.violations.flatMap((violation) =>
        violation.nodes.map((node) => `${violation.id}: ${node.target.join(" ")}`),
      ),
    ).toEqual([]);
  });
});
