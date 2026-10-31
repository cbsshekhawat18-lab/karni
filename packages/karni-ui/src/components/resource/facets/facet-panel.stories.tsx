import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { ResourceTable } from "../table/ResourceTable";
import type { ProductRow } from "../tree/tree-backend";
import { TreeStoryProviders, treeStoryBackend } from "../tree/tree-stories-support";
import { FacetPanel, type FacetPanelProps } from "./FacetPanel";

/**
 * FacetPanel (experimental) holding its choice like a page would, against
 * msw handlers that simulate a product catalog tagged to a region tree
 * (`class Karni: taxonomies`).
 */
type PanelArgs = Omit<FacetPanelProps, "onChange">;

function Panel(args: PanelArgs): React.ReactElement {
  const { value: initial, ...rest } = args;
  const [value, setValue] = React.useState<ReadonlyArray<string | number>>(initial);
  return (
    <div className="max-w-xs">
      <FacetPanel {...rest} value={value} onChange={setValue} />
    </div>
  );
}

function catalog(): ProductRow[] {
  return [
    { id: 1, name: "Trowel", category: 2, regions: [3] },
    { id: 2, name: "Rake", category: 2, regions: [3, 4] },
    { id: 3, name: "Seeds", category: 3, regions: [7] },
    { id: 4, name: "Knife", category: 5, regions: [9] },
    { id: 5, name: "Hose", category: 2, regions: [] },
  ];
}

const meta = {
  title: "Resource/FacetPanel",
  component: Panel,
  args: { resource: "products", taxonomy: "regions", label: "Regions", value: [] },
  parameters: treeStoryBackend({ taxonomy: true, products: catalog() }),
  decorators: [
    (Story) => (
      <TreeStoryProviders>
        <Story />
      </TreeStoryProviders>
    ),
  ],
} satisfies Meta<typeof Panel>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Rolled up: each region counts the products tagged with it or below it. */
export const RolledUp: Story = {};

/** Only the regions a product is tagged with. */
export const Tagged: Story = { args: { rollup: false } };

export const Chosen: Story = { args: { value: [2] } };

/** The other filters of the list leave no product to count. */
export const NothingToCount: Story = { args: { query: { search: "nothing" } } };

export const Failed: Story = {
  parameters: treeStoryBackend({ taxonomy: true, products: catalog(), facetsFailure: 500 }),
};

export const Loading: Story = {
  parameters: treeStoryBackend({ taxonomy: true, products: catalog(), treeDelay: "infinite" }),
};

/** ResourceTable with `facets`: choosing a region filters the table to the products under it. */
export const InATable: Story = {
  render: () => <ResourceTable resource="products" facets syncUrl={false} />,
};
