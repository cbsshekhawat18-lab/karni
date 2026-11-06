import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { createKarniClient, KarniApiError } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthContext, type AuthContextValue } from "./provider";
import { defaultTermsGateSlots, TermsGate } from "./TermsGate";
import type { AuthStatus, AuthTerms, KarniUser } from "./types";

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["attendee"] };
const TERMS: AuthTerms = {
  version: "2026-11",
  url: "https://example.com/terms/",
  required: true,
  accepted: false,
};

type Accept = (terms: AuthTerms) => Promise<AuthTerms>;

/** Records the acceptance after a short pause, the way the server answers. */
const accepts: Accept = (terms) =>
  new Promise((resolve) => setTimeout(() => resolve({ ...terms, accepted: true }), 600));

/** A stateful auth context: accepting flips `termsRequired`, as AuthProvider does. */
function Providers(props: {
  status?: AuthStatus;
  terms?: AuthTerms;
  accept?: Accept;
  children: React.ReactNode;
}): React.ReactElement {
  const { status = "authenticated", accept = accepts } = props;
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient(),
  }));
  const [terms, setTerms] = React.useState<AuthTerms>(props.terms ?? TERMS);
  const value: AuthContextValue = {
    user: status === "authenticated" ? USER : null,
    roles: USER.roles,
    status,
    login: () => new Promise(() => undefined),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
    terms,
    termsRequired: terms.required && !terms.accepted,
    acceptTerms: async () => {
      const accepted = await accept(terms);
      setTerms(accepted);
      return accepted;
    },
  };
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <AuthContext.Provider value={value}>{props.children}</AuthContext.Provider>
    </KarniProvider>
  );
}

const app = <p className="text-sm">The organizer dashboard.</p>;

const meta = {
  title: "Auth/TermsGate",
  component: TermsGate,
  tags: ["autodocs"],
  args: { children: app },
} satisfies Meta<typeof TermsGate>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The user has not accepted the current version: a link to the terms and the accept button. */
export const Required: Story = {
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
};

/** `embed` shows the terms in a frame (the page must allow being framed), with the link below. */
export const Embedded: Story = {
  args: { embed: true },
  decorators: Required.decorators,
};

/** Accepting never finishes here: the button stays busy and says so to screen readers. */
export const Accepting: Story = {
  decorators: [
    (Story) => (
      <Providers accept={() => new Promise(() => undefined)}>
        <Story />
      </Providers>
    ),
  ],
};

/** The terms changed again while the page was open (E246): accepting shows why it failed. */
export const ChangedAgain: Story = {
  decorators: [
    (Story) => (
      <Providers
        accept={() =>
          Promise.reject(
            new KarniApiError(400, { code: "E246", version: "2027-01", url: TERMS.url }),
          )
        }
      >
        <Story />
      </Providers>
    ),
  ],
};

/** The panel with a failed attempt, as the `Panel` slot receives it. */
export const PanelWithError: Story = {
  render: () => (
    <defaultTermsGateSlots.Panel
      terms={TERMS}
      accept={() => undefined}
      accepting={false}
      error={{
        kind: "offline",
        title: "You're offline",
        description: "Check your connection, then try again.",
        retryable: true,
      }}
      embed={false}
      title="Terms of use"
      description="Read the terms (version 2026-11) and accept them to continue."
      acceptLabel="Accept and continue"
      page={false}
    />
  ),
};

/** Accepted, or the server asks for no terms: the children render. */
export const Accepted: Story = {
  decorators: [
    (Story) => (
      <Providers terms={{ ...TERMS, accepted: true }}>
        <Story />
      </Providers>
    ),
  ],
};

/** While the auth status loads, `loading` renders (nothing by default). */
export const Loading: Story = {
  args: { loading: <p className="text-sm text-muted-foreground">Loading…</p> },
  decorators: [
    (Story) => (
      <Providers status="loading">
        <Story />
      </Providers>
    ),
  ],
};
