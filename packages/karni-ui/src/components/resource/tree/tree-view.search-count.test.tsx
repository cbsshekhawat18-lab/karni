/**
 * TreeView's counts per node (`countField`) and its search that keeps
 * ancestors (`searchKeepsAncestors`), against the simulated tree backend.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axeViolations } from "../../../../tests/axe";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { treeBackend, type TreeBackendOptions, type TreeRow } from "./tree-backend";
import { TreeView, type TreeViewProps } from "./TreeView";

const REGIONS: TreeRow[] = [
  { id: 1, name: "Europe", parent: null, dataset_count: 12 },
  { id: 2, name: "Nordics", parent: 1, dataset_count: 5 },
  { id: 3, name: "Norway", parent: 2, dataset_count: 3 },
  { id: 4, name: "Sweden", parent: 2 },
  { id: 5, name: "Iberia", parent: 1, dataset_count: 7 },
  { id: 6, name: "Portugal", parent: 5 },
  { id: 8, name: "Asia", parent: null, dataset_count: 0 },
  { id: 9, name: "Japan", parent: 8 },
];

function mount(props: Partial<TreeViewProps>, options: TreeBackendOptions = {}) {
  const backend = treeBackend({ regions: REGIONS, ...options });
  server.use(...backend.handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <KarniProvider client={client} queryClient={queryClient}>
      <TreeView resource="regions" searchDebounceMs={0} {...props} />
    </KarniProvider>,
  );
  return { backend, ...view };
}

const names = (): string[] =>
  screen
    .getAllByRole("treeitem")
    .map(
      (node) =>
        node.getAttribute("aria-level") +
        ":" +
        (node.querySelector("span.flex-1")?.textContent ?? ""),
    );

describe("TreeView countField", () => {
  it("shows each node's number, none for a node without one, and says what it counts", async () => {
    mount({ countField: "dataset_count", countNoun: "datasets", defaultExpanded: [1] });
    const europe = await screen.findByRole("treeitem", { name: /Europe/ });
    expect(europe).toHaveTextContent("12");
    expect(within(europe).getByText("datasets")).toHaveClass("sr-only");
    expect(await screen.findByRole("treeitem", { name: /Iberia/ })).toHaveTextContent("7");
    expect(screen.getByRole("treeitem", { name: /Asia/ })).toHaveTextContent("0");
    expect(screen.getByRole("treeitem", { name: /Nordics/ })).toHaveTextContent("5");
  });

  it("shows no count without countField", async () => {
    mount({});
    const europe = await screen.findByRole("treeitem", { name: "Europe" });
    expect(europe).not.toHaveTextContent("12");
  });
});

describe("TreeView searchKeepsAncestors", () => {
  it("shows a match under its ancestors with the path open and the match in bold", async () => {
    const user = userEvent.setup();
    mount({ searchKeepsAncestors: true });
    await screen.findByRole("treeitem", { name: "Europe" });
    await user.type(screen.getByRole("searchbox", { name: "Search regions" }), "norway");
    await waitFor(() => expect(names()).toEqual(["1:Europe", "2:Nordics", "3:Norway"]));
    expect(
      screen.getByRole("treeitem", { name: "Norway" }).querySelector("span.flex-1"),
    ).toHaveClass("font-semibold");
    expect(
      screen.getByRole("treeitem", { name: "Europe" }).querySelector("span.flex-1"),
    ).not.toHaveClass("font-semibold");
    expect(screen.getByRole("treeitem", { name: "Europe" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("shares an ancestor between matches and keeps unrelated branches out", async () => {
    const user = userEvent.setup();
    mount({ searchKeepsAncestors: true });
    await screen.findByRole("treeitem", { name: "Europe" });
    await user.type(screen.getByRole("searchbox"), "ia");
    await waitFor(() => expect(names()).toContain("2:Iberia"));
    expect(names().filter((entry) => entry === "1:Europe")).toHaveLength(1);
    expect(screen.queryByRole("treeitem", { name: "Sweden" })).toBeNull();
  });

  it("collapses a branch of the result", async () => {
    const user = userEvent.setup();
    mount({ searchKeepsAncestors: true });
    await screen.findByRole("treeitem", { name: "Europe" });
    await user.type(screen.getByRole("searchbox"), "norway");
    await screen.findByRole("treeitem", { name: "Norway" });
    await user.click(
      within(screen.getByRole("treeitem", { name: "Nordics" })).getByTestId("tree-toggle"),
    );
    await waitFor(() => expect(screen.queryByRole("treeitem", { name: "Norway" })).toBeNull());
    expect(screen.getByRole("treeitem", { name: "Nordics" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("prunes the loaded nodes the same way when the API cannot search", async () => {
    const user = userEvent.setup();
    mount({ searchKeepsAncestors: true, defaultExpanded: [1, 2] }, { search: false });
    await screen.findByRole("treeitem", { name: "Norway" });
    await user.type(screen.getByRole("searchbox"), "norway");
    await waitFor(() => expect(names()).toEqual(["1:Europe", "2:Nordics", "3:Norway"]));
  });

  it("says when nothing matches, and has no axe violations", async () => {
    const user = userEvent.setup();
    const { container } = mount({ searchKeepsAncestors: true, countField: "dataset_count" });
    await screen.findByRole("treeitem", { name: /Europe/ });
    await user.type(screen.getByRole("searchbox"), "norway");
    await screen.findByRole("treeitem", { name: /Norway/ });
    expect(await axeViolations(container)).toEqual([]);
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(
      await screen.findByText("No regions match “zzz”", { selector: "p" }),
    ).toBeInTheDocument();
  });
});
