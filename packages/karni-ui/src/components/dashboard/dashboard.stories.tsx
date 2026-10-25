import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { handlers } from "../../../tests/msw/handlers";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { Dashboard } from "./dashboard";

/**
 * The msw backend's Event resource declares a dashboard (tests/msw/openapi.ts),
 * the way `class Karni: dashboard = {...}` publishes one.
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
      <div className="max-w-4xl">{props.children}</div>
    </KarniProvider>
  );
}

const meta = {
  title: "Resource/Dashboard",
  component: Dashboard,
  tags: ["autodocs"],
  args: {
    now: () => new Date(2026, 9, 12),
  },
  parameters: { msw: { handlers } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof Dashboard>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Counts and the newest rows of every model that opts in. */
export const Default: Story = {};

/** The tiles open the list with their filters, and a row opens the record. */
export const Navigating: Story = {
  args: {
    onOpen: (resource, row) => window.alert(`${resource} ${String(row["id"])}`),
    onOpenList: (resource, filters) => window.alert(`${resource} ${JSON.stringify(filters)}`),
  },
};

/** Only the resources named, in that order. */
export const Chosen: Story = {
  args: { resources: ["events"] },
};
