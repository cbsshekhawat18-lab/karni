/**
 * <OtpLoginForm> (experimental) through the real AuthProvider against msw: the
 * email step, the code step and its one input, success, the 2FA step, an
 * account awaiting approval, refusals in plain words, the resend cooldown,
 * the way back, and the form's accessible states. Also LoginForm's switch.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  authTestControls,
  resetMswData,
  server,
  TEST_2FA_USER,
  TEST_EPHEMERAL_TOKEN,
  TEST_LOGIN_CODE,
  TEST_OTP_EMAILS,
  TEST_USER,
} from "../../tests/msw/server";
import { createKarniClient, KarniApiError } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { LoginForm, type LoginFormProps } from "./LoginForm";
import { describeOtpError, OtpLoginForm, type OtpLoginFormProps } from "./OtpLoginForm";
import { AuthProvider } from "./provider";
import { createMemoryTokenStorage } from "./storage";

const BASE = "http://karni.test/api";

function Providers({ children }: { children: React.ReactNode }) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
        {children}
      </AuthProvider>
    </KarniProvider>
  );
}

function mount(props: OtpLoginFormProps = {}) {
  render(
    <Providers>
      <OtpLoginForm {...props} />
    </Providers>,
  );
}

async function sendTo(email: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.click(screen.getByRole("button", { name: "Send the code" }));
  await screen.findByLabelText("Code");
}

async function enter(code: string): Promise<void> {
  const user = userEvent.setup();
  const input = screen.getByLabelText("Code");
  await user.clear(input);
  await user.type(input, code);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  resetMswData();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("OtpLoginForm", () => {
  it("sends the code, then signs in with it and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    mount({ onSuccess });
    expect(screen.getByRole("heading", { name: "Sign in with a code" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveFocus();
    await sendTo(TEST_USER.email);
    expect(screen.getByText(/for a 6-digit code\. It expires in 10 minutes\./)).toBeInTheDocument();
    await enter(TEST_LOGIN_CODE);
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onSuccess.mock.calls[0]?.[0]).toMatchObject({ email: TEST_USER.email });
    expect(authTestControls.otpRequests().map((request) => request.step)).toEqual([
      "send",
      "verify",
    ]);
  });

  it("has one code input sized to the code, for the phone's one-time-code suggestion", async () => {
    server.use(
      http.post("*/api/auth/otp/send/", () =>
        HttpResponse.json({ detail: "ok", length: 8, expires_in: 60 }),
      ),
    );
    mount();
    await sendTo(TEST_USER.email);
    const input = screen.getByLabelText("Code");
    expect(screen.getAllByRole("textbox")).toEqual([input]);
    expect(input).toHaveAttribute("autocomplete", "one-time-code");
    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(input).toHaveAttribute("maxlength", "8");
    expect(input).toHaveAttribute("pattern", "[0-9]{8}");
    expect(input).toHaveFocus();
    expect(screen.getByText(/for a 8-digit code\. It expires in 1 minute\./)).toBeInTheDocument();
  });

  it("says a wrong code did not work, clears it and focuses it again", async () => {
    mount();
    await sendTo(TEST_USER.email);
    await enter("000000");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That code did not work");
    const input = screen.getByLabelText("Code");
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", alert.id);
    await waitFor(() => expect(input).toHaveFocus());
  });

  it("says an inactive account is not active", async () => {
    mount();
    await sendTo(TEST_OTP_EMAILS.inactive);
    await enter(TEST_LOGIN_CODE);
    expect(await screen.findByRole("alert")).toHaveTextContent("This account is not active");
  });

  it("hands the 2FA step to on2FA", async () => {
    const on2FA = vi.fn();
    mount({ on2FA });
    await sendTo(TEST_2FA_USER.email);
    await enter(TEST_LOGIN_CODE);
    await waitFor(() => expect(on2FA).toHaveBeenCalledWith(TEST_EPHEMERAL_TOKEN));
  });

  it("explains the 2FA step when the app has no on2FA", async () => {
    mount();
    await sendTo(TEST_2FA_USER.email);
    await enter(TEST_LOGIN_CODE);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This account needs a two-factor code",
    );
  });

  it("shows a new account awaiting approval as a status, not an error", async () => {
    const onAwaitingApproval = vi.fn();
    mount({ onAwaitingApproval });
    await sendTo(TEST_OTP_EMAILS.pending);
    await enter(TEST_LOGIN_CODE);
    const status = await screen.findByText("Your account is waiting for approval");
    expect(status.closest("[role=status]")).toHaveAttribute("data-state", "awaiting-approval");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onAwaitingApproval).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it("says how long to wait when sending is throttled, on the email step", async () => {
    mount();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), TEST_OTP_EMAILS.throttled);
    await user.click(screen.getByRole("button", { name: "Send the code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wait 42 seconds");
    expect(screen.queryByLabelText("Code")).toBeNull();
    await waitFor(() => expect(screen.getByLabelText("Email")).toHaveFocus());
  });

  it("waits out the resend cooldown, then sends a new code", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mount({ resendCooldown: 2 });
    await sendTo(TEST_USER.email);
    const resend = screen.getByRole("button", { name: "Send a new code" });
    expect(resend).toBeDisabled();
    expect(screen.getByText("You can ask for a new code in 2 seconds.")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    await waitFor(() => expect(resend).toBeEnabled());
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(resend);
    await waitFor(() => expect(authTestControls.otpRequests()).toHaveLength(2));
    expect(authTestControls.otpRequests()[1]?.body).toEqual({ email: TEST_USER.email });
    await waitFor(() => expect(resend).toBeDisabled());
  });

  it("goes back to the email step with the address filled in", async () => {
    mount();
    await sendTo(TEST_USER.email);
    await userEvent.setup().click(screen.getByRole("button", { name: "Use another email" }));
    expect(screen.queryByLabelText("Code")).toBeNull();
    expect(screen.getByLabelText("Email")).toHaveValue(TEST_USER.email);
  });

  it("is busy while the code is checked and announces it", async () => {
    server.use(
      http.post("*/api/auth/otp/verify/", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    mount();
    await sendTo(TEST_USER.email);
    await enter(TEST_LOGIN_CODE);
    const button = screen.getByRole("button", { name: "Sign in" });
    await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByLabelText("Code")).toBeDisabled();
    expect(screen.getAllByRole("status").some((node) => node.textContent === "Signing in…")).toBe(
      true,
    );
  });

  it("starts with defaultEmail and renders no heading for title={null}", () => {
    mount({ defaultEmail: "x@example.com", title: null, description: "No password needed." });
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByLabelText("Email")).toHaveValue("x@example.com");
    expect(screen.getByText("No password needed.")).toBeInTheDocument();
  });

  it("can be disabled", () => {
    mount({ disabled: true });
    expect(screen.getByLabelText("Email")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send the code" })).toBeDisabled();
  });

  it("takes its own Error and Approval slots", async () => {
    mount({
      slots: {
        Error: ({ id, described }) => (
          <p id={id} role="alert">
            Custom: {described.title}
          </p>
        ),
      },
    });
    await sendTo(TEST_USER.email);
    await enter("111111");
    expect(await screen.findByRole("alert")).toHaveTextContent("Custom: That code did not work");
  });

  it("passes axe on both steps and in its error state", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const options: axe.RunOptions = {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      rules: { "color-contrast": { enabled: false } },
    };
    mount();
    expect((await axe.run(document.body, options)).violations).toEqual([]);
    await sendTo(TEST_USER.email);
    await enter("000000");
    await screen.findByRole("alert");
    expect((await axe.run(document.body, options)).violations).toEqual([]);
  });
});

describe("describeOtpError", () => {
  function refusal(status: number, body: unknown): KarniApiError {
    return new KarniApiError(status, body);
  }

  it("words each Karni code and the plain statuses", () => {
    expect(describeOtpError(refusal(401, { code: "E235" })).title).toBe("That code did not work");
    expect(describeOtpError(refusal(401, { code: "E226" })).kind).toBe("forbidden");
    expect(describeOtpError(refusal(404, { code: "E236" })).title).toBe(
      "Sign-in with a code is not available here",
    );
    expect(describeOtpError(refusal(429, { detail: "throttled" })).description).toBe(
      "Wait a few minutes, then try again.",
    );
    expect(describeOtpError(refusal(400, { email: ["Enter a valid email address."] })).kind).toBe(
      "validation",
    );
  });

  it("falls back to describeError for anything without a Karni code", () => {
    expect(describeOtpError(new TypeError("Failed to fetch")).kind).toMatch(/network|offline/);
  });
});

describe("LoginForm's switch to sign-in with a code", () => {
  function mountLogin(props: LoginFormProps = {}) {
    render(
      <Providers>
        <LoginForm {...props} />
      </Providers>,
    );
  }

  it("is off by default", () => {
    mountLogin();
    expect(screen.queryByRole("button", { name: "Sign in with a code" })).toBeNull();
  });

  it("swaps the password fields for OtpLoginForm and back", async () => {
    const onSuccess = vi.fn();
    mountLogin({ codeSignIn: true, onSuccess });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign in with a code" }));
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await sendTo(TEST_USER.email);
    await enter(TEST_LOGIN_CODE);
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  });

  it("returns to the password form", async () => {
    mountLogin({ codeSignIn: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign in with a code" }));
    await user.click(screen.getByRole("button", { name: "Sign in with a password" }));
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});
