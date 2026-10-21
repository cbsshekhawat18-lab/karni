/**
 * <AuthGuard>'s two refusals: "anonymous" (not signed in: a sign-in prompt)
 * and "denied" (signed in, the role lacks access: PermissionDenied), their
 * props and slots, and `fallback` still covering both.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { server, TEST_USER } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthGuard, defaultAuthGuardSlots } from "./AuthGuard";
import { AuthContext, AuthProvider, type AuthContextValue } from "./provider";
import { createMemoryTokenStorage } from "./storage";
import type { KarniUser, LoginResult } from "./types";

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["attendee"] };

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

const signedIn = contextValue({ status: "authenticated", user: USER, roles: USER.roles });
const anonymous = contextValue({ status: "anonymous" });

function renderGuard(value: AuthContextValue, guard: ReactNode) {
  return render(<AuthContext.Provider value={value}>{guard}</AuthContext.Provider>);
}

describe("AuthGuard defaults", () => {
  it("prompts an anonymous visitor to sign in, with the form", () => {
    renderGuard(
      anonymous,
      <AuthGuard explain className="mt-8">
        <p>secret</p>
      </AuthGuard>,
    );
    const prompt = screen.getByRole("region", { name: "Sign in to continue" });
    expect(prompt).toHaveTextContent("You need to be signed in to see this.");
    expect(prompt).toHaveClass("mt-8");
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("tells a signed-in user without the role who they are and that the role lacks access", () => {
    renderGuard(
      signedIn,
      <AuthGuard explain roles={["organizer"]}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("You don't have access to this")).toBeInTheDocument();
    expect(screen.getByText(/You're signed in as/)).toHaveTextContent(
      "You're signed in as ada@example.com, and your role doesn't include this.",
    );
    expect(screen.queryByLabelText("Email")).toBeNull(); // not a sign-in prompt
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("reveals the content in place once the visitor signs in from the prompt", async () => {
    server.use(
      http.get("*/api/auth/me/", () =>
        HttpResponse.json({ id: TEST_USER.id, email: TEST_USER.email, roles: ["organizer"] }),
      ),
    );
    const client = createKarniClient({ baseUrl: "http://karni.test/api" });
    render(
      <KarniProvider client={client} queryClient={new QueryClient()}>
        <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
          <AuthGuard explain roles={["organizer"]}>
            <p>secret</p>
          </AuthGuard>
        </AuthProvider>
      </KarniProvider>,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), TEST_USER.email);
    await user.type(screen.getByLabelText("Password"), TEST_USER.password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByText("secret")).toBeInTheDocument());
  });
});

describe("AuthGuard overrides", () => {
  it("keeps `fallback` working for both refusals", () => {
    const { unmount } = renderGuard(
      anonymous,
      <AuthGuard fallback={<p>go away</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("go away")).toBeInTheDocument();
    unmount();
    renderGuard(
      signedIn,
      <AuthGuard roles={["organizer"]} fallback={<p>go away</p>}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByText("go away")).toBeInTheDocument();
  });

  it("lets `anonymous` and `denied` say which refusal, over `fallback`", () => {
    const guard = (
      <AuthGuard
        roles={["organizer"]}
        fallback={<p>fallback</p>}
        anonymous={<p>please sign in</p>}
        denied={<p>organizers only</p>}
      >
        <p>secret</p>
      </AuthGuard>
    );
    const { unmount } = renderGuard(anonymous, guard);
    expect(screen.getByText("please sign in")).toBeInTheDocument();
    unmount();
    renderGuard(signedIn, guard);
    expect(screen.getByText("organizers only")).toBeInTheDocument();
    expect(screen.queryByText("fallback")).toBeNull();
  });

  it("renders a project's slots, which can wrap Karni's", () => {
    const Denied = defaultAuthGuardSlots.Denied;
    renderGuard(
      signedIn,
      <AuthGuard
        roles={["organizer"]}
        slots={{
          Denied: (props) => (
            <div data-testid="wrapped">
              <Denied {...props} />
              <p>needs: {props.roles.join(", ")}</p>
            </div>
          ),
        }}
      >
        <p>secret</p>
      </AuthGuard>,
    );
    expect(screen.getByTestId("wrapped")).toHaveTextContent("You don't have access to this");
    expect(screen.getByText("needs: organizer")).toBeInTheDocument();
  });
});

describe("AuthGuard without explain (0.3 default, deprecated)", () => {
  it("renders nothing and warns once that 1.0 explains by default", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { container } = renderGuard(
      anonymous,
      <AuthGuard>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(container).toBeEmptyDOMElement();
    const guardWarnings = warn.mock.calls.filter(([message]) =>
      String(message).includes("AuthGuard"),
    );
    expect(guardWarnings.length).toBeLessThanOrEqual(1);
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("does not warn when the project chose to render nothing", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { container } = renderGuard(
      signedIn,
      <AuthGuard roles={["admin"]} fallback={null}>
        <p>secret</p>
      </AuthGuard>,
    );
    expect(container).toBeEmptyDOMElement();
    expect(warn).not.toHaveBeenCalled();
  });
});
