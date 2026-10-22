import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { delay, http, HttpResponse, type RequestHandler } from "msw";
import * as React from "react";
import { userEvent, within } from "storybook/test";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { LoginForm } from "./LoginForm";
import { AuthProvider } from "./provider";
import { createMemoryTokenStorage } from "./storage";

/** The real AuthProvider against msw: each story answers `POST /api/auth/login/` its own way. */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    storage: createMemoryTokenStorage(),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <AuthProvider mode="jwt" tokenStorage={context.storage}>
        <div className="max-w-96">{props.children}</div>
      </AuthProvider>
    </KarniProvider>
  );
}

function login(answer: () => Response | Promise<Response>): RequestHandler[] {
  return [http.post("*/api/auth/login/", answer)];
}

const meta = {
  title: "Auth/LoginForm",
  component: LoginForm,
  tags: ["autodocs"],
  args: { description: "Use the email you registered with." },
  parameters: {
    msw: {
      handlers: login(() =>
        HttpResponse.json(
          { detail: "No active account found with the given credentials" },
          { status: 401 },
        ),
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
} satisfies Meta<typeof LoginForm>;

export default meta;
type Story = StoryObj<typeof meta>;

async function submit(canvasElement: HTMLElement): Promise<void> {
  const canvas = within(canvasElement);
  await userEvent.type(canvas.getByLabelText("Email"), "ada@example.com");
  await userEvent.type(canvas.getByLabelText("Password"), "not-my-password");
  await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
}

async function failed(canvasElement: HTMLElement): Promise<void> {
  await submit(canvasElement);
  await within(canvasElement).findByRole("alert");
}

export const Default: Story = {};

/**
 * Both fields marked invalid and pointing at the message. The email stays and
 * the password is cleared.
 */
export const WrongCredentials: Story = {
  play: async ({ canvasElement }) => failed(canvasElement),
};

export const Throttled: Story = {
  parameters: {
    msw: {
      handlers: login(() =>
        HttpResponse.json(
          { detail: "Request was throttled. Expected available in 42 seconds." },
          { status: 429 },
        ),
      ),
    },
  },
  play: async ({ canvasElement }) => failed(canvasElement),
};

export const ServerError: Story = {
  parameters: { msw: { handlers: login(() => HttpResponse.json({}, { status: 500 })) } },
  play: async ({ canvasElement }) => failed(canvasElement),
};

export const Offline: Story = {
  parameters: { msw: { handlers: login(() => HttpResponse.error()) } },
  play: async ({ canvasElement }) => failed(canvasElement),
};

/** Slow: after 500ms the button shows progress, keeping its width. */
export const Submitting: Story = {
  parameters: {
    msw: {
      handlers: login(async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    },
  },
  play: async ({ canvasElement }) => submit(canvasElement),
};
