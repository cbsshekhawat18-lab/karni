import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { handlers } from "../../../tests/msw/handlers";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { Layout } from "../layout/layout";
import { GlobalSearch } from "./global-search";

/**
 * The msw backend answers GET /api/search/ over its events and venues, the way
 * Karni does for every model with `class Karni: search`. Type "hall".
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      {props.children}
    </KarniProvider>
  );
}

const meta = {
  title: "App shell/GlobalSearch",
  component: GlobalSearch,
  tags: ["autodocs"],
  parameters: { msw: { handlers } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof GlobalSearch>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The trigger button. Cmd+K (macOS) or Ctrl+K opens the palette too. */
export const Default: Story = {};

/** Open, before anything is typed: it says how many characters it needs. */
export const Open: Story = { args: { defaultOpen: true } };

/** Only some resources, and a router of your own choosing where a hit goes. */
export const Narrowed: Story = {
  args: {
    defaultOpen: true,
    models: ["venues"],
    onSelect: (hit) => window.alert(`${hit.resource} ${String(hit.id)}`),
  },
};

/** Mounted by the app shell: `<Layout search>`. */
export const InLayout: Story = {
  render: () => (
    <Layout search navItems={[{ label: "Events", href: "/events", active: true }]}>
      <h1 className="text-2xl font-semibold">Events</h1>
    </Layout>
  ),
};
