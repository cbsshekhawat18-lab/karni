/**
 * TreeView against a simulated backend (msw): the real client, tree/ and
 * its lazy branches, ancestors/, search, and the WAI-ARIA tree keyboard
 * pattern.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import {
  makeWideTree,
  treeBackend,
  type TreeBackend,
  type TreeBackendOptions,
} from "./tree-backend";
import { TreeView, type TreeValue, type TreeViewProps } from "./TreeView";

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

function Picker(
  props: Partial<TreeViewProps> & { initial?: TreeValue; onValue?: (value: TreeValue) => void },
): React.ReactElement {
  const { initial = null, onValue, ...rest } = props;
  const [value, setValue] = React.useState<TreeValue>(initial);
  return (
    <TreeView
      resource="regions"
      value={value}
      onChange={(next) => {
        setValue(next);
        onValue?.(next);
      }}
      searchDebounceMs={0}
      {...rest}
    />
  );
}

async function item(name: string): Promise<HTMLElement> {
  return screen.findByRole("treeitem", { name });
}

describe("TreeView: the WAI-ARIA tree pattern", () => {
  it("renders the roots with their level, position and state, and one tab stop", async () => {
    mount(<TreeView resource="regions" searchDebounceMs={0} />);
    const tree = await screen.findByRole("tree", { name: "Regions" });
    const roots = await within(tree).findAllByRole("treeitem");
    expect(roots.map((node) => node.textContent)).toEqual(["Europe", "Asia", "Americas"]);
    const europe = roots[0] as HTMLElement;
    expect(europe).toHaveAttribute("aria-level", "1");
    expect(europe).toHaveAttribute("aria-setsize", "3");
    expect(europe).toHaveAttribute("aria-posinset", "1");
    expect(europe).toHaveAttribute("aria-expanded", "false");
    expect(roots.filter((node) => node.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(europe).toHaveAttribute("tabindex", "0");
    // Without onChange the tree does not select.
    expect(europe).not.toHaveAttribute("aria-selected");
  });

  it("moves with the arrow keys, Home and End, and opens and closes branches", async () => {
    const user = userEvent.setup();
    const backend = mount(<TreeView resource="regions" searchDebounceMs={0} />);
    const europe = await item("Europe");
    europe.focus();
    await user.keyboard("{ArrowDown}");
    expect(await item("Asia")).toHaveFocus();
    await user.keyboard("{End}");
    expect(await item("Americas")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(europe).toHaveFocus();

    // Right opens (the children came with depth 2: no request), Right again enters.
    await user.keyboard("{ArrowRight}");
    expect(europe).toHaveAttribute("aria-expanded", "true");
    expect(backend.treeRequests()).toHaveLength(1);
    await user.keyboard("{ArrowRight}");
    const nordics = await item("Nordics");
    expect(nordics).toHaveFocus();
    expect(nordics).toHaveAttribute("aria-level", "2");
    expect(nordics).toHaveAttribute("aria-posinset", "1");
    expect(nordics).toHaveAttribute("aria-setsize", "2");

    // Left goes to the parent, Left again closes it.
    await user.keyboard("{ArrowLeft}");
    expect(europe).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(europe).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("treeitem", { name: "Nordics" })).not.toBeInTheDocument();
  });

  it("loads a deeper branch when it is opened, once", async () => {
    const user = userEvent.setup();
    const backend = mount(<TreeView resource="regions" searchDebounceMs={0} />);
    const europe = await item("Europe");
    europe.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    const nordics = await item("Nordics");
    expect(nordics).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{ArrowRight}");
    const norway = await item("Norway");
    expect(norway).toHaveAttribute("aria-level", "3");
    const lazy = backend.treeRequests().filter((url) => url.searchParams.get("root") === "2");
    expect(lazy).toHaveLength(1);
    expect(lazy[0]?.searchParams.get("depth")).toBe("2");

    // Closing and opening again uses what was loaded.
    await user.keyboard("{ArrowLeft}{ArrowRight}");
    expect(await item("Norway")).toBeInTheDocument();
    expect(
      backend.treeRequests().filter((url) => url.searchParams.get("root") === "2"),
    ).toHaveLength(1);
  });

  it("opens every sibling with *", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" searchDebounceMs={0} />);
    const europe = await item("Europe");
    europe.focus();
    await user.keyboard("*");
    expect(europe).toHaveAttribute("aria-expanded", "true");
    expect(await item("Asia")).toHaveAttribute("aria-expanded", "true");
    expect(await item("Americas")).toHaveAttribute("aria-expanded", "true");
    expect(await item("Canada")).toBeInTheDocument();
  });

  it("jumps to the next node whose label starts with the typed text", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" searchDebounceMs={0} />);
    const europe = await item("Europe");
    europe.focus();
    await user.keyboard("a");
    expect(await item("Asia")).toHaveFocus();
    await user.keyboard("a");
    expect(await item("Americas")).toHaveFocus();
  });

  it("selects one node with Enter or a click, and reports the activation", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    const onActivate = vi.fn();
    mount(<Picker onValue={onValue} onActivate={onActivate} />);
    const asia = await item("Asia");
    asia.focus();
    await user.keyboard("{Enter}");
    expect(onValue).toHaveBeenLastCalledWith(8);
    expect(onActivate).toHaveBeenCalledWith(expect.objectContaining({ id: 8, name: "Asia" }));
    expect(asia).toHaveAttribute("aria-selected", "true");
    expect(await item("Europe")).toHaveAttribute("aria-selected", "false");
    await user.click(await item("Americas"));
    expect(onValue).toHaveBeenLastCalledWith(11);
  });

  it("toggles several nodes with Space in multiple mode", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker multiple initial={[1]} onValue={onValue} />);
    const asia = await item("Asia");
    expect(screen.getByRole("tree")).toHaveAttribute("aria-multiselectable", "true");
    asia.focus();
    await user.keyboard(" ");
    expect(onValue).toHaveBeenLastCalledWith([1, 8]);
    await user.keyboard("{ArrowUp} ");
    expect(onValue).toHaveBeenLastCalledWith([8]);
  });

  it("opens the path to a revealed node and focuses the selected one", async () => {
    const backend = mount(<Picker initial={10} reveal={10} autoFocus />);
    const kyoto = await item("Kyoto");
    await waitFor(() => expect(kyoto).toHaveFocus());
    expect(kyoto).toHaveAttribute("aria-level", "3");
    expect(kyoto).toHaveAttribute("aria-selected", "true");
    expect(backend.requests.some((url) => url.pathname.endsWith("/regions/10/ancestors/"))).toBe(
      true,
    );
  });
});

describe("TreeView search", () => {
  it("asks the list's ?search= and shows the matches flat", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    const backend = mount(<Picker onValue={onValue} />);
    await item("Europe");
    await user.type(screen.getByRole("searchbox", { name: "Search regions" }), "nor");
    const norway = await item("Norway");
    expect(norway).toHaveAttribute("aria-level", "1");
    expect(screen.getAllByRole("treeitem").map((node) => node.textContent)).toEqual([
      "Nordics",
      "Norway",
    ]);
    expect(
      backend.requests.some(
        (url) => url.pathname.endsWith("/regions/") && url.searchParams.get("search") === "nor",
      ),
    ).toBe(true);
    // ArrowDown from the search field enters the results.
    await user.keyboard("{ArrowDown}");
    expect(await item("Nordics")).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onValue).toHaveBeenLastCalledWith(3);
  });

  it("narrows the loaded nodes when the API cannot search", async () => {
    const user = userEvent.setup();
    const backend = mount(<TreeView resource="regions" searchDebounceMs={0} />, { search: false });
    await item("Europe");
    await user.type(screen.getByRole("searchbox"), "an");
    await waitFor(() =>
      expect(screen.getAllByRole("treeitem").map((node) => node.textContent)).toEqual([
        "Japan",
        "Canada",
      ]),
    );
    expect(backend.requests.some((url) => url.searchParams.has("search"))).toBe(false);
  });

  it("says when nothing matches", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" searchDebounceMs={0} />);
    await item("Europe");
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(
      await screen.findByText("No regions match “zzz”", { selector: "p" }),
    ).toBeInTheDocument();
  });
});

describe("TreeView states", () => {
  it("shows a loading tree, then the nodes", async () => {
    mount(<TreeView resource="regions" />, { treeDelay: 50 });
    expect(screen.getByRole("tree", { name: "Regions" })).toHaveAttribute("aria-busy", "true");
    expect(await item("Europe")).toBeInTheDocument();
  });

  it("says when the tree has no nodes", async () => {
    mount(<TreeView resource="regions" />, { regions: [] });
    expect(await screen.findByText("No regions yet", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
  });

  it("explains a failed load and tries again", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" />, { treeFailure: 500 });
    const retry = await screen.findByRole("button", { name: /try again/i });
    server.use(...treeBackend().handlers);
    await user.click(retry);
    expect(await item("Europe")).toBeInTheDocument();
  });

  it("says which branch failed to load and tries it again", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" searchDebounceMs={0} />, { lazyFailure: 500 });
    const europe = await item("Europe");
    europe.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(await screen.findByText("Couldn't load the regions under Nordics.")).toBeInTheDocument();
    server.use(...treeBackend().handlers);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await item("Norway")).toBeInTheDocument();
  });

  it("says when the node limit cut a branch", async () => {
    mount(<TreeView resource="regions" />, { maxNodes: 4 });
    await item("Europe");
    expect(
      await screen.findByText(/Some branches are too large to show at once/),
    ).toBeInTheDocument();
  });

  it("starts below a root node", async () => {
    mount(<TreeView resource="regions" root={1} />);
    const nodes = await screen.findAllByRole("treeitem");
    expect(nodes.map((node) => node.textContent)).toEqual(["Nordics", "Iberia"]);
  });

  it("opens a tree of 10,000 nodes with one request for two levels", async () => {
    const regions = makeWideTree(10, 32, 3);
    expect(regions.length).toBeGreaterThan(10_000);
    const backend = mount(<TreeView resource="regions" />, { regions });
    expect(await screen.findAllByRole("treeitem")).toHaveLength(10);
    expect(backend.treeRequests()).toHaveLength(1);
  });
});
