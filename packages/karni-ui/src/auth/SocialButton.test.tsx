/**
 * <SocialButton> (experimental) through the real AuthProvider against msw:
 * success, the 2FA step, an account awaiting approval, each refusal in plain
 * words, a closed provider window, and the button's accessible states.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  authTestControls,
  resetMswData,
  server,
  TEST_EPHEMERAL_TOKEN,
  TEST_ID_TOKENS,
  TEST_USER,
} from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthProvider } from "./provider";
import { describeSocialError, SocialButton, type SocialButtonProps } from "./SocialButton";
import { createMemoryTokenStorage } from "./storage";

const BASE = "http://karni.test/api";

function mount(props: Partial<SocialButtonProps> & Pick<SocialButtonProps, "getIdToken">) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
        <SocialButton provider="google" {...props} />
      </AuthProvider>
    </KarniProvider>,
  );
}

async function press(name = "Continue with Google"): Promise<void> {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

const token = (value: string) => () => Promise.resolve(value);

beforeEach(() => {
  resetMswData();
});

describe("SocialButton", () => {
  it("signs in with the token getIdToken returns and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    mount({ getIdToken: token(TEST_ID_TOKENS.valid), onSuccess });
    await press();
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onSuccess.mock.calls[0]?.[0]).toMatchObject({ email: TEST_USER.email });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("passes the nonce and Apple's first-sign-in name along", async () => {
    const onSuccess = vi.fn();
    mount({
      provider: "apple",
      getIdToken: () =>
        Promise.resolve({
          idToken: TEST_ID_TOKENS.valid,
          nonce: "n-1",
          name: { firstName: "Mary", lastName: "Jackson" },
        }),
      onSuccess,
    });
    await press("Continue with Apple");
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(authTestControls.socialRequests()[0]).toEqual({
      provider: "apple",
      body: {
        id_token: TEST_ID_TOKENS.valid,
        nonce: "n-1",
        name: { first_name: "Mary", last_name: "Jackson" },
      },
    });
  });

  it("uses the label, the provider name and the icon it is given", async () => {
    mount({
      provider: "contoso-id",
      providerName: "Contoso",
      label: "Use your Contoso account",
      icon: <svg data-testid="mark" />,
      getIdToken: token("x"),
    });
    const button = screen.getByRole("button", { name: "Use your Contoso account" });
    expect(screen.getByTestId("mark").parentElement).toHaveAttribute("aria-hidden", "true");
    await press("Use your Contoso account");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign-in with Contoso is not available here",
    );
    expect(button).toHaveAccessibleDescription(expect.stringContaining("not available"));
  });

  it("hands the 2FA step to on2FA, as LoginForm does", async () => {
    const on2FA = vi.fn();
    const onSuccess = vi.fn();
    mount({ getIdToken: token(TEST_ID_TOKENS.twoFactor), on2FA, onSuccess });
    await press();
    await waitFor(() => expect(on2FA).toHaveBeenCalledWith(TEST_EPHEMERAL_TOKEN));
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("explains the 2FA step when the app has none", async () => {
    mount({ getIdToken: token(TEST_ID_TOKENS.twoFactor) });
    await press();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This account needs a two-factor code",
    );
  });

  it("shows an account awaiting approval as a status, not an error", async () => {
    const onAwaitingApproval = vi.fn();
    const onSuccess = vi.fn();
    mount({ getIdToken: token(TEST_ID_TOKENS.pending), onAwaitingApproval, onSuccess });
    await press();
    const status = await screen.findByText("Your account is waiting for approval");
    const region = status.closest("[data-state='awaiting-approval']");
    expect(region).toHaveAttribute("role", "status");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onAwaitingApproval).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toHaveAttribute(
      "aria-describedby",
      region?.id,
    );
  });

  it.each([
    [TEST_ID_TOKENS.expired, "The sign-in took too long"],
    [TEST_ID_TOKENS.unverified, "Google has not verified your email address"],
    [TEST_ID_TOKENS.closed, "No account is set up for you here"],
    [TEST_ID_TOKENS.unavailable, "Google cannot be reached right now"],
    ["garbage", "Sign-in with Google did not work"],
  ])("says why %s was refused, in plain words", async (idToken, title) => {
    mount({ getIdToken: token(idToken) });
    await press();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert.textContent).not.toMatch(/E2\d\d|40\d|50\d/);
  });

  it("does nothing when the user closes the provider's window", async () => {
    mount({ getIdToken: () => Promise.resolve(null) });
    await press();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Continue with Google" })).toBeEnabled(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(authTestControls.socialRequests()).toEqual([]);
  });

  it("shows a failing provider SDK as an error", async () => {
    mount({ getIdToken: () => Promise.reject(new Error("popup blocked")) });
    await press();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("is busy while the request runs and announces it", async () => {
    server.use(
      http.post("*/api/auth/social/google/", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    mount({ getIdToken: token(TEST_ID_TOKENS.valid) });
    await press();
    const button = screen.getByRole("button", { name: "Continue with Google" });
    await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Signing in with Google…");
  });

  it("announces the same refusal again on the next attempt", async () => {
    mount({ getIdToken: token(TEST_ID_TOKENS.expired) });
    await press();
    const first = await screen.findByRole("alert");
    await press();
    await waitFor(() => expect(screen.getByRole("alert")).not.toBe(first));
  });

  it("passes axe in its error and approval states", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const options: axe.RunOptions = {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      rules: { "color-contrast": { enabled: false } },
    };
    mount({ getIdToken: token(TEST_ID_TOKENS.unverified) });
    await press();
    await screen.findByRole("alert");
    expect((await axe.run(document.body, options)).violations).toEqual([]);
  });

  it("can be disabled", () => {
    mount({ getIdToken: token("x"), disabled: true });
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeDisabled();
  });

  it("takes its own Error and Approval slots", async () => {
    mount({
      getIdToken: token(TEST_ID_TOKENS.pending),
      slots: {
        Approval: ({ id, providerName }) => (
          <p id={id} role="status">
            Waiting on {providerName} approval
          </p>
        ),
      },
    });
    await press();
    expect(await screen.findByText("Waiting on Google approval")).toBeInTheDocument();
  });
});

describe("describeSocialError", () => {
  it("falls back to describeError for anything without a Karni code", () => {
    expect(describeSocialError(new TypeError("Failed to fetch"), "Google").kind).toMatch(
      /network|offline/,
    );
  });
});
