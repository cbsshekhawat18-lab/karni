/**
 * <AuthGuard> tests — driven through the AuthContext directly so every auth
 * state is exercised deterministically.
 */
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { AuthGuard } from "./AuthGuard";
import { AuthContext, type AuthContextValue } from "./provider";
import type { KarniUser, LoginResult } from "./types";

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["admin"] };

function contextValue(partial: Partial<AuthContextValue>): AuthContextValue {
  return {
    user: null,
    roles: [],
    status: "anonymous",
    login: () => Promise.resolve({ ok: true, user: USER } satisfies LoginResult),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
    ...partial,
  };
}

function renderGuard(value: AuthContextValue, guard: ReactNode) {
  return render(<AuthContext.Provider value={value}>{guard}</AuthContext.Provider>);
}

const authenticated = contextValue({ status: "authenticated", user: USER, roles: USER.roles });

describe("AuthGuard", () => {
  it("renders children for an authenticated user (no roles required)", () => {
    renderGuard(
      authenticated,
      <AuthGuard fallback={<p>denied</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("secret")).toBeInTheDocument();
    expect(screen.queryByText("denied")).not.toBeInTheDocument();
  });

  it("renders the fallback for anonymous users (and nothing for fallback={null})", () => {
    renderGuard(
      contextValue({ status: "anonymous" }),
      <AuthGuard fallback={<p>please log in</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("please log in")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();

    // Behaviour change: without a fallback the guard now says why (see the
    // defaults below); `fallback={null}` is how to render nothing.
    const { container } = renderGuard(
      contextValue({ status: "anonymous" }),
      <AuthGuard fallback={null}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("grants access when the user holds at least one required role", () => {
    renderGuard(
      authenticated,
      <AuthGuard roles={["editor", "admin"]} fallback={<p>denied</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("secret")).toBeInTheDocument();
  });

  it("renders the fallback on a role mismatch", () => {
    renderGuard(
      authenticated,
      <AuthGuard roles={["superuser"]} fallback={<p>denied</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("denied")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders the loading slot (not the fallback) while auth resolves", () => {
    renderGuard(
      contextValue({ status: "loading" }),
      <AuthGuard fallback={<p>denied</p>} loading={<p>checking…</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("checking…")).toBeInTheDocument();
    expect(screen.queryByText("denied")).not.toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();

    const { container } = renderGuard(
      contextValue({ status: "loading" }),
      <AuthGuard fallback={<p>denied</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(container).toBeEmptyDOMElement(); // default: nothing, no flash
  });
});
