import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { delay, http, HttpResponse, type RequestHandler } from "msw";
import * as React from "react";
import { userEvent, within } from "storybook/test";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthProvider } from "./provider";
import { SocialButton } from "./SocialButton";
import { createMemoryTokenStorage } from "./storage";

/**
 * The real AuthProvider against msw: each story answers
 * `POST /api/auth/social/google/` its own way. `getIdToken` stands in for the
 * app's call into the provider's SDK.
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    storage: createMemoryTokenStorage(),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <AuthProvider mode="jwt" tokenStorage={context.storage}>
        <div className="max-w-80">{props.children}</div>
      </AuthProvider>
    </KarniProvider>
  );
}

function social(answer: () => Response | Promise<Response>): RequestHandler[] {
  return [http.post("*/api/auth/social/:provider/", answer)];
}

function refusal(status: number, code: string): () => Response {
  return () => HttpResponse.json({ code, detail: `${code}: refused` }, { status });
}

const meta = {
  title: "Auth/SocialButton",
  component: SocialButton,
  tags: ["autodocs", "experimental"],
  args: {
    provider: "google",
    getIdToken: () => Promise.resolve("id-token-from-the-provider-sdk"),
  },
  parameters: {
    msw: {
      handlers: social(() =>
        HttpResponse.json({
          access: "a",
          refresh: "r",
          user: { id: 1, email: "ada@example.com", roles: [] },
        }),
      ),
    },
  },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof SocialButton>;

export default meta;
type Story = StoryObj<typeof meta>;

async function press(canvasElement: HTMLElement): Promise<void> {
  const canvas = within(canvasElement);
  await userEvent.click(canvas.getByRole("button"));
}

export const Default: Story = {};

export const Microsoft: Story = { args: { provider: "microsoft" } };

export const Apple: Story = {
  args: { provider: "apple", label: "Sign in with Apple", variant: "default" },
};

/** Slow: after 500ms the button shows progress, keeping its width. */
export const Signing: Story = {
  parameters: {
    msw: {
      handlers: social(async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    },
  },
  play: async ({ canvasElement }) => press(canvasElement),
};

/** A new account under the `approval` policy: a status, not an error. */
export const AwaitingApproval: Story = {
  parameters: {
    msw: {
      handlers: social(() =>
        HttpResponse.json(
          { code: "E224", detail: "E224: awaits approval", awaiting_approval: true },
          { status: 202 },
        ),
      ),
    },
  },
  play: async ({ canvasElement }) => {
    await press(canvasElement);
    await within(canvasElement).findByText("Your account is waiting for approval");
  },
};

export const EmailNotVerified: Story = {
  parameters: { msw: { handlers: social(refusal(400, "E222")) } },
  play: async ({ canvasElement }) => {
    await press(canvasElement);
    await within(canvasElement).findByRole("alert");
  },
};

export const SignUpClosed: Story = {
  parameters: { msw: { handlers: social(refusal(400, "E223")) } },
  play: async ({ canvasElement }) => {
    await press(canvasElement);
    await within(canvasElement).findByRole("alert");
  },
};

export const Offline: Story = {
  parameters: { msw: { handlers: social(() => HttpResponse.error()) } },
  play: async ({ canvasElement }) => {
    await press(canvasElement);
    await within(canvasElement).findByRole("alert");
  },
};
