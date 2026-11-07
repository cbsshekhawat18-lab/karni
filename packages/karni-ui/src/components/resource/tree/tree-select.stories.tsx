import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { screen, userEvent } from "storybook/test";
import { Label } from "../../primitives/label";
import { TreeStoryProviders, treeStoryBackend } from "./tree-stories-support";
import { TreeSelect, type TreeSelectProps } from "./TreeSelect";

/**
 * TreeSelect in a labelled field, holding its value like a form would,
 * against msw handlers that simulate a Karni region tree.
 */
type FieldArgs = Omit<TreeSelectProps, "onChange"> & { label?: string; error?: string };

function Field(args: FieldArgs): React.ReactElement {
  const { label = "Region", error, value: initial, ...rest } = args;
  const [value, setValue] = React.useState(initial);
  const errorId = error !== undefined ? "region-error" : undefined;
  return (
    <div className="max-w-sm [&>:not([hidden])~:not([hidden])]:mt-2">
      <Label htmlFor="region" id="region-label">
        {label}
      </Label>
      <TreeSelect
        id="region"
        aria-labelledby="region-label"
        {...rest}
        value={value}
        onChange={setValue}
        aria-describedby={errorId}
        aria-invalid={error !== undefined || undefined}
      />
      {error !== undefined ? (
        <p id={errorId} className="text-sm font-medium text-foreground">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const meta = {
  title: "Resource/TreeSelect",
  component: Field,
  args: { resource: "regions", value: null },
  parameters: treeStoryBackend(),
  decorators: [
    (Story) => (
      <TreeStoryProviders>
        <Story />
      </TreeStoryProviders>
    ),
  ],
} satisfies Meta<typeof Field>;

export default meta;
type Story = StoryObj<typeof meta>;

async function open(): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Region/ }));
  await screen.findByRole("tree");
}

export const Closed: Story = {};

export const Open: Story = { play: open };

/** A deep value is labelled from the API, and the tree opens at it. */
export const Preselected: Story = { args: { value: 10 }, play: open };

export const Multiple: Story = { args: { value: [3, 9], multiple: true, label: "Regions" } };

/** A value whose node cannot be loaded (deleted, or hidden from this role) says so. */
export const UnloadableValue: Story = { args: { value: 999 } };

export const Invalid: Story = { args: { error: "Choose the region the store is in." } };

export const Disabled: Story = { args: { value: 3, disabled: true } };

/** An ordered category tree, as a product form shows it. */
export const Category: Story = { args: { resource: "categories", label: "Category" } };
