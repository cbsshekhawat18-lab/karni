/**
 * ResourceForm with relations to tree models (x-karni-tree): each one is
 * edited with TreeSelect, through the real schema pipeline and the
 * simulated tree backend (msw).
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { ResourceForm } from "../form/ResourceForm";
import { treeBackend, type TreeBackend } from "./tree-backend";

function mount(ui: React.ReactElement): TreeBackend {
  const backend = treeBackend();
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

describe("ResourceForm and tree relations", () => {
  it("picks an FK and an M2M to trees with TreeSelect", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    const backend = mount(<ResourceForm resource="products" onSuccess={onSuccess} />);
    await user.type(await screen.findByRole("textbox", { name: /Name/ }), "Spade");

    const category = screen.getByRole("button", { name: /^Category/ });
    expect(category).toHaveAttribute("aria-haspopup", "tree");
    await user.click(category);
    const garden = await screen.findByRole("treeitem", { name: "Garden" });
    await waitFor(() => expect(garden).toHaveFocus());
    await user.keyboard("{ArrowRight}{ArrowRight}{Enter}");
    await waitFor(() => expect(category).toHaveAccessibleName("Category Tools"));

    const regions = screen.getByRole("button", { name: /^Regions/ });
    await user.click(regions);
    const tree = await screen.findByRole("tree");
    await user.click(await within(tree).findByRole("treeitem", { name: "Asia" }));
    await user.click(within(tree).getByRole("treeitem", { name: "Americas" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tree")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const posted = backend.bodies.find((entry) => entry.url.pathname === "/api/products/");
    expect(posted?.body).toMatchObject({ name: "Spade", category: 2, regions: [8, 11] });
  });

  it("labels the stored values when editing", async () => {
    mount(<ResourceForm resource="products" id={1} />);
    expect(await screen.findByRole("button", { name: "Category Tools" })).toBeInTheDocument();
    expect(await screen.findByText("Norway")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Norway" })).toBeInTheDocument();
  });

  it("edits a tree's own parent with TreeSelect and leaves position to the move action", async () => {
    mount(<ResourceForm resource="categories" />);
    expect(await screen.findByRole("button", { name: /^Parent/ })).toHaveAttribute(
      "aria-haspopup",
      "tree",
    );
    expect(screen.queryByText("Position")).not.toBeInTheDocument();
  });
});
