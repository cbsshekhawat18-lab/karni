import type { Meta, StoryObj } from "@storybook/react";
import { ThemeProvider, ThemeToggle } from "./theme";

const meta = {
  title: "Support/ThemeToggle",
  component: ThemeToggle,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      // A separate storage key, so the story never changes Storybook's own theme choice.
      <ThemeProvider storageKey="karni-theme-story" target={() => document.createElement("div")}>
        <Story />
      </ThemeProvider>
    ),
  ],
} satisfies Meta<typeof ThemeToggle>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
