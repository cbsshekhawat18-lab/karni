import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../components/primitives/button";
import { KarniApiError } from "../schema/client";
import { ErrorState, PermissionDenied } from "./ErrorState";
import { PendingButton } from "./PendingButton";

const meta = {
  title: "States/ErrorState",
  component: ErrorState,
  tags: ["autodocs"],
  args: { error: new KarniApiError(503, {}), onRetry: () => undefined },
} satisfies Meta<typeof ErrorState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ServerError: Story = {};

export const Forbidden: Story = {
  args: {
    error: new KarniApiError(403, {}),
    context: { action: "delete", resource: "events" },
  },
};

export const NotFound: Story = {
  args: { error: new KarniApiError(404, {}), context: { resource: "this event" } },
};

export const Offline: Story = {
  args: { error: new TypeError("Failed to fetch") },
};

export const WithServerDetail: Story = {
  args: {
    error: new KarniApiError(409, { detail: "The event was edited by Asha at 10:42." }),
  },
};

export const Retrying: Story = {
  args: { retrying: true },
};

export const Inline: Story = {
  args: { variant: "inline", error: new KarniApiError(500, {}) },
};

export const Permission: Story = {
  render: () => (
    <PermissionDenied
      action="create"
      resource="events"
      actions={
        <Button variant="outline" size="sm">
          Back to the list
        </Button>
      }
    />
  ),
};

export const PendingButtons: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <PendingButton>Save changes</PendingButton>
      <PendingButton pending pendingLabel="Saving…">
        Save changes
      </PendingButton>
      <PendingButton variant="destructive" pending pendingLabel="Deleting…">
        Delete
      </PendingButton>
    </div>
  ),
};
