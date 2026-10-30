import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { screen, userEvent } from "storybook/test";
import { makeWideTree } from "./tree-backend";
import { TreeStoryProviders, treeStoryBackend } from "./tree-stories-support";
import { TreeView, type TreeValue, type TreeViewProps } from "./TreeView";

/**
 * One story per state of TreeView, against msw handlers that simulate a
 * Karni region tree (any size, failing on demand). Open states get there
 * through a play function.
 */
function Selectable(args: TreeViewProps): React.ReactElement {
  const [value, setValue] = React.useState<TreeValue>(args.value ?? null);
  return (
    <div className="max-w-sm">
      <TreeView {...args} value={value} onChange={(next) => setValue(next)} />
    </div>
  );
}

const meta = {
  title: "Resource/TreeView",
  component: Selectable,
  args: { resource: "regions" },
  parameters: treeStoryBackend(),
  decorators: [
    (Story) => (
      <TreeStoryProviders>
        <Story />
      </TreeStoryProviders>
    ),
  ],
} satisfies Meta<typeof Selectable>;

export default meta;
type Story = StoryObj<typeof meta>;

async function openEurope(): Promise<void> {
  const user = userEvent.setup();
  const europe = await screen.findByRole("treeitem", { name: "Europe" });
  europe.focus();
  await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
  await screen.findByRole("treeitem", { name: "Norway" });
}

export const Roots: Story = {};

/** A branch two levels down, loaded when it was opened. */
export const OpenBranch: Story = { play: openEurope };

/** A chosen node, with the path to it open (`reveal`). */
export const Revealed: Story = { args: { value: 10, reveal: 10 } };

export const Multiple: Story = { args: { multiple: true, value: [3, 9] } };

/** The search asks the list's `?search=` and shows the matches flat. */
export const Search: Story = {
  play: async () => {
    const user = userEvent.setup();
    await screen.findByRole("treeitem", { name: "Europe" });
    await user.type(screen.getByRole("searchbox"), "an");
    await screen.findByRole("treeitem", { name: "Japan" });
  },
};

export const NoMatch: Story = {
  play: async () => {
    const user = userEvent.setup();
    await screen.findByRole("treeitem", { name: "Europe" });
    await user.type(screen.getByRole("searchbox"), "zzz");
  },
};

/** 10,570 nodes: two levels on the first request, then one request per opened branch. */
export const TenThousand: Story = {
  parameters: treeStoryBackend({ regions: makeWideTree(10, 32, 3) }),
};

/** The node limit cut a level: the tree says so. */
export const Truncated: Story = { parameters: treeStoryBackend({ maxNodes: 4 }) };

export const Loading: Story = { parameters: treeStoryBackend({ treeDelay: "infinite" }) };

/** A branch is loading (its spinner) while the rest of the tree stays usable. */
export const LoadingBranch: Story = {
  parameters: treeStoryBackend({ lazyDelay: "infinite" }),
  play: async () => {
    const user = userEvent.setup();
    const europe = await screen.findByRole("treeitem", { name: "Europe" });
    europe.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
  },
};

export const BranchFailed: Story = {
  parameters: treeStoryBackend({ lazyFailure: 500 }),
  play: async () => {
    const user = userEvent.setup();
    const europe = await screen.findByRole("treeitem", { name: "Europe" });
    europe.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    await screen.findByText("Couldn't load the regions under Nordics.");
  },
};

export const Empty: Story = { parameters: treeStoryBackend({ regions: [] }) };

export const ServerError: Story = { parameters: treeStoryBackend({ treeFailure: 500 }) };

export const Forbidden: Story = { parameters: treeStoryBackend({ treeFailure: 403 }) };

export const Offline: Story = { parameters: treeStoryBackend({ treeFailure: "offline" }) };

/** An ordered tree (a product catalog's categories). */
export const Ordered: Story = { args: { resource: "categories" } };
