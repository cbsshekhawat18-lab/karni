/**
 * Experimental. useOtpLogin: sign in with a one-time code sent by email.
 *
 * Two steps. `send(email)` asks the server to email a code (`POST
 * <authBasePath>/otp/send/`) and moves to the code step. `verify(code)` posts
 * the code (`POST <authBasePath>/otp/verify/`) through the AuthProvider: JWT
 * mode adopts the returned token pair, session mode re-syncs the session
 * user. The result is the same shape `useSocialLogin` resolves. `resend()`
 * asks for a new code once the cooldown has run out, and `back()` returns to
 * the email step.
 */
import * as React from "react";
import { useAuth } from "./provider";
import type { OtpLoginResult, OtpSendResult } from "./types";

/** Experimental. Which step the sign-in is on: typing the address, or the code. */
export type OtpLoginStep = "email" | "code";

/**
 * Experimental. Where a sign-in by code stands: `idle`, `sending` while a
 * code is requested, `code-sent`, `verifying` while the code is checked,
 * `success`, `requires-2fa` (finish with the 2FA step), `awaiting-approval`
 * (a new account an administrator must activate) or `error`.
 */
export type OtpLoginStatus =
  | "idle"
  | "sending"
  | "code-sent"
  | "verifying"
  | "success"
  | "requires-2fa"
  | "awaiting-approval"
  | "error";

/** Experimental. Options of `useOtpLogin`. */
export interface UseOtpLoginOptions {
  /** Seconds before `resend()` may ask for another code. Default 30. */
  resendCooldown?: number;
}

/** Experimental. What `useOtpLogin` returns. */
export interface UseOtpLoginResult {
  step: OtpLoginStep;
  /** The address the code was last asked for ("" before the first send). */
  email: string;
  /** Digits the code has, from the server's answer (6 until it answers). */
  length: number;
  /** Seconds the code lives, from the server's answer (`null` until it answers). */
  expiresIn: number | null;
  status: OtpLoginStatus;
  /** The last failure, or `null`: a `KarniApiError` whose `data.code` is the Karni code. */
  error: unknown;
  /** Seconds until `resend()` works again (0 when it does). */
  cooldown: number;
  /** Asks for a code for `email` and moves to the code step. Rejects on failure. */
  send(email: string): Promise<OtpSendResult>;
  /** Asks for a new code for the same address. Rejects during the cooldown. */
  resend(): Promise<OtpSendResult>;
  /** Posts the code. Resolves with the result, or rejects with the refusal. */
  verify(code: string): Promise<OtpLoginResult>;
  /** Back to the email step. `email` keeps the address, so a form can show it again. */
  back(): void;
  /** Back to the start. */
  reset(): void;
}

interface State {
  step: OtpLoginStep;
  email: string;
  length: number;
  expiresIn: number | null;
  status: OtpLoginStatus;
  error: unknown;
  /** `Date.now()` after which a resend is allowed. */
  resendAt: number;
}

const INITIAL: State = {
  step: "email",
  email: "",
  length: 6,
  expiresIn: null,
  status: "idle",
  error: null,
  resendAt: 0,
};

function statusOf(result: OtpLoginResult): OtpLoginStatus {
  if ("ok" in result) return "success";
  if ("requires2fa" in result) return "requires-2fa";
  return "awaiting-approval";
}

function secondsLeft(resendAt: number): number {
  return Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
}

/** Thrown by `resend()` while the cooldown runs. */
class ResendTooSoon extends Error {
  constructor(seconds: number) {
    super(`A new code can be requested in ${seconds} seconds.`);
    this.name = "ResendTooSoon";
  }
}

/**
 * Experimental. Sign in with a code sent by email: `{ step, send, verify, resend, back, status }`.
 *
 * Render inside `AuthProvider`. Escape hatch: `OtpLoginForm` is this hook
 * plus a form, so a project that wants its own form calls the hook directly.
 */
export function useOtpLogin(options: UseOtpLoginOptions = {}): UseOtpLoginResult {
  const { otpSend, otpVerify } = useAuth();
  const resendCooldown = options.resendCooldown ?? 30;
  const [state, setState] = React.useState<State>(INITIAL);
  const [, tick] = React.useState(0);
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Re-render once a second while the cooldown runs, so `cooldown` counts down.
  const cooling = secondsLeft(state.resendAt) > 0;
  React.useEffect(() => {
    if (!cooling) return;
    const timer = setInterval(() => {
      tick((value) => value + 1);
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [cooling, state.resendAt]);

  const update = React.useCallback((patch: Partial<State>) => {
    if (mounted.current) setState((previous) => ({ ...previous, ...patch }));
  }, []);

  const request = React.useCallback(
    async (email: string): Promise<OtpSendResult> => {
      if (otpSend === undefined) {
        throw new Error(
          "useOtpLogin needs Karni's <AuthProvider>, whose context provides otpSend and " +
            "otpVerify. A hand-built AuthContext value must pass both.",
        );
      }
      update({ status: "sending", error: null });
      try {
        const answer = await otpSend(email);
        update({
          step: "code",
          email,
          length: answer.length,
          expiresIn: answer.expiresIn,
          status: "code-sent",
          error: null,
          resendAt: Date.now() + resendCooldown * 1000,
        });
        return answer;
      } catch (error) {
        update({ status: "error", error });
        throw error;
      }
    },
    [otpSend, resendCooldown, update],
  );

  const send = React.useCallback((email: string) => request(email.trim()), [request]);

  const resend = React.useCallback(async (): Promise<OtpSendResult> => {
    const wait = secondsLeft(state.resendAt);
    if (wait > 0) throw new ResendTooSoon(wait);
    return request(state.email);
  }, [request, state.email, state.resendAt]);

  const verify = React.useCallback(
    async (code: string): Promise<OtpLoginResult> => {
      if (otpVerify === undefined) {
        throw new Error(
          "useOtpLogin needs Karni's <AuthProvider>, whose context provides otpSend and " +
            "otpVerify. A hand-built AuthContext value must pass both.",
        );
      }
      update({ status: "verifying", error: null });
      try {
        const result = await otpVerify(state.email, code.replace(/\s+/g, ""));
        update({ status: statusOf(result), error: null });
        return result;
      } catch (error) {
        update({ status: "error", error });
        throw error;
      }
    },
    [otpVerify, state.email, update],
  );

  const back = React.useCallback(() => {
    update({ step: "email", status: "idle", error: null, expiresIn: null, resendAt: 0 });
  }, [update]);

  const reset = React.useCallback(() => {
    update(INITIAL);
  }, [update]);

  return {
    step: state.step,
    email: state.email,
    length: state.length,
    expiresIn: state.expiresIn,
    status: state.status,
    error: state.error,
    cooldown: secondsLeft(state.resendAt),
    send,
    resend,
    verify,
    back,
    reset,
  };
}
