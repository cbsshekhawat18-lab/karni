/**
 * The non-React auth core (contract "Hooks + auth" + D6): the client side
 * owns tokens and refresh; <AuthProvider> merely mirrors this engine's state
 * into React.
 *
 * The engine registers itself on the KarniClient via its D6 hook points
 * (`setAuthHooks`): access-token injection, extra headers (session CSRF),
 * credentials mode, and the 401 handler. EVERY request made through the
 * client — resource hooks, schema loading, custom calls — therefore carries
 * credentials and takes part in the refresh flow, with no per-callsite
 * wiring.
 *
 * ## JWT mode (D6)
 * - The access token lives in memory only; the refresh token lives in the
 *   pluggable TokenStorage (localStorage by default).
 * - On a 401 the client calls `onUnauthorized` (at most once per request):
 *   the engine runs ONE shared in-flight refresh (`POST
 *   <authBasePath>/refresh/`) — every concurrent 401 awaits the same
 *   promise. A rotated refresh token is persisted BEFORE that promise
 *   resolves, so queued retries can never observe the stale token. The
 *   client then retries each request exactly once; a request that 401s
 *   AFTER a successful refresh is surfaced and never re-triggers refresh.
 * - Refresh failure clears the storage and flips the engine to "anonymous";
 *   the original 401s surface to the queued callers.
 * - The engine's own auth calls (login/refresh/me/logout/csrf) set
 *   `skipAuthRefresh`, so a 401 from them can never recurse into another
 *   refresh. During a refresh the in-memory access token is nulled, so the
 *   refresh request itself never carries a stale Bearer header (which would
 *   trip DRF authentication/throttling before the view runs).
 * - Multi-tab: tabs do not coordinate (documented limitation). With
 *   refresh-token rotation + blacklisting, a refresh in tab A can invalidate
 *   the token tab B just read, logging tab B out on its next refresh.
 *   Storage events are intentionally not consumed in v0.1.
 *
 * ## Session mode (A4)
 * Django's session cookie authenticates requests; the engine registers
 * `credentials: "include"` and a header hook that mirrors the CSRF cookie
 * ("csrftoken") into the CSRF header ("X-CSRFToken") — names pinned by A4,
 * both overridable. When the cookie is absent it is bootstrapped via
 * `GET <authBasePath>/csrf/` (204 + ensure_csrf_cookie) during initialization
 * and before login. Cross-origin note: `credentials: "include"` is only
 * registered once the mode is known — pass `mode="session"` to
 * <AuthProvider> (skipping async schema detection) so the very first
 * requests already include cookies.
 *
 * ## Mode resolution
 * `modeOverride` prop → cached parsed schema (`authMode`) → the schema
 * document's root `x-karni-auth-mode` (api B14) → "jwt".
 *
 * Internal module: not re-exported from the barrel.
 */
import type { KarniClient } from "../schema/client";
import type { TokenStorage } from "./storage";
import type { AuthStatus, KarniUser, LoginResult } from "./types";

export type AuthMode = "jwt" | "session";

export interface AuthEngineOptions {
  client: KarniClient;
  tokenStorage: TokenStorage;
  /** Skips schema-based mode detection entirely when set. */
  modeOverride?: AuthMode;
  /** Session-mode CSRF cookie name (A4 pin). Default "csrftoken". */
  csrfCookieName?: string;
  /** Session-mode CSRF header name (A4 pin). Default "X-CSRFToken". */
  csrfHeaderName?: string;
  /** Path prefix of the auth endpoints, relative to the client's baseUrl. */
  authBasePath?: string;
  /**
   * Reads whatever the schema loader cached under karniKeys.schema() —
   * consulted (shape-guarded) for `authMode` before fetching the document.
   */
  readCachedSchema?: () => unknown;
}

export interface AuthSnapshot {
  readonly status: AuthStatus;
  readonly user: KarniUser | null;
  readonly mode: AuthMode | null;
}

/**
 * Reads the auth mode out of either a ParsedSchema (`authMode`) or a raw
 * OpenAPI document (root `x-karni-auth-mode`), shape-guarded.
 */
export function readAuthMode(value: unknown): AuthMode | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const record = value as Record<string, unknown>;
  const candidate = record["authMode"] ?? record["x-karni-auth-mode"];
  return candidate === "jwt" || candidate === "session" ? candidate : undefined;
}

/** Validates/normalizes a `me` payload into a KarniUser (roles default []). */
export function normalizeUser(value: unknown): KarniUser | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  const { id, email } = record;
  if (typeof id !== "string" && typeof id !== "number") return null;
  if (typeof email !== "string") return null;
  const roles = Array.isArray(record.roles)
    ? record.roles.filter((role): role is string => typeof role === "string")
    : [];
  return { ...record, id, email, roles };
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  try {
    for (const part of document.cookie.split(";")) {
      const trimmed = part.trim();
      const separator = trimmed.indexOf("=");
      if (separator === -1) continue;
      if (trimmed.slice(0, separator) === name) {
        return decodeURIComponent(trimmed.slice(separator + 1));
      }
    }
  } catch {
    // Cookie access can throw in sandboxed documents.
  }
  return null;
}

function describeShape(value: unknown): string {
  if (typeof value !== "object" || value === null) return `a ${typeof value}`;
  const keys = Object.keys(value);
  return keys.length === 0 ? "an empty object" : `an object with keys [${keys.join(", ")}]`;
}

function read2fa(value: unknown): { ephemeralToken: string } | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (record.requires_2fa !== true) return null;
  return typeof record.ephemeral_token === "string"
    ? { ephemeralToken: record.ephemeral_token }
    : null;
}

export class AuthEngine {
  private readonly client: KarniClient;
  private readonly tokenStorage: TokenStorage;
  private readonly modeOverride: AuthMode | undefined;
  private readonly csrfCookieName: string;
  private readonly csrfHeaderName: string;
  private readonly authBasePath: string;
  private readonly readCachedSchema: (() => unknown) | undefined;

  private mode: AuthMode | null;
  private accessToken: string | null = null;
  private refreshPromise: Promise<boolean> | null = null;
  private initPromise: Promise<void> | null = null;
  private readonly listeners = new Set<() => void>();
  private state: AuthSnapshot;

  constructor(options: AuthEngineOptions) {
    this.client = options.client;
    this.tokenStorage = options.tokenStorage;
    this.modeOverride = options.modeOverride;
    this.csrfCookieName = options.csrfCookieName ?? "csrftoken";
    this.csrfHeaderName = options.csrfHeaderName ?? "X-CSRFToken";
    this.authBasePath = (options.authBasePath ?? "/auth").replace(/\/+$/, "");
    this.readCachedSchema = options.readCachedSchema;
    this.mode = options.modeOverride ?? null;
    this.state = { status: "loading", user: null, mode: this.mode };
    // Register the hook points during construction (render phase), not in an
    // effect: children of <AuthProvider> fire their first queries from
    // effects that run BEFORE the parent's own effects, and those requests
    // must already flow through the auth machinery.
    this.attach();
  }

  // client hook registration

  /** Registers the D6 hook points on the client. Idempotent. */
  attach(): void {
    this.client.setAuthHooks({
      getAccessToken: () => this.accessToken,
      onUnauthorized: () => this.handleUnauthorized(),
      getHeaders: () => this.csrfHeaders(),
      ...(this.mode === "session" ? { credentials: "include" as RequestCredentials } : {}),
    });
  }

  /**
   * Clears every hook this engine registered (including a `getAccessToken`
   * the app passed to createKarniClient — an unmounted AuthProvider leaves
   * the client fully unauthenticated by design).
   */
  detach(): void {
    this.client.setAuthHooks({
      getAccessToken: undefined,
      onUnauthorized: undefined,
      getHeaders: undefined,
      credentials: undefined,
    });
  }

  private csrfHeaders(): Record<string, string> {
    if (this.mode !== "session") return {};
    const token = readCookie(this.csrfCookieName);
    return token === null ? {} : { [this.csrfHeaderName]: token };
  }

  /**
   * The client calls this at most once per 401-ing request (D6). Returning
   * true makes the client retry that request exactly once with
   * freshly-injected credentials; the retry's outcome is always surfaced.
   */
  private async handleUnauthorized(): Promise<boolean> {
    await this.ensureInitialized();
    if (this.mode !== "jwt") {
      // The session evaporated server-side; mirror it.
      if (this.state.status === "authenticated") this.setState("anonymous", null);
      return false;
    }
    if (this.tokenStorage.get() === null) return false;
    return this.ensureRefresh();
  }

  // --- state mirroring (consumed by <AuthProvider> via useSyncExternalStore)

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getSnapshot = (): AuthSnapshot => this.state;

  private setState(status: AuthStatus, user: KarniUser | null): void {
    this.state = { status, user, mode: this.mode };
    for (const listener of this.listeners) listener();
  }

  // bootstrap

  /** Idempotent: the first call kicks off mode resolution + session restore. */
  ensureInitialized(): Promise<void> {
    this.initPromise ??= this.initialize();
    return this.initPromise;
  }

  private async initialize(): Promise<void> {
    try {
      this.mode =
        this.modeOverride ??
        readAuthMode(this.readCachedSchema?.()) ??
        (await this.fetchSchemaAuthMode()) ??
        "jwt";
      if (this.mode === "session") {
        this.client.setAuthHooks({ credentials: "include" });
        await this.ensureCsrfToken(); // A4: bootstrap the cookie when absent.
        await this.syncUser();
        return;
      }
      if (this.tokenStorage.get() === null) {
        this.setState("anonymous", null);
        return;
      }
      const refreshed = await this.ensureRefresh();
      if (!refreshed) return; // performRefresh already cleared + emitted.
      await this.syncUser();
    } catch {
      this.setState("anonymous", null);
    }
  }

  private async fetchSchemaAuthMode(): Promise<AuthMode | undefined> {
    try {
      // joinUrl never double-prefixes, so passing the absolute schema path is
      // safe with any baseUrl; the client's accept header selects JSON.
      const document = await this.client.request<unknown>(this.client.schemaUrl, {
        skipAuthRefresh: true,
      });
      return readAuthMode(document);
    } catch {
      return undefined;
    }
  }

  /** Fetches `/me/` and mirrors the result; any failure means anonymous. */
  private async syncUser(): Promise<void> {
    try {
      const data = await this.client.request<unknown>(`${this.authBasePath}/me/`, {
        skipAuthRefresh: true,
      });
      const user = normalizeUser(data);
      if (user === null) {
        this.setState("anonymous", null);
      } else {
        this.setState("authenticated", user);
      }
    } catch {
      this.setState("anonymous", null);
    }
  }

  /**
   * Reads the CSRF cookie, bootstrapping it via `GET <authBasePath>/csrf/`
   * when absent (A4). Returns null when the cookie stays unreadable (e.g.
   * CSRF_COOKIE_HTTPONLY) — requests then go out without the header and the
   * backend's 403 surfaces, which is the honest failure mode.
   */
  private async ensureCsrfToken(): Promise<string | null> {
    let token = readCookie(this.csrfCookieName);
    if (token === null) {
      try {
        await this.client.request<unknown>(`${this.authBasePath}/csrf/`, {
          method: "GET",
          skipAuthRefresh: true,
        });
      } catch {
        // Bootstrap is best-effort; the cookie re-read below decides.
      }
      token = readCookie(this.csrfCookieName);
    }
    return token;
  }

  // refresh (D6)

  /** ONE shared in-flight refresh; resolves true on success. */
  private ensureRefresh(): Promise<boolean> {
    if (this.refreshPromise === null) {
      this.refreshPromise = this.performRefresh().finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }

  private async performRefresh(): Promise<boolean> {
    const refreshToken = this.tokenStorage.get();
    if (refreshToken === null) {
      this.accessToken = null;
      this.setState("anonymous", null);
      return false;
    }
    // Null the stale access token for the duration of the refresh so the
    // refresh request itself (and anything racing it) never carries a Bearer
    // header the backend would reject before reaching the view.
    this.accessToken = null;
    try {
      const data = await this.client.request<unknown>(`${this.authBasePath}/refresh/`, {
        method: "POST",
        body: { refresh: refreshToken },
        skipAuthRefresh: true, // a 401 here can never recurse (D6)
      });
      const record =
        typeof data === "object" && data !== null ? (data as Record<string, unknown>) : {};
      const access = record.access;
      if (typeof access !== "string" || access === "") {
        throw new Error(
          `Karni auth: ${this.authBasePath}/refresh/ returned ${describeShape(data)} ` +
            "instead of { access, refresh? }.",
        );
      }
      // Persist the rotated refresh token BEFORE this promise resolves, so
      // every queued 401 retry runs against the rotated token (D6).
      const rotated = record.refresh;
      if (typeof rotated === "string" && rotated !== "") {
        this.tokenStorage.set(rotated);
      }
      this.accessToken = access;
      return true;
    } catch {
      this.tokenStorage.clear();
      this.accessToken = null;
      this.setState("anonymous", null);
      return false;
    }
  }

  // public auth actions

  async login(email: string, password: string): Promise<LoginResult> {
    await this.ensureInitialized();
    const path = `${this.authBasePath}/login/`;
    if (this.mode === "session") {
      await this.ensureCsrfToken(); // header rides in via the getHeaders hook
      const data = await this.client.request<unknown>(path, {
        method: "POST",
        body: { email, password },
        skipAuthRefresh: true,
      });
      const twoFactor = read2fa(data);
      if (twoFactor !== null) {
        return { requires2fa: true, ephemeralToken: twoFactor.ephemeralToken };
      }
      const user = normalizeUser(data) ?? (await this.fetchMe(path));
      this.setState("authenticated", user);
      return { ok: true, user };
    }

    const data = await this.client.request<unknown>(path, {
      method: "POST",
      body: { email, password },
      skipAuthRefresh: true,
    });
    const twoFactor = read2fa(data);
    if (twoFactor !== null) {
      return { requires2fa: true, ephemeralToken: twoFactor.ephemeralToken };
    }
    const record =
      typeof data === "object" && data !== null ? (data as Record<string, unknown>) : {};
    const { access, refresh } = record;
    if (typeof access !== "string" || typeof refresh !== "string") {
      throw new Error(
        `Karni auth: unexpected response from POST ${path} — expected ` +
          "{ access, refresh } (JWT mode) or { requires_2fa, ephemeral_token }, got " +
          `${describeShape(data)}. Check the backend's KARNI_AUTH_MODE and the ` +
          'AuthProvider "mode" prop.',
      );
    }
    this.tokenStorage.set(refresh);
    this.accessToken = access;
    const user = normalizeUser(record.user) ?? (await this.fetchMe(path));
    this.setState("authenticated", user);
    return { ok: true, user };
  }

  private async fetchMe(loginPath: string): Promise<KarniUser> {
    const data = await this.client.request<unknown>(`${this.authBasePath}/me/`, {
      skipAuthRefresh: true,
    });
    const user = normalizeUser(data);
    if (user === null) {
      throw new Error(
        `Karni auth: POST ${loginPath} succeeded but ${this.authBasePath}/me/ returned ` +
          `${describeShape(data)} instead of a user object with id and email.`,
      );
    }
    return user;
  }

  /** Best-effort server logout, then always clears local state (anonymous). */
  async logout(): Promise<void> {
    await this.ensureInitialized();
    try {
      if (this.mode === "session") {
        await this.ensureCsrfToken();
        await this.client.request<unknown>(`${this.authBasePath}/logout/`, {
          method: "POST",
          skipAuthRefresh: true,
        });
      } else {
        const refresh = this.tokenStorage.get();
        if (refresh !== null) {
          await this.client.request<unknown>(`${this.authBasePath}/logout/`, {
            method: "POST",
            body: { refresh },
            skipAuthRefresh: true,
          });
        }
      }
    } catch {
      // Server-side logout is best effort; local state clears regardless.
    }
    this.accessToken = null;
    this.tokenStorage.clear();
    this.setState("anonymous", null);
  }

  /**
   * Adopts tokens issued out of band — what `@karni/impersonation-ui` does
   * when a support user starts or stops impersonating (the backend answers
   * with tokens for the other identity). JWT mode only; in session mode the
   * server-side session already changed, so this just re-syncs `/me/`.
   */
  async adoptTokens(access: string | null, refresh: string | null): Promise<void> {
    await this.ensureInitialized();
    if (this.mode === "jwt") {
      if (typeof refresh === "string" && refresh !== "") this.tokenStorage.set(refresh);
      if (typeof access === "string" && access !== "") this.accessToken = access;
    }
    await this.syncUser();
  }

  /**
   * Re-syncs the session: rotates the tokens in JWT mode (A3: /refresh/ is
   * 405 in session mode, so session mode only re-fetches /me/).
   */
  async refresh(): Promise<void> {
    await this.ensureInitialized();
    if (this.mode === "jwt") {
      const refreshed = await this.ensureRefresh();
      if (!refreshed) return; // Already anonymous + cleared.
    }
    await this.syncUser();
  }
}
