import { KarniProvider, createKarniClient } from "@karni/ui";
import type { Meta, StoryObj } from "@storybook/react";
import { CheckoutButton } from "./CheckoutButton";

/**
 * Stories run against a stubbed KarniClient (the client's injectable `fetch`),
 * so no backend or MSW worker is needed; `navigate` is injected so the story
 * canvas never actually leaves the page.
 */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const successClient = createKarniClient({
  baseUrl: "/api",
  fetch: async () =>
    jsonResponse({ id: "cs_story_1", url: "https://pay.example.test/session/cs_story_1" }),
});

const errorClient = createKarniClient({
  baseUrl: "/api",
  fetch: async () => jsonResponse({ detail: "Amount rejected by the checkout validator." }, 400),
});

const meta = {
  title: "Payments/CheckoutButton",
  component: CheckoutButton,
  tags: ["autodocs"],
  args: {
    amount: "49.00",
    currency: "usd",
    successUrl: "https://app.example.test/billing/done",
    cancelUrl: "https://app.example.test/billing/cancel",
    children: "Pay $49.00",
    navigate: (url: string) => {
      window.alert(`Would redirect to ${url}`);
    },
  },
  decorators: [
    (Story) => (
      <KarniProvider client={successClient}>
        <Story />
      </KarniProvider>
    ),
  ],
} satisfies Meta<typeof CheckoutButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const Outline: Story = {
  args: { variant: "outline", children: "Upgrade plan" },
};

export const Disabled: Story = {
  args: { disabled: true },
};

export const ServerError: Story = {
  render: (args) => (
    <KarniProvider client={errorClient}>
      <CheckoutButton
        {...args}
        onError={(error) => {
          window.alert(`Checkout failed: ${String(error)}`);
        }}
      />
    </KarniProvider>
  ),
};
