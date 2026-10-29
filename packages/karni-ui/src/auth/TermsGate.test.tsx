/**
 * <TermsGate> (experimental) through the real AuthProvider against msw: the
 * terms from `/me/`, accepting them (with what the app sends about itself), a
 * version bumped mid-session caught from the gate's 403 (E245), the terms
 * changing again while the page is open (E246), the frame, and the loading,
 * error and accessible states. Plus the engine and client hooks underneath.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { delay, http, HttpResponse } from "msw";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authTestControls, resetMswData, server, TEST_USER } from "../../tests/msw/server";
import { createKarniClient, KarniApiError, type KarniClient } from "../schema/client";
import { KarniProvider, useKarniClient } from "../schema/provider";
import { AuthEngine } from "./engine";
import { AuthContext, AuthProvider, useAuth, type AuthContextValue } from "./provider";
import { createMemoryTokenStorage } from "./storage";
import { TermsGate, type TermsGateProps } from "./TermsGate";
import type { AuthTerms } from "./types";

const BASE = "http://karni.test/api";

let auth: AuthContextValue | null = null;

function Probe(): null {
  auth = useAuth();
  return null;
}

/** The app behind the gate: a button that calls the API, like any page would. */
function App(): React.ReactElement {
  const client = useKarniClient();
  const [answer, setAnswer] = React.useState("");
  return (
    <div>
      <p>The organizer dashboard.</p>
      <button
        type="button"
        onClick={() => {
          client.request<{ ok: boolean }>("/api/gated/").then(
            () => setAnswer("loaded"),
            () => setAnswer("refused"),
          );
        }}
      >
        Load
      </button>
      <p data-testid="answer">{answer}</p>
    </div>
  );
}

function mount(props: Partial<TermsGateProps> = {}): KarniClient {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
        <Probe />
        <TermsGate {...props}>
          <App />
        </TermsGate>
      </AuthProvider>
    </KarniProvider>,
  );
  return client;
}

async function signIn(): Promise<void> {
  await waitFor(() => expect(auth?.status).toBe("anonymous"));
  await act(async () => {
    await auth?.login(TEST_USER.email, TEST_USER.password);
  });
}

async function press(name: string): Promise<void> {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

beforeEach(() => {
  resetMswData();
  auth = null;
});

describe("TermsGate", () => {
  it("renders the app when the server asks for no terms", async () => {
    mount();
    await signIn();
    expect(screen.getByText("The organizer dashboard.")).toBeInTheDocument();
    expect(auth?.terms).toBeNull();
    expect(auth?.termsRequired).toBe(false);
  });

  it("renders the app once the current version is accepted", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    mount();
    await signIn();
    expect(screen.queryByText("The organizer dashboard.")).toBeNull();
    await press("Accept and continue");
    expect(await screen.findByText("The organizer dashboard.")).toBeInTheDocument();
    // The server now says so too.
    await act(async () => {
      await auth?.refresh();
    });
    expect(auth?.terms).toEqual({
      version: "2026-11",
      url: "/terms/",
      required: true,
      accepted: true,
    });
    expect(screen.getByText("The organizer dashboard.")).toBeInTheDocument();
  });

  it("shows the terms and the accept button instead of the app until the user accepts", async () => {
    authTestControls.setTerms({ version: "2026-11", url: "/legal/terms/" });
    const onAccepted = vi.fn();
    mount({ onAccepted, client: { platform: "web", app_version: "4.1.0" } });
    await signIn();

    const panel = screen.getByRole("region", { name: "Terms of use" });
    expect(panel).toHaveTextContent(
      "Read the terms (version 2026-11) and accept them to continue.",
    );
    const link = screen.getByRole("link", { name: "Read the terms (opens in a new tab)" });
    expect(link).toHaveAttribute("href", "/legal/terms/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByTitle(/Terms, version/)).toBeNull();
    expect(screen.queryByText("The organizer dashboard.")).toBeNull();
    expect(auth?.termsRequired).toBe(true);

    await press("Accept and continue");
    expect(await screen.findByText("The organizer dashboard.")).toBeInTheDocument();
    expect(authTestControls.termsRequests()).toEqual([
      { version: "2026-11", client: { platform: "web", app_version: "4.1.0" } },
    ]);
    expect(onAccepted).toHaveBeenCalledWith({
      version: "2026-11",
      url: "/legal/terms/",
      required: true,
      accepted: true,
    });
    expect(auth?.termsRequired).toBe(false);
    expect(auth?.user?.["terms"]).toMatchObject({ accepted: true });
  });

  it("calls a client function when the user accepts, and sends no client without one", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    const client = vi.fn(() => ({ device: "Pixel 9" }));
    mount({ client });
    await signIn();
    expect(client).not.toHaveBeenCalled();
    await press("Accept and continue");
    await screen.findByText("The organizer dashboard.");
    expect(client).toHaveBeenCalledTimes(1);
    expect(authTestControls.termsRequests()).toEqual([
      { version: "2026-11", client: { device: "Pixel 9" } },
    ]);
  });

  it("embeds the terms in a titled frame when asked, with the link below", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    mount({ embed: true });
    await signIn();
    const frame = screen.getByTitle("Terms, version 2026-11");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("src", "/terms/");
    expect(
      screen.getByRole("link", { name: "Open the terms in a new tab (opens in a new tab)" }),
    ).toHaveAttribute("href", "/terms/");
  });

  it("catches a version bumped mid-session from the gate's 403 on any request", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    mount();
    await signIn();
    await press("Accept and continue");
    await press("Load");
    await waitFor(() => expect(screen.getByTestId("answer")).toHaveTextContent("loaded"));

    authTestControls.setTerms({ version: "2027-01" });
    await press("Load");
    const panel = await screen.findByRole("region", { name: "Terms of use" });
    expect(panel).toHaveTextContent("version 2027-01");
    expect(auth?.terms).toMatchObject({ version: "2027-01", accepted: false });

    await press("Accept and continue");
    expect(await screen.findByText("The organizer dashboard.")).toBeInTheDocument();
    await press("Load");
    await waitFor(() => expect(screen.getByTestId("answer")).toHaveTextContent("loaded"));
  });

  it("shows the new version when the terms change again before the user accepts (E246)", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    mount();
    await signIn();
    authTestControls.setTerms({ version: "2027-01" });

    await press("Accept and continue");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The terms have changed");
    expect(alert).toHaveTextContent("Read the new version, then accept it.");
    const button = screen.getByRole("button", { name: "Accept and continue" });
    expect(button).toHaveAttribute("aria-describedby", alert.id);
    expect(screen.getByRole("region", { name: "Terms of use" })).toHaveTextContent(
      "version 2027-01",
    );

    await press("Accept and continue");
    expect(await screen.findByText("The organizer dashboard.")).toBeInTheDocument();
    expect(authTestControls.termsRequests()).toEqual([
      { version: "2026-11" },
      { version: "2027-01" },
    ]);
  });

  it("says in plain words why accepting failed, and lets the user try again", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    let fail = true;
    server.use(
      http.post("*/api/auth/terms/accept/", () => {
        if (!fail) return undefined;
        return HttpResponse.json({ detail: "Server Error" }, { status: 500 });
      }),
    );
    mount();
    await signIn();
    await press("Accept and continue");
    expect(await screen.findByRole("alert")).toHaveTextContent(/something went wrong/i);
    fail = false;
    await press("Accept and continue");
    expect(await screen.findByText("The organizer dashboard.")).toBeInTheDocument();
  });

  it("keeps the button busy while the acceptance is recorded", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    server.use(
      http.post("*/api/auth/terms/accept/", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    mount();
    await signIn();
    await press("Accept and continue");
    const button = screen.getByRole("button", { name: "Accept and continue" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Accepting the terms…");
  });

  it("has no axe violations with the frame", async () => {
    authTestControls.setTerms({ version: "2026-11" });
    mount({ embed: true });
    await signIn();
    // jsdom never loads the frame: axe checks the frame element (its title), not inside it.
    const results = await axe.run(document.body, {
      iframes: false,
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});

describe("TermsGate with a hand-built auth context", () => {
  const terms: AuthTerms = { version: "2026-11", url: "/terms/", required: true, accepted: false };

  function value(partial: Partial<AuthContextValue>): AuthContextValue {
    return {
      user: { id: 1, email: "ada@example.com", roles: [] },
      roles: [],
      status: "authenticated",
      login: () => new Promise(() => undefined),
      logout: () => Promise.resolve(),
      refresh: () => Promise.resolve(),
      adoptTokens: () => Promise.resolve(),
      ...partial,
    };
  }

  function renderWith(context: AuthContextValue, props: Partial<TermsGateProps> = {}) {
    return render(
      <AuthContext.Provider value={context}>
        <TermsGate {...props}>
          <p>The app</p>
        </TermsGate>
      </AuthContext.Provider>,
    );
  }

  it("renders `loading` while the auth status loads", () => {
    renderWith(value({ status: "loading", terms, termsRequired: true }), {
      loading: <p>Loading…</p>,
    });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("The app")).toBeNull();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("renders the children for a context without terms", () => {
    renderWith(value({}));
    expect(screen.getByText("The app")).toBeInTheDocument();
  });

  it("does not gate a visitor who is not signed in", () => {
    renderWith(value({ status: "anonymous", user: null, terms, termsRequired: true }));
    expect(screen.getByText("The app")).toBeInTheDocument();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("explains that the app cannot accept terms when the context has no acceptTerms", async () => {
    renderWith(value({ terms, termsRequired: true }));
    await press("Accept and continue");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("The app")).toBeNull();
  });

  it("takes a title, a description, a label and its own panel", () => {
    const { unmount } = renderWith(value({ terms, termsRequired: true }), {
      title: "Before you start",
      description: "Our terms changed in November.",
      acceptLabel: "I accept",
      className: "mt-8",
    });
    const panel = screen.getByRole("region", { name: "Before you start" });
    expect(panel).toHaveTextContent("Our terms changed in November.");
    expect(panel).toHaveClass("mt-8");
    expect(screen.getByRole("button", { name: "I accept" })).toBeInTheDocument();
    unmount();

    renderWith(value({ terms, termsRequired: true }), {
      slots: {
        Panel: ({ terms: shown, accept }) => (
          <button type="button" onClick={accept}>
            Accept {shown.version}
          </button>
        ),
      },
    });
    expect(screen.getByRole("button", { name: "Accept 2026-11" })).toBeInTheDocument();
  });
});

describe("the engine and client under TermsGate", () => {
  it("hands every thrown error to onError, and an observer that throws changes nothing", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const seen: number[] = [];
    client.setAuthHooks({
      onError: (error) => {
        seen.push(error.status);
        throw new Error("observer bug");
      },
    });
    authTestControls.setTerms({ version: "2026-11" });
    const caught = await client.request("/api/gated/").catch((error: unknown) => error);
    expect(caught).toBeInstanceOf(KarniApiError);
    expect((caught as KarniApiError).status).toBe(403);
    expect(seen).toEqual([403]);
  });

  it("flips termsRequired from a 403 E245 and stops listening once detached", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const engine = new AuthEngine({
      client,
      tokenStorage: createMemoryTokenStorage(),
      modeOverride: "jwt",
    });
    await engine.ensureInitialized();
    authTestControls.setTerms({ version: "2026-11", url: "/terms/" });
    await client.request("/api/gated/").catch(() => undefined);
    expect(engine.getSnapshot()).toMatchObject({
      termsRequired: true,
      terms: { version: "2026-11", url: "/terms/", required: true, accepted: false },
    });

    engine.detach();
    const fresh = new AuthEngine({
      client,
      tokenStorage: createMemoryTokenStorage(),
      modeOverride: "jwt",
    });
    fresh.detach();
    await client.request("/api/gated/").catch(() => undefined);
    expect(fresh.getSnapshot().termsRequired).toBe(false);
  });

  it("ignores a 403 that is not the terms gate's", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const engine = new AuthEngine({
      client,
      tokenStorage: createMemoryTokenStorage(),
      modeOverride: "jwt",
    });
    server.use(
      http.get("*/api/gated/", () =>
        HttpResponse.json({ detail: "You do not have permission." }, { status: 403 }),
      ),
    );
    await client.request("/api/gated/").catch(() => undefined);
    expect(engine.getSnapshot()).toMatchObject({ terms: null, termsRequired: false });
  });

  it("rejects acceptTerms when the server sent no terms", async () => {
    const engine = new AuthEngine({
      client: createKarniClient({ baseUrl: BASE }),
      tokenStorage: createMemoryTokenStorage(),
      modeOverride: "jwt",
    });
    await expect(engine.acceptTerms()).rejects.toThrow(/no terms to accept/);
  });
});
