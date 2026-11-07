/**
 * TreeSelect against the simulated tree backend (msw): the popover tree,
 * single and multiple choice, preselected values and their labels.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { treeBackend, type TreeBackend, type TreeBackendOptions } from "./tree-backend";
import { TreeSelect, type TreeSelectProps } from "./TreeSelect";

type Value = TreeSelectProps["value"];

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
  props: Partial<Omit<TreeSelectProps, "value">> & {
    initial?: Value;
    onValue?: (value: Value) => void;
  },
): React.ReactElement {
  const { initial = null, onValue, ...rest } = props;
  const [value, setValue] = React.useState<Value>(initial);
  return (
    <TreeSelect
      resource="regions"
      aria-label="Region"
      value={value}
      onChange={(next) => {
        setValue(next);
        onValue?.(next);
      }}
      {...rest}
    />
  );
}

describe("TreeSelect", () => {
  it("opens a tree, chooses a node with Enter and returns focus to the button", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker onValue={onValue} />);
    const button = screen.getByRole("button", { name: "Region Choose a region" });
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const tree = await screen.findByRole("tree", { name: "Region" });
    const popup = screen.getByRole("dialog", { name: "Choose a region" });
    expect(button).toHaveAttribute("aria-controls", popup.id);
    expect(popup).toContainElement(tree);
    const europe = await within(tree).findByRole("treeitem", { name: "Europe" });
    await waitFor(() => expect(europe).toHaveFocus());
    await user.keyboard("{ArrowRight}{ArrowRight}{Enter}");
    expect(onValue).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(screen.queryByRole("tree")).not.toBeInTheDocument());
    expect(button).toHaveFocus();
    expect(button).toHaveAccessibleName("Region Nordics");
  });

  it("opens on the press, so a click whose release lands elsewhere is not lost, and stays open after the click", async () => {
    const user = userEvent.setup();
    mount(<Picker />);
    const button = screen.getByRole("button", { name: "Region Choose a region" });
    // The press only: the page moved under the pointer before the release (a validation message above).
    await user.pointer({ keys: "[MouseLeft>]", target: button });
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.pointer({ keys: "[/MouseLeft]", target: document.body });
    await screen.findByRole("tree", { name: "Region" });
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("still opens with Enter and closes on a second click", async () => {
    const user = userEvent.setup();
    mount(<Picker />);
    const button = screen.getByRole("button", { name: "Region Choose a region" });
    button.focus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.click(button);
    await waitFor(() => expect(button).toHaveAttribute("aria-expanded", "false"));
  });

  it("labels a preselected deep node and opens the tree at it", async () => {
    const user = userEvent.setup();
    const backend = mount(<Picker initial={10} />);
    const button = await screen.findByRole("button", { name: "Region Kyoto" });
    expect(backend.requests.some((url) => url.pathname.endsWith("/regions/10/"))).toBe(true);
    await user.click(button);
    const kyoto = await screen.findByRole("treeitem", { name: "Kyoto" });
    await waitFor(() => expect(kyoto).toHaveFocus());
    expect(kyoto).toHaveAttribute("aria-selected", "true");
    expect(kyoto).toHaveAttribute("aria-level", "3");
  });

  it("says when a preselected node cannot be loaded", async () => {
    mount(<Picker initial={999} />);
    expect(
      await screen.findByRole("button", { name: "Region Couldn't load region 999" }),
    ).toBeInTheDocument();
  });

  it("clears the value", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker initial={1} onValue={onValue} />);
    await screen.findByRole("button", { name: "Region Europe" });
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onValue).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole("button", { name: "Region Choose a region" })).toHaveFocus();
  });

  it("closes with Escape without choosing", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker onValue={onValue} />);
    const button = screen.getByRole("button", { name: /Region/ });
    await user.click(button);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: "Europe" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tree")).not.toBeInTheDocument());
    expect(button).toHaveFocus();
    expect(onValue).not.toHaveBeenCalled();
  });

  it("chooses several nodes, keeps the tree open and removes a chip", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mount(<Picker multiple initial={[3]} onValue={onValue} />);
    expect(await screen.findByText("Norway")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Region Add regions" });
    await user.click(button);
    const tree = await screen.findByRole("tree");
    expect(tree).toHaveAttribute("aria-multiselectable", "true");
    const asia = await within(tree).findByRole("treeitem", { name: "Asia" });
    await user.click(asia);
    expect(onValue).toHaveBeenLastCalledWith([3, 8]);
    expect(screen.getByRole("tree")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tree")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Remove Norway" }));
    expect(onValue).toHaveBeenLastCalledWith([8]);
  });

  it("is disabled", () => {
    mount(<Picker disabled initial={null} />);
    expect(screen.getByRole("button", { name: /Region/ })).toBeDisabled();
  });
});
