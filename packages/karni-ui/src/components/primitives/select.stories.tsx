import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Select, type SelectOption } from "./select";

const statusOptions: readonly SelectOption[] = [
  { value: "draft", label: "Draft" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived", disabled: true },
];

/** Controlled wrapper so stories reflect selection state. */
function ControlledSelect(
  props: Omit<React.ComponentProps<typeof Select>, "value" | "onValueChange">,
): React.ReactElement {
  const [value, setValue] = React.useState<string | null>(null);
  return (
    <div className="grid w-64 gap-2">
      <Select {...props} value={value} onValueChange={setValue} />
      <p className="text-sm text-muted-foreground">
        Selected: <code>{value === null ? "null" : value}</code>
      </p>
    </div>
  );
}

const meta = {
  title: "Primitives/Select",
  component: Select,
  tags: ["autodocs"],
  args: {
    value: null,
    options: statusOptions,
    placeholder: "Pick a status",
  },
} satisfies Meta<typeof Select>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  render: (args) => <ControlledSelect options={args.options} placeholder={args.placeholder} />,
};

/**
 * `clearable` renders a clear item at the top of the list (contract D8);
 * choosing it emits `null` — the `"__karni_empty__"` sentinel never leaks
 * out of the component.
 */
export const Clearable: Story = {
  render: (args) => (
    <ControlledSelect
      options={args.options}
      placeholder={args.placeholder}
      clearable
      clearLabel="All statuses"
    />
  ),
};

export const Disabled: Story = {
  args: { disabled: true },
};
