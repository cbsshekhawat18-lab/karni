/**
 * <AuthProvider> + useAuth (contract "Hooks + auth" + D6).
 *
 * The provider instantiates the non-React AuthEngine — which owns the tokens
 * and the single-flight refresh machinery, and registers itself on the
 * KarniClient's auth hook points (see ./engine.ts) — and mirrors its state
 * into React. It must be rendered inside <KarniProvider>: it takes the
 * KarniClient from context and uses the shared QueryClient to peek at the
 * cached schema for `x-karni-auth-mode`.
 *
 * Because the engine hooks into the client itself, EVERY request made
 * through the client while an <AuthProvider> is mounted — resource hooks,
 * schema loading, custom `client.request` calls — carries credentials
 * (Bearer in JWT mode; CSRF header + `credentials: "include"` in session
 * mode) and takes part in the 401 → refresh → retry flow.
 *
 * Escape hatches: `mode` pins the auth mode (skipping schema detection —
 * recommended for cross-origin session setups so the very first requests
 * already include cookies), `tokenStorage` swaps the refresh-token store,
 * `csrfCookieName` / `csrfHeaderName` re-pin the session CSRF names (A4),
 * and `authBasePath` moves the auth endpoints off `/auth`.
 *
 * The OpenAPI document is generated per role (`Karni.field_roles`, ADR 0002
 * P3): a field a role may not read is absent from its schema. When the
 * identity changes (login, logout, a refresh that lands on another user) the
 * provider invalidates the cached schema, so tables, forms and detail views
 * follow the new user's field set without any per-role component code.
 *
 * Known limitations (D6): browser tabs do not coordinate refreshes — with
 * refresh-token rotation, a refresh in one tab can log another tab out on
 * its next refresh. Identity changes also do not auto-invalidate resource
 * queries; call `queryClient.invalidateQueries({ queryKey:
 * karniKeys.resource(...) })` after login/logout where it matters.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactElement,
  type ReactNode,
} from "react";
import { karniKeys } from "../hooks/keys";
import { useKarniClient } from "../schema/provider";
import { AuthEngine } from "./engine";
import { createLocalStorageTokenStorage, type TokenStorage } from "./storage";
import type { AuthStatus, KarniUser, LoginResult } from "./types";

export interface AuthProviderProps {
  /**
   * "jwt" | "session"; when omitted, the mode comes from the schema root's
   * x-karni-auth-mode (D6), falling back to "jwt" when the schema does not
   * declare one.
   */
  mode?: "jwt" | "session";
  /** JWT mode refresh-token storage; default localStorage adapter. */
  tokenStorage?: TokenStorage;
  /** Session mode CSRF cookie name; default "csrftoken" (D6/A4). */
  csrfCookieName?: string;
  /** Session mode CSRF header name; default "X-CSRFToken" (D6/A4). */
  csrfHeaderName?: string;
  /** Path prefix of the auth endpoints relative to baseUrl; default "/auth". */
  authBasePath?: string;
  children?: ReactNode;
}

export interface AuthContextValue {
  user: KarniUser | null;
  roles: string[];
  status: AuthStatus;
  login(email: string, password: string): Promise<LoginResult>;
  logout(): Promise<void>;
  refresh(): Promise<void>;
  /**
   * Adopts tokens issued out of band (JWT mode; session mode re-syncs `/me/`),
   * e.g. after starting or stopping an impersonated session.
   */
  adoptTokens(access: string | null, refresh: string | null): Promise<void>;
}

/**
 * The React mirror of the auth engine's state. Exported for advanced
 * composition (stories, tests, custom providers); application code should
 * use <AuthProvider> + useAuth().
 */
export const AuthContext = createContext<AuthContextValue | null>(null);

/** Holds the signed-in user and attaches credentials (JWT or session) to every request; render it inside `KarniProvider`. */
export function AuthProvider({
  mode,
  tokenStorage,
  csrfCookieName,
  csrfHeaderName,
  authBasePath,
  children,
}: AuthProviderProps): ReactElement {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const storage = useMemo(() => tokenStorage ?? createLocalStorageTokenStorage(), [tokenStorage]);

  // The engine registers the client auth hooks in its constructor (render
  // phase) so that children's first queries — fired from effects that run
  // BEFORE this component's own effects — already flow through it.
  const engine = useMemo(
    () =>
      new AuthEngine({
        client,
        tokenStorage: storage,
        ...(mode !== undefined ? { modeOverride: mode } : {}),
        ...(csrfCookieName !== undefined ? { csrfCookieName } : {}),
        ...(csrfHeaderName !== undefined ? { csrfHeaderName } : {}),
        ...(authBasePath !== undefined ? { authBasePath } : {}),
        readCachedSchema: () => queryClient.getQueryData(karniKeys.schema()),
      }),
    [client, queryClient, storage, mode, csrfCookieName, csrfHeaderName, authBasePath],
  );

  useEffect(() => {
    engine.attach(); // re-assert after StrictMode remounts / engine swaps
    void engine.ensureInitialized();
    return () => {
      engine.detach();
    };
  }, [engine]);

  const snapshot = useSyncExternalStore(engine.subscribe, engine.getSnapshot, engine.getSnapshot);

  // The schema is per role: a new identity (or none) means a new field set.
  const identity = snapshot.user?.id ?? null;
  const previousIdentity = useRef(identity);
  useEffect(() => {
    if (previousIdentity.current === identity) return;
    previousIdentity.current = identity;
    void queryClient.invalidateQueries({ queryKey: karniKeys.schema() });
  }, [identity, queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: snapshot.user,
      roles: snapshot.user?.roles ?? [],
      status: snapshot.status,
      login: (email, password) => engine.login(email, password),
      logout: () => engine.logout(),
      refresh: () => engine.refresh(),
      adoptTokens: (access, refresh) => engine.adoptTokens(access, refresh),
    }),
    [engine, snapshot],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Returns the signed-in user, auth status, `login` and `logout`; throws a descriptive error outside `AuthProvider`. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error(
      "useAuth must be used within an <AuthProvider> (itself inside <KarniProvider>). " +
        "Wrap your tree: <KarniProvider client={...}><AuthProvider>...</AuthProvider></KarniProvider>.",
    );
  }
  return value;
}
