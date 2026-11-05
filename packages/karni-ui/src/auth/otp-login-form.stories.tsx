import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { delay, http, HttpResponse, type RequestHandler } from "msw";
import * as React from "react";
import { userEvent, within } from "storybook/test";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { OtpLoginForm } from "./OtpLoginForm";
import { AuthProvider } from "./provider";
import { createMemoryTokenStorage } from "./storage";

/**
 * The real AuthProvider against msw: `POST /api/auth/otp/send/` always answers
 * the same, and each story answers `POST /api/auth/otp/verify/` its own way.
 * The code that works is 246810.
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
        <div className="max-w-96">{props.children}</div>
      </AuthProvider>
    </KarniProvider>
  );
}

function otp(verify: () => Response | Promise<Response>): RequestHandler[] {
  return [
    http.post("*/api/auth/otp/send/", () =>
      HttpResponse.json({
        detail: "If this address may sign in, a sign-in code is on its way to it.",
        length: 6,
        expires_in: 600,
      }),
    ),
    http.post("*/api/auth/otp/verify/", verify),
  ];
}

function refusal(status: number, code: string): () => Response {
  return () => HttpResponse.json({ code, detail: `${code}: refused` }, { status });
}

const meta = {
  title: "Auth/OtpLoginForm",
  component: OtpLoginForm,
  tags: ["autodocs", "experimental"],
  args: { description: "We email you a code. No password needed." },
  parameters: {
    msw: {
      handlers: otp(() =>
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
} satisfies Meta<typeof OtpLoginForm>;

export default meta;
type Story = StoryObj<typeof meta>;

async function toCodeStep(canvasElement: HTMLElement): Promise<void> {
  const canvas = within(canvasElement);
  await userEvent.type(canvas.getByLabelText("Email"), "ada@example.com");
  await userEvent.click(canvas.getByRole("button", { name: "Send the code" }));
  await canvas.findByLabelText("Code");
}

async function enter(canvasElement: HTMLElement, code: string): Promise<void> {
  const canvas = within(canvasElement);
  await toCodeStep(canvasElement);
  await userEvent.type(canvas.getByLabelText("Code"), code);
  await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
}

export const Default: Story = {};

/** The code step: one input for the whole code, a resend button that waits 30 seconds. */
export const CodeStep: Story = {
  play: async ({ canvasElement }) => toCodeStep(canvasElement),
};

/** A shorter cooldown, a prop. */
export const ShortCooldown: Story = {
  args: { resendCooldown: 5 },
  play: async ({ canvasElement }) => toCodeStep(canvasElement),
};

export const WrongCode: Story = {
  parameters: { msw: { handlers: otp(refusal(401, "E235")) } },
  play: async ({ canvasElement }) => {
    await enter(canvasElement, "000000");
    await within(canvasElement).findByRole("alert");
  },
};

/** A new account under the `approval` policy: a status, not an error. */
export const AwaitingApproval: Story = {
  parameters: {
    msw: {
      handlers: otp(() =>
        HttpResponse.json(
          { code: "E224", detail: "E224: awaits approval", awaiting_approval: true },
          { status: 202 },
        ),
      ),
    },
  },
  play: async ({ canvasElement }) => {
    await enter(canvasElement, "246810");
    await within(canvasElement).findByText("Your account is waiting for approval");
  },
};

export const InactiveAccount: Story = {
  parameters: { msw: { handlers: otp(refusal(401, "E226")) } },
  play: async ({ canvasElement }) => {
    await enter(canvasElement, "246810");
    await within(canvasElement).findByRole("alert");
  },
};

/** Slow: after 500ms the button shows progress, keeping its width. */
export const Verifying: Story = {
  parameters: {
    msw: {
      handlers: otp(async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    },
  },
  play: async ({ canvasElement }) => enter(canvasElement, "246810"),
};
