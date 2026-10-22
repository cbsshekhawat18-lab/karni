import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Button } from "../components/primitives/button";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthGuard } from "./AuthGuard";
import { AuthContext, type AuthContextValue } from "./provider";
import type { AuthStatus, KarniUser } from "./types";

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["attendee"] };

function auth(status: AuthStatus, user: KarniUser | null): AuthContextValue {
  return {
    user,
    roles: user?.roles ?? [],
    status,
    login: () => new Promise(() => undefined),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
  };
}

/** A fixed auth state per story (the guard only reads it). */
function Providers(props: {
  value: AuthContextValue;
  children: React.ReactNode;
}): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient(),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <AuthContext.Provider value={props.value}>{props.children}</AuthContext.Provider>
    </KarniProvider>
  );
}

const content = <p className="text-sm">The organizer dashboard.</p>;

const meta = {
  title: "Auth/AuthGuard",
  component: AuthGuard,
  tags: ["autodocs"],
  args: { roles: ["organizer"], children: content },
} satisfies Meta<typeof AuthGuard>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Not signed in: a sign-in prompt. Signing in reveals the content in place. */
export const Anonymous: Story = {
  decorators: [
    (Story) => (
      <Providers value={auth("anonymous", null)}>
        <Story />
      </Providers>
    ),
  ],
};

/** Signed in, but the role lacks access: PermissionDenied, naming who is signed in. */
export const Denied: Story = {
  decorators: [
    (Story) => (
      <Providers value={auth("authenticated", USER)}>
        <Story />
      </Providers>
    ),
  ],
};

/** `denied` replaces only that case's default (as does `anonymous`, and `fallback` covers both). */
export const CustomDenied: Story = {
  args: {
    denied: (
      <div className="space-y-2 text-sm">
        <p>The dashboard is for organizers.</p>
        <Button variant="outline" size="sm">
          Ask to become an organizer
        </Button>
      </div>
    ),
  },
  decorators: Denied.decorators,
};

export const Allowed: Story = {
  args: { roles: ["attendee"] },
  decorators: Denied.decorators,
};
