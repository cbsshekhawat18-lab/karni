import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Button } from "./button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./dropdown-menu";

const meta = {
  title: "Primitives/DropdownMenu",
  component: DropdownMenu,
  tags: ["autodocs"],
} satisfies Meta<typeof DropdownMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

function RowActionsDemo(props: { defaultOpen?: boolean }): React.ReactElement {
  const [archived, setArchived] = React.useState(false);
  return (
    <DropdownMenu defaultOpen={props.defaultOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">Row actions</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Actions</DropdownMenuLabel>
        <DropdownMenuItem>Edit</DropdownMenuItem>
        <DropdownMenuItem>Duplicate</DropdownMenuItem>
        <DropdownMenuCheckboxItem checked={archived} onCheckedChange={setArchived}>
          Archived
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive focus:text-destructive">
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const Playground: Story = {
  render: () => <RowActionsDemo />,
};

/**
 * Open on load. The arrow keys move through the items, Enter or Space runs
 * one, typing jumps to an item, Escape closes and returns focus to the trigger.
 */
export const Open: Story = {
  render: () => <RowActionsDemo defaultOpen />,
};
