import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { userEvent, waitFor, within } from "storybook/test";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Button } from "../../primitives/button";
import {
  detailBackend,
  DEMO_EVENT_ID,
  eventHiding,
  openApiHidingEventFields,
  SCOPED_NOT_FOUND,
} from "../testapp-fixtures";
import { ResourceDetail } from "./ResourceDetail";

/**
 * Every story runs against msw handlers serving the backend's own OpenAPI
 * snapshot (the testapp's Event), one story per state.
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <div className="max-w-3xl">{props.children}</div>
    </KarniProvider>
  );
}

const back = (
  <Button variant="outline" size="sm">
    Back to events
  </Button>
);

const meta = {
  title: "Resource/ResourceDetail",
  component: ResourceDetail,
  tags: ["autodocs"],
  args: {
    resource: "events",
    id: DEMO_EVENT_ID,
    expand: ["venue"],
    title: (item: Record<string, unknown>) => String(item["title"]),
    back,
    onEdit: () => undefined,
    enableDelete: true,
  },
  parameters: { msw: { handlers: detailBackend() } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof ResourceDetail>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Every readable field; empty values (description, organizer, tags) are the shared dash. */
export const Loaded: Story = {};

/** Slow: after 500ms the placeholder draws the record's own layout, header included. */
export const Loading: Story = {
  parameters: { msw: { handlers: detailBackend({ event: "pending" }) } },
};

/** A role `Karni.field_roles` hides capacity and description from: no rows, no hint. */
export const PartialPermission: Story = {
  parameters: {
    msw: {
      handlers: detailBackend({
        openApi: openApiHidingEventFields(["capacity", "description"]),
        record: eventHiding(["capacity", "description"]),
      }),
    },
  },
};

/** Edit and Delete only for roles that may: here the role may do neither. */
export const ReadOnlyRole: Story = {
  args: { canEdit: false, canDelete: false },
};

/** 404, also what Karni answers for a row outside the user's scope. */
export const NotFound: Story = {
  parameters: { msw: { handlers: detailBackend({ event: SCOPED_NOT_FOUND }) } },
};

export const Forbidden: Story = {
  parameters: { msw: { handlers: detailBackend({ event: { status: 403, body: {} } }) } },
};

export const ServerError: Story = {
  parameters: { msw: { handlers: detailBackend({ event: { status: 500, body: {} } }) } },
};

/** The schema itself failed: "Try again" refetches it. */
export const SchemaError: Story = {
  parameters: { msw: { handlers: detailBackend({ schema: { status: 503, body: {} } }) } },
};

export const Offline: Story = {
  parameters: { msw: { handlers: detailBackend({ event: "network" }) } },
};

async function openDelete(canvasElement: HTMLElement): Promise<void> {
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByRole("button", { name: "Delete" }));
}

async function confirmDelete(): Promise<void> {
  const body = within(document.body);
  const dialog = await body.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
}

export const DeleteConfirm: Story = {
  play: async ({ canvasElement }) => {
    await openDelete(canvasElement);
  },
};

export const DeleteRefused: Story = {
  parameters: { msw: { handlers: detailBackend({ remove: { status: 403, body: {} } }) } },
  play: async ({ canvasElement }) => {
    await openDelete(canvasElement);
    await confirmDelete();
    await waitFor(() => within(document.body).getByRole("alert"));
  },
};

export const DeletePending: Story = {
  parameters: { msw: { handlers: detailBackend({ remove: "pending" }) } },
  play: async ({ canvasElement }) => {
    await openDelete(canvasElement);
    await confirmDelete();
  },
};

export const Deleted: Story = {
  play: async ({ canvasElement }) => {
    await openDelete(canvasElement);
    await confirmDelete();
    await within(canvasElement).findByText("The event was deleted");
  },
};
