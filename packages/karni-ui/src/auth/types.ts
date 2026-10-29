/**
 * Public auth types (contract "Hooks + auth" + D6, accounts contract A15).
 */

/**
 * Shape of the `/api/auth/me/` response. The accounts contract (A15)
 * guarantees `roles: string[]` on MeSerializer. Every other field the
 * backend's user serializer exposes rides along via the index signature.
 */
export interface KarniUser {
  id: string | number;
  email: string;
  roles: string[];
  [extra: string]: unknown;
}

/**
 * "loading" while the initial session restore runs, then "authenticated" or
 * "anonymous". A failed token refresh always lands on "anonymous" (D6).
 */
export type AuthStatus = "loading" | "authenticated" | "anonymous";

/**
 * Discriminated login result (D6). When the backend's 2FA gate fires
 * (accounts A6), `login()` resolves `{ requires2fa, ephemeralToken }`.
 * The 2FA UI is out of scope in v0.1, so consumers exchange the ephemeral
 * token themselves via `POST /api/auth/2fa/login/`.
 */
export type LoginResult =
  { ok: true; user: KarniUser } | { requires2fa: true; ephemeralToken: string };

/**
 * Experimental. What the app sends along with an ID token. `nonce` is the raw
 * value it generated for this sign-in (the token carries it, or its SHA-256
 * hex digest, as Apple does). `name` is Apple's first-sign-in name, used only
 * when the token creates an account.
 */
export interface SocialSignInOptions {
  nonce?: string;
  name?: { firstName?: string; lastName?: string };
}

/**
 * Experimental. The result of signing in with an ID token: signed in, the 2FA
 * step (the same `ephemeralToken` LoginForm's `on2FA` receives), or a new
 * account that waits for an administrator (nothing signed in).
 */
export type SocialLoginResult =
  | { ok: true; user: KarniUser }
  | { requires2fa: true; ephemeralToken: string }
  | { awaitingApproval: true; detail: string };
