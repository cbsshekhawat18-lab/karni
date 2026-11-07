/**
 * useOtpLogin (experimental) through the real AuthProvider against msw: the two
 * steps, the request bodies, JWT adoption, the session re-sync, the 2FA step,
 * an account awaiting approval, refusals, and the resend cooldown.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
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
import { AuthContext, AuthProvider, useAuth, type AuthContextValue } from "./provider";
import { createMemoryTokenStorage } from "./storage";
import { useOtpLogin, type UseOtpLoginOptions } from "./useOtpLogin";

const BASE = "http://karni.test/api";

function setup(mode: "jwt" | "session" = "jwt", options: UseOtpLoginOptions = {}) {
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
  const hook = renderHook(() => ({ otp: useOtpLogin(options), auth: useAuth() }), { wrapper });
  return { ...hook, storage };
}

beforeEach(() => {
  resetMswData();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useOtpLogin", () => {
  it("sends the code, moves to the code step, then adopts the token pair in JWT mode", async () => {
    const { result, storage } = setup();
    expect(result.current.otp.step).toBe("email");
    expect(result.current.otp.status).toBe("idle");
    await act(async () => {
      await result.current.otp.send(` ${TEST_USER.email} `);
    });
    expect(result.current.otp.step).toBe("code");
    expect(result.current.otp.status).toBe("code-sent");
    expect(result.current.otp.email).toBe(TEST_USER.email);
    expect(result.current.otp.length).toBe(6);
    expect(result.current.otp.expiresIn).toBe(600);
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.otp.verify("246 810");
    });
    expect(outcome).toMatchObject({ ok: true, user: { email: TEST_USER.email } });
    expect(result.current.otp.status).toBe("success");
    expect(result.current.auth.status).toBe("authenticated");
    expect(storage.get()).toBe(authTestControls.snapshot().currentRefreshToken);
    expect(authTestControls.otpRequests()).toEqual([
      { step: "send", body: { email: TEST_USER.email } },
      { step: "verify", body: { email: TEST_USER.email, code: TEST_LOGIN_CODE } },
    ]);
  });

  it("takes the length and lifetime from the server's answer", async () => {
    server.use(
      http.post("*/api/auth/otp/send/", () =>
        HttpResponse.json({ detail: "ok", length: 8, expires_in: 120 }),
      ),
    );
    const { result } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_USER.email);
    });
    expect(result.current.otp.length).toBe(8);
    expect(result.current.otp.expiresIn).toBe(120);
  });

  it("falls back to the server defaults when the answer leaves them out", async () => {
    server.use(http.post("*/api/auth/otp/send/", () => HttpResponse.json({ detail: "ok" })));
    const { result } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_USER.email);
    });
    expect(result.current.otp.length).toBe(6);
    expect(result.current.otp.expiresIn).toBe(600);
  });

  it("is sending, then verifying, while the requests run", async () => {
    let finish: (() => void) | undefined;
    server.use(
      http.post("*/api/auth/otp/send/", async () => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return HttpResponse.json({ detail: "ok", length: 6, expires_in: 600 });
      }),
    );
    const { result } = setup();
    let pending: Promise<unknown> | undefined;
    act(() => {
      pending = result.current.otp.send(TEST_USER.email);
    });
    await waitFor(() => expect(result.current.otp.status).toBe("sending"));
    finish?.();
    await act(async () => {
      await pending;
    });
    expect(result.current.otp.status).toBe("code-sent");
  });

  it("hands the 2FA gate on without signing in", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_2FA_USER.email);
    });
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.otp.verify(TEST_LOGIN_CODE);
    });
    expect(outcome).toEqual({ requires2fa: true, ephemeralToken: TEST_EPHEMERAL_TOKEN });
    expect(result.current.otp.status).toBe("requires-2fa");
    expect(result.current.auth.status).toBe("anonymous");
  });

  it("reports an account awaiting approval as its own state, signed out", async () => {
    const { result, storage } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_OTP_EMAILS.pending);
    });
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.otp.verify(TEST_LOGIN_CODE);
    });
    expect(outcome).toMatchObject({ awaitingApproval: true });
    expect(result.current.otp.status).toBe("awaiting-approval");
    expect(result.current.auth.status).toBe("anonymous");
    expect(storage.get()).toBeNull();
  });

  it("rejects a wrong code with the KarniApiError, keeping the code step", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_USER.email);
    });
    let caught: unknown;
    await act(async () => {
      await result.current.otp.verify("000000").catch((error: unknown) => {
        caught = error;
      });
    });
    expect(caught).toBeInstanceOf(KarniApiError);
    expect((caught as KarniApiError).data).toMatchObject({ code: "E235" });
    expect(result.current.otp.status).toBe("error");
    expect(result.current.otp.error).toBe(caught);
    expect(result.current.otp.step).toBe("code");
  });

  it("keeps the email step when sending fails", async () => {
    const { result } = setup();
    let caught: unknown;
    await act(async () => {
      await result.current.otp.send(TEST_OTP_EMAILS.throttled).catch((error: unknown) => {
        caught = error;
      });
    });
    expect((caught as KarniApiError).status).toBe(429);
    expect(result.current.otp.step).toBe("email");
    expect(result.current.otp.status).toBe("error");
  });

  it("counts the resend cooldown down and resends for the same address", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = setup("jwt", { resendCooldown: 3 });
    await act(async () => {
      await result.current.otp.send(TEST_USER.email);
    });
    expect(result.current.otp.cooldown).toBe(3);
    await expect(result.current.otp.resend()).rejects.toThrow("in 3 seconds");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(result.current.otp.cooldown).toBe(0);
    await act(async () => {
      await result.current.otp.resend();
    });
    expect(result.current.otp.cooldown).toBe(3);
    expect(authTestControls.otpRequests().map((request) => request.body)).toEqual([
      { email: TEST_USER.email },
      { email: TEST_USER.email },
    ]);
  });

  it("goes back to the email step, keeping the address, and resets", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.otp.send(TEST_USER.email);
    });
    act(() => {
      result.current.otp.back();
    });
    expect(result.current.otp.step).toBe("email");
    expect(result.current.otp.email).toBe(TEST_USER.email);
    expect(result.current.otp.cooldown).toBe(0);
    act(() => {
      result.current.otp.reset();
    });
    expect(result.current.otp.email).toBe("");
    expect(result.current.otp.status).toBe("idle");
  });

  it("re-syncs the session user in session mode", async () => {
    let signedIn = false;
    server.use(
      http.post("*/api/auth/otp/verify/", () => {
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
    await act(async () => {
      await result.current.otp.send("s@example.com");
    });
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.otp.verify(TEST_LOGIN_CODE);
    });
    expect(outcome).toMatchObject({ ok: true, user: { email: "s@example.com", roles: ["staff"] } });
    expect(result.current.auth.user?.roles).toEqual(["staff"]);
    expect(storage.get()).toBeNull();
  });

  it("explains a hand-built context without otpSend", async () => {
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
    const { result } = renderHook(() => useOtpLogin(), { wrapper });
    await expect(result.current.send("a@example.com")).rejects.toThrow(
      "needs Karni's <AuthProvider>",
    );
    await expect(result.current.verify("1")).rejects.toThrow("needs Karni's <AuthProvider>");
  });
});
