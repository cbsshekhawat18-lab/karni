import { KarniProvider, createKarniClient } from "@karni/ui";
import type { Meta, StoryObj } from "@storybook/react";
import { PaymentStatus } from "./PaymentStatus";
import { PAYMENT_STATUSES } from "./types";

/**
 * The stubbed client derives the payment's status from the requested id, so
 * one client serves every story (`paymentId="succeeded"` → status succeeded).
 */
const client = createKarniClient({
  baseUrl: "/api",
  fetch: async (input) => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const id = /\/payments\/([^/]+)\//.exec(url)?.[1] ?? "pending";
    return new Response(
      JSON.stringify({
        id,
        amount: "49.00",
        currency: "usd",
        status: decodeURIComponent(id),
        provider: "test",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  },
});

const meta = {
  title: "Payments/PaymentStatus",
  component: PaymentStatus,
  tags: ["autodocs"],
  args: {
    paymentId: "succeeded",
    poll: false,
  },
  decorators: [
    (Story) => (
      <KarniProvider client={client}>
        <Story />
      </KarniProvider>
    ),
  ],
} satisfies Meta<typeof PaymentStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const AllStatuses: Story = {
  render: () => (
    <div className="flex flex-col items-start gap-3">
      {PAYMENT_STATUSES.map((status) => (
        <PaymentStatus key={status} paymentId={status} />
      ))}
    </div>
  ),
};

export const Polling: Story = {
  args: { paymentId: "processing", poll: 2000 },
};

export const CustomRendering: Story = {
  render: () => (
    <PaymentStatus paymentId="succeeded" statusLabels={{ succeeded: "Paid" }}>
      {(payment) => (
        <span className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-card-foreground">
          Payment {payment.id}: {payment.status} ({payment.amount} {payment.currency.toUpperCase()})
        </span>
      )}
    </PaymentStatus>
  ),
};
