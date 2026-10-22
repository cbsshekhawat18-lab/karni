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
