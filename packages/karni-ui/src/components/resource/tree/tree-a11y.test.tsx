/**
 * axe-core over the tree components in their loaded, open and failed states,
 * rendered against the simulated tree backend (the shared a11y suite runs the
 * stories that need no network).
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Label } from "../../primitives/label";
import { treeBackend, type TreeBackendOptions } from "./tree-backend";
import { TreeBreadcrumb } from "./TreeBreadcrumb";
import { TreeSelect } from "./TreeSelect";
import { TreeView } from "./TreeView";

const OPTIONS: axe.RunOptions = {
  runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
  rules: { "color-contrast": { enabled: false } },
};

async function violations(): Promise<string[]> {
  const results = await axe.run(document.body, OPTIONS);
  return results.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${violation.help} — ${node.target.join(" ")}`),
  );
}

function mount(ui: React.ReactElement, options: TreeBackendOptions = {}): void {
  server.use(...treeBackend(options).handlers);
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

function Selectable(props: { multiple?: boolean }): React.ReactElement {
  const [value, setValue] = React.useState<string | number | Array<string | number> | null>(
    props.multiple === true ? [3] : 3,
  );
  return (
    <TreeView
      resource="regions"
      multiple={props.multiple}
      value={value}
      onChange={(next) => setValue(next)}
      reveal={3}
    />
  );
}

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

describe("tree components pass axe", () => {
  it("TreeView with an open path and a selection", async () => {
    mount(<Selectable />);
    await screen.findByRole("treeitem", { name: "Norway" });
    expect(await violations()).toEqual([]);
  });

  it("TreeView selecting several nodes", async () => {
    mount(<Selectable multiple />);
    await screen.findByRole("treeitem", { name: "Norway" });
    expect(await violations()).toEqual([]);
  });

  it("TreeView while it loads, and when a branch fails", async () => {
    const user = userEvent.setup();
    mount(<TreeView resource="regions" />, { lazyFailure: 500 });
    expect(await violations()).toEqual([]);
    const europe = await screen.findByRole("treeitem", { name: "Europe" });
    europe.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    await screen.findByText("Couldn't load the regions under Nordics.");
    expect(await violations()).toEqual([]);
  });

  it("TreeSelect closed and open, in a labelled field", async () => {
    const user = userEvent.setup();
    mount(
      <div>
        <Label htmlFor="region" id="region-label">
          Region
        </Label>
        <TreeSelect
          id="region"
          aria-labelledby="region-label"
          resource="regions"
          value={10}
          onChange={() => undefined}
        />
      </div>,
    );
    const button = await screen.findByRole("button", { name: "Region Kyoto" });
    expect(await violations()).toEqual([]);
    await user.click(button);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: "Kyoto" })).toHaveFocus());
    expect(await violations()).toEqual([]);
  });

  it("TreeBreadcrumb", async () => {
    mount(
      <TreeBreadcrumb
        resource="regions"
        id={10}
        item={{ id: 10, name: "Kyoto" }}
        href={(node) => `/regions/${String(node["id"])}`}
      />,
    );
    await screen.findByRole("navigation");
    expect(await violations()).toEqual([]);
  });
});
