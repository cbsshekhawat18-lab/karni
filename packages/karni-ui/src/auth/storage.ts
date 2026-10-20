/**
 * Pluggable refresh-token storage for JWT mode (contract "Hooks + auth").
 *
 * The default adapter is `localStorage`: it survives reloads and is the
 * simplest thing that works, but any XSS on your page can read it. Stricter
 * setups use `createMemoryTokenStorage()` (logout on reload) or implement
 * the three-method `TokenStorage` interface themselves (e.g. backed by a
 * worker, or by an HttpOnly-cookie BFF). Session mode needs no storage.
 */

export interface TokenStorage {
  get(): string | null;
  set(token: string): void;
  clear(): void;
}

/**
 * Keeps the refresh token in localStorage; the default storage. `key` defaults to "karni.refreshToken". Every storage
 * access is guarded: when localStorage is unavailable (SSR, private windows,
 * blocked site data) the adapter degrades to a no-op that returns `null`
 * instead of throwing.
 */
export function createLocalStorageTokenStorage(key = "karni.refreshToken"): TokenStorage {
  return {
    get(): string | null {
      try {
        return globalThis.localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(token: string): void {
      try {
        globalThis.localStorage.setItem(key, token);
      } catch {
        // Storage unavailable — the session simply won't survive a reload.
      }
    },
    clear(): void {
      try {
        globalThis.localStorage.removeItem(key);
      } catch {
        // Nothing stored, nothing to clear.
      }
    },
  };
}

/**
 * In-memory adapter: most secure (nothing persisted anywhere), but a page
 * reload logs the user out.
 */
export function createMemoryTokenStorage(): TokenStorage {
  let token: string | null = null;
  return {
    get: () => token,
    set: (next: string) => {
      token = next;
    },
    clear: () => {
      token = null;
    },
  };
}
