import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { detailBackend, DEMO_EVENT_ID } from "../testapp-fixtures";
import { ChangeHistory } from "./ChangeHistory";

/** msw serves `/api/events/<id>/history/`, one story per state. */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <div className="max-w-2xl">{props.children}</div>
    </KarniProvider>
  );
}

const meta = {
  title: "Resource/ChangeHistory",
  component: ChangeHistory,
  tags: ["autodocs"],
  args: { resource: "events", id: DEMO_EVENT_ID },
  parameters: { msw: { handlers: detailBackend() } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof ChangeHistory>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Newest first. An emptied value is the shared dash, and a redacted one says so. */
export const Entries: Story = {};

/** Slow: after 500ms the placeholders draw the entries' layout. */
export const Loading: Story = {
  parameters: { msw: { handlers: detailBackend({ history: "pending" }) } },
};

export const Empty: Story = {
  parameters: {
    msw: {
      handlers: detailBackend({
        historyPage: { count: 0, next: null, previous: null, results: [] },
      }),
    },
  },
};

export const Forbidden: Story = {
  parameters: { msw: { handlers: detailBackend({ history: { status: 403, body: {} } }) } },
};

/** The model does not keep history: the backend's 404 says how to opt in. */
export const NotAudited: Story = {
  parameters: {
    msw: {
      handlers: detailBackend({
        history: {
          status: 404,
          body: {
            detail:
              "No history is kept for Event: opt in with `class Karni: audit = True` on the model.",
          },
        },
      }),
    },
  },
};

export const ServerError: Story = {
  parameters: { msw: { handlers: detailBackend({ history: { status: 500, body: {} } }) } },
};

export const Offline: Story = {
  parameters: { msw: { handlers: detailBackend({ history: "network" }) } },
};
