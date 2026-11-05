import { KarniProvider, createKarniClient } from "@karni/ui";
import type { Meta, StoryObj } from "@storybook/react";
import { ProtectedFileLink } from "./ProtectedFileLink";

const client = createKarniClient({
  baseUrl: "/api",
  fetch: async () =>
    new Response(
      JSON.stringify({
        url: "https://bucket.example.test/guide.pdf",
        expires_in: 300,
        name: "guide.pdf",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
});

const meta = {
  title: "Storage/ProtectedFileLink",
  component: ProtectedFileLink,
  tags: ["autodocs"],
  args: {
    href: "/api/products/7/files/manual/",
    children: "Manual (PDF)",
    open: (url: string) => {
      window.alert(`Would open ${url}`);
    },
  },
  decorators: [
    (Story) => (
      <KarniProvider client={client}>
        <Story />
      </KarniProvider>
    ),
  ],
} satisfies Meta<typeof ProtectedFileLink>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OpensASignedLink: Story = {};

export const Download: Story = { args: { download: true, children: "Download the manual" } };
