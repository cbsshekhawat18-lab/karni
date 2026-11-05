import type { Meta, StoryObj } from "@storybook/react";
import { TreeStoryProviders, treeStoryBackend } from "./tree-stories-support";
import { TreeBreadcrumb } from "./TreeBreadcrumb";

/** The path above a node of a region tree, against msw handlers. */
const meta = {
  title: "Resource/TreeBreadcrumb",
  component: TreeBreadcrumb,
  args: { resource: "regions", id: 10, item: { id: 10, name: "Kyoto" } },
  parameters: treeStoryBackend(),
  decorators: [
    (Story) => (
      <TreeStoryProviders>
        <Story />
      </TreeStoryProviders>
    ),
  ],
} satisfies Meta<typeof TreeBreadcrumb>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Path: Story = {};

/** Ancestors linked to their detail pages. */
export const Links: Story = {
  args: { href: (node: Record<string, unknown>) => `#/regions/${String(node["id"])}` },
};

/** A root has no path: nothing renders. */
export const Root: Story = { args: { id: 1, item: { id: 1, name: "Europe" } } };

export const Loading: Story = {
  parameters: treeStoryBackend({ ancestorsDelay: "infinite" }),
};

export const Failed: Story = { parameters: treeStoryBackend({ ancestorsFailure: 500 }) };
