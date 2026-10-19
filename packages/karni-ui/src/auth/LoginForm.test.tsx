/**
 * <LoginForm> tests — driven through the AuthContext so every login outcome
 * (success, failure, the 2FA gate) is exercised deterministically.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginForm } from "./LoginForm";
import { AuthContext, type AuthContextValue } from "./provider";
import type { KarniUser, LoginResult } from "./types";

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["attendee"] };

function contextValue(login: AuthContextValue["login"]): AuthContextValue {
  return {
    user: null,
    roles: [],
    status: "anonymous",
    login,
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
  };
}

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Password"), "secret-pass");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("signs in with the typed credentials and reports the user", async () => {
    const login = vi.fn(() => Promise.resolve({ ok: true, user: USER } satisfies LoginResult));
    const onSuccess = vi.fn();
    render(
      <AuthContext.Provider value={contextValue(login)}>
        <LoginForm onSuccess={onSuccess} description="Demo logins below." />
      </AuthContext.Provider>,
    );
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Demo logins below.")).toBeInTheDocument();
    await fillAndSubmit();
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(USER));
    expect(login).toHaveBeenCalledWith("ada@example.com", "secret-pass");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a failed login inline and keeps the form usable", async () => {
    const login = vi.fn(() => Promise.reject(new Error("401")));
    render(
      <AuthContext.Provider value={contextValue(login)}>
        <LoginForm />
      </AuthContext.Provider>,
    );
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("hands the 2FA gate to on2FA, or explains it when there is no handler", async () => {
    const gate = { requires2fa: true, ephemeralToken: "tok" } satisfies LoginResult;
    const on2FA = vi.fn();
    const { unmount } = render(
      <AuthContext.Provider value={contextValue(() => Promise.resolve(gate))}>
        <LoginForm on2FA={on2FA} />
      </AuthContext.Provider>,
    );
    await fillAndSubmit();
    await waitFor(() => expect(on2FA).toHaveBeenCalledWith("tok"));
    unmount();

    render(
      <AuthContext.Provider value={contextValue(() => Promise.resolve(gate))}>
        <LoginForm title={null} submitLabel="Go" />
      </AuthContext.Provider>,
    );
    expect(screen.queryByRole("heading")).toBeNull();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "secret-pass");
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("two-factor");
  });
});
