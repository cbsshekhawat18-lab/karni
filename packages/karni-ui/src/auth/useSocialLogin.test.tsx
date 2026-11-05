/**
 * useSocialLogin (experimental) through the real AuthProvider against msw: the
 * request body, JWT adoption, the session re-sync, the 2FA step, an account
 * awaiting approval and refusals, with `status` and `error` following along.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  authTestControls,
  resetMswData,
  server,
  TEST_EPHEMERAL_TOKEN,
  TEST_ID_TOKENS,
  TEST_USER,
} from "../../tests/msw/server";
import { createKarniClient, KarniApiError } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { AuthContext, AuthProvider, useAuth, type AuthContextValue } from "./provider";
import { createMemoryTokenStorage } from "./storage";
import { useSocialLogin } from "./useSocialLogin";

const BASE = "http://karni.test/api";

function setup(mode: "jwt" | "session" = "jwt") {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const storage = createMemoryTokenStorage();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode={mode} tokenStorage={storage}>
        {children}
      </AuthProvider>
    </KarniProvider>
  );
  const hook = renderHook(() => ({ social: useSocialLogin("google"), auth: useAuth() }), {
    wrapper,
  });
  return { ...hook, storage };
}

beforeEach(() => {
  resetMswData();
});

describe("useSocialLogin", () => {
  it("posts the token, nonce and name, and adopts the token pair in JWT mode", async () => {
    const { result, storage } = setup();
    expect(result.current.social.status).toBe("idle");
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.social.signIn(TEST_ID_TOKENS.valid, {
        nonce: "raw-nonce",
        name: { firstName: "Ada", lastName: "Lovelace" },
      });
    });
    expect(outcome).toMatchObject({ ok: true, user: { email: TEST_USER.email } });
    expect(result.current.social.status).toBe("success");
    expect(result.current.auth.status).toBe("authenticated");
    expect(result.current.auth.user?.email).toBe(TEST_USER.email);
    expect(storage.get()).toBe(authTestControls.snapshot().currentRefreshToken);
    expect(authTestControls.socialRequests()).toEqual([
      {
        provider: "google",
        body: {
          id_token: TEST_ID_TOKENS.valid,
          nonce: "raw-nonce",
          name: { first_name: "Ada", last_name: "Lovelace" },
        },
      },
    ]);
  });

  it("sends only the token when there is no nonce or name", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.social.signIn(TEST_ID_TOKENS.valid);
    });
    expect(authTestControls.socialRequests()[0]?.body).toEqual({ id_token: TEST_ID_TOKENS.valid });
  });

  it("is pending while the request runs", async () => {
    const { result } = setup();
    let finish: (() => void) | undefined;
    server.use(
      http.post("*/api/auth/social/google/", async () => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return HttpResponse.json({ code: "E218", detail: "E218: expired" }, { status: 401 });
      }),
    );
    let pending: Promise<unknown> | undefined;
    act(() => {
      pending = result.current.social.signIn("t").catch(() => undefined);
    });
    await waitFor(() => expect(result.current.social.status).toBe("pending"));
    finish?.();
    await act(async () => {
      await pending;
    });
    expect(result.current.social.status).toBe("error");
  });

  it("hands the 2FA gate on without signing in", async () => {
    const { result } = setup();
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.social.signIn(TEST_ID_TOKENS.twoFactor);
    });
    expect(outcome).toEqual({ requires2fa: true, ephemeralToken: TEST_EPHEMERAL_TOKEN });
    expect(result.current.social.status).toBe("requires-2fa");
    expect(result.current.auth.status).toBe("anonymous");
  });

  it("reports an account awaiting approval as its own state, signed out", async () => {
    const { result, storage } = setup();
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.social.signIn(TEST_ID_TOKENS.pending);
    });
    expect(outcome).toMatchObject({ awaitingApproval: true });
    expect(result.current.social.status).toBe("awaiting-approval");
    expect(result.current.auth.status).toBe("anonymous");
    expect(storage.get()).toBeNull();
  });

  it("rejects a refusal with the KarniApiError and keeps it as error", async () => {
    const { result } = setup();
    let caught: unknown;
    await act(async () => {
      await result.current.social.signIn(TEST_ID_TOKENS.expired).catch((error: unknown) => {
        caught = error;
      });
    });
    expect(caught).toBeInstanceOf(KarniApiError);
    expect((caught as KarniApiError).data).toMatchObject({ code: "E218" });
    expect(result.current.social.status).toBe("error");
    expect(result.current.social.error).toBe(caught);
    act(() => result.current.social.reset());
    expect(result.current.social.status).toBe("idle");
    expect(result.current.social.error).toBeNull();
  });

  it("re-syncs the session user in session mode", async () => {
    let signedIn = false;
    server.use(
      http.post("*/api/auth/social/google/", () => {
        signedIn = true;
        return HttpResponse.json({ user: { id: 7, email: "s@example.com", roles: [] } });
      }),
      http.get("*/api/auth/me/", () =>
        signedIn
          ? HttpResponse.json({ id: 7, email: "s@example.com", roles: ["staff"] })
          : HttpResponse.json({ detail: "no" }, { status: 403 }),
      ),
    );
    const { result, storage } = setup("session");
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.social.signIn("any-token");
    });
    expect(outcome).toMatchObject({ ok: true, user: { email: "s@example.com", roles: ["staff"] } });
    expect(result.current.auth.user?.roles).toEqual(["staff"]);
    expect(storage.get()).toBeNull();
  });

  it("says when the session cookie did not come back", async () => {
    server.use(
      http.post("*/api/auth/social/google/", () =>
        HttpResponse.json({ user: { id: 7, email: "s@example.com" } }),
      ),
      http.get("*/api/auth/me/", () => HttpResponse.json({ detail: "no" }, { status: 403 })),
    );
    const { result } = setup("session");
    let caught: unknown;
    await act(async () => {
      await result.current.social.signIn("any-token").catch((error: unknown) => {
        caught = error;
      });
    });
    expect(String(caught)).toContain("The session cookie did not come back");
  });

  it("names the provider in the URL", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const queryClient = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <KarniProvider client={client} queryClient={queryClient}>
        <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
          {children}
        </AuthProvider>
      </KarniProvider>
    );
    const { result } = renderHook(() => useSocialLogin("apple"), { wrapper });
    await act(async () => {
      await result.current.signIn(TEST_ID_TOKENS.valid);
    });
    expect(authTestControls.socialRequests()[0]?.provider).toBe("apple");
  });

  it("explains a hand-built context without socialLogin", async () => {
    const value: AuthContextValue = {
      user: null,
      roles: [],
      status: "anonymous",
      login: () => Promise.reject(new Error("unused")),
      logout: () => Promise.resolve(),
      refresh: () => Promise.resolve(),
      adoptTokens: () => Promise.resolve(),
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    );
    const { result } = renderHook(() => useSocialLogin("google"), { wrapper });
    await expect(result.current.signIn("t")).rejects.toThrow("needs Karni's <AuthProvider>");
  });
});
