/**
 * Experimental. useSocialLogin: sign in with a Google, Microsoft or Apple ID token.
 *
 * The app gets the ID token from the provider's own SDK (Google Identity
 * Services, MSAL, Sign in with Apple JS). Karni bundles none. `signIn` posts
 * it to `<authBasePath>/social/<provider>/` through the AuthProvider: JWT mode
 * adopts the returned token pair, session mode re-syncs the session user.
 * The result is the same shape `login()` resolves, plus a third case for an
 * account that waits for an administrator's approval.
 */
import * as React from "react";
import { useAuth } from "./provider";
import type { SocialLoginResult, SocialSignInOptions } from "./types";

/**
 * Experimental. Where a sign-in stands: `idle`, `pending` while the request
 * runs, `success`, `requires-2fa` (finish with the 2FA step), `awaiting-approval`
 * (the account exists, an administrator must activate it) or `error`.
 */
export type SocialLoginStatus =
  "idle" | "pending" | "success" | "requires-2fa" | "awaiting-approval" | "error";

/** Experimental. What `useSocialLogin` returns. */
export interface UseSocialLoginResult {
  /**
   * Posts the ID token. Resolves with the result (and sets `status`), or
   * rejects with the error (and sets `error`): a `KarniApiError` whose `data.code`
   * is the Karni code (E215 to E227) for a refusal.
   */
  signIn(idToken: string, options?: SocialSignInOptions): Promise<SocialLoginResult>;
  status: SocialLoginStatus;
  /** The last failure, or `null`. */
  error: unknown;
  /** Back to `idle` with no error. */
  reset(): void;
}

function statusOf(result: SocialLoginResult): SocialLoginStatus {
  if ("ok" in result) return "success";
  if ("requires2fa" in result) return "requires-2fa";
  return "awaiting-approval";
}

/**
 * Experimental. Sign in with a provider's ID token: `{ signIn, status, error, reset }`.
 *
 * Render inside `AuthProvider`. `provider` is the name in the backend's
 * `KARNI_SOCIAL_TOKEN_PROVIDERS` (`"google"`, `"microsoft"`, `"apple"` or the
 * project's own). Escape hatch: `SocialButton` is this hook plus a button, so
 * a project that wants its own button calls the hook directly.
 */
export function useSocialLogin(provider: string): UseSocialLoginResult {
  const { socialLogin } = useAuth();
  const [state, setState] = React.useState<{ status: SocialLoginStatus; error: unknown }>({
    status: "idle",
    error: null,
  });
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const signIn = React.useCallback(
    async (idToken: string, options?: SocialSignInOptions): Promise<SocialLoginResult> => {
      if (socialLogin === undefined) {
        throw new Error(
          "useSocialLogin needs Karni's <AuthProvider>, whose context provides socialLogin. " +
            "A hand-built AuthContext value must pass socialLogin too.",
        );
      }
      setState({ status: "pending", error: null });
      try {
        const result = await socialLogin(provider, idToken, options);
        if (mounted.current) setState({ status: statusOf(result), error: null });
        return result;
      } catch (error) {
        if (mounted.current) setState({ status: "error", error });
        throw error;
      }
    },
    [socialLogin, provider],
  );

  const reset = React.useCallback(() => {
    setState({ status: "idle", error: null });
  }, []);

  return { signIn, status: state.status, error: state.error, reset };
}
