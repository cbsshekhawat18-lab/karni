import type { Meta, StoryObj } from "@storybook/react";
import { MarkdownView } from "./markdown-view";

const source = `# Product notes

The **Garden range** ships in spring. See the [catalog](/catalog) or the
[supplier's site](https://example.com/garden).

- Seeds and bulbs
- Tools, with \`SKU-1042\` as the bestseller

| Item | Stock |
|---|---:|
| Rake | 40 |
| Hose | 12 |

> Prices include tax.

\`\`\`
order --region north
\`\`\`
`;

const meta = {
  title: "Blocks/MarkdownView",
  component: MarkdownView,
  tags: ["autodocs"],
  args: { source },
} satisfies Meta<typeof MarkdownView>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Headings, links, lists, a table, a quote and code. `#` renders as an h2 under the page title. */
export const Formatted: Story = {};

/** Raw HTML shows as text unless allowHtml, and a script never runs either way. */
export const RawHtml: Story = {
  args: {
    source: 'A <em>styled</em> word and <img src="x" onerror="alert(1)"> an image.',
  },
};

/** With allowHtml the safe HTML renders and the event handler is gone. */
export const AllowHtml: Story = {
  args: {
    source: 'A <em>styled</em> word and <img src="x" alt="Broken image" onerror="alert(1)">.',
    allowHtml: true,
  },
};
