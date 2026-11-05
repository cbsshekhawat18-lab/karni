import type { Meta, StoryObj } from "@storybook/react";
import { Accordion, type AccordionItem } from "./accordion";

const items: AccordionItem[] = [
  {
    id: "shipping",
    title: "Shipping",
    content: <p>Orders leave the warehouse within two working days.</p>,
  },
  {
    id: "returns",
    title: "Returns",
    content: <p>Unused items can be returned within 30 days for a full refund.</p>,
  },
  {
    id: "warranty",
    title: "Warranty",
    content: <p>Every product carries a two-year warranty against defects.</p>,
  },
  { id: "archived", title: "Archived policy", content: <p>No longer applies.</p>, disabled: true },
];

const meta = {
  title: "Blocks/Accordion",
  component: Accordion,
  tags: ["autodocs"],
  args: { items, defaultOpen: ["shipping"] },
  argTypes: { type: { control: "select", options: ["multiple", "single"] } },
} satisfies Meta<typeof Accordion>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Any number of sections open at once (the default). */
export const Multiple: Story = {};

/** One section open at a time, and the open one stays open. */
export const Single: Story = { args: { type: "single", collapsible: false } };
