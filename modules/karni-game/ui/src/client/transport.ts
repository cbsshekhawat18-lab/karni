export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface TransportRequest {
  method?: Method;
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/**
 * How the client reaches the server. The client of `@karni/ui`
 * (`createKarniClient`) fits it as it is, so a project that signs people in
 * through Karni passes its own client and the game's calls carry the
 * account. Errors must carry the HTTP `status` and the parsed body as `data`
 * (as `KarniApiError` and {@link GameApiError} do); anything else thrown is
 * read as the network being down.
 */
export interface Transport {
  request<T>(path: string, options?: TransportRequest): Promise<T>;
}

/** An answer the server gave with an error status. `code` is the contract's (`GAME008`). */
export class GameApiError extends Error {
  readonly status: number;
  readonly data: unknown;
  readonly code: string | null;

  constructor(status: number, data: unknown, message?: string) {
    const code = codeOf(data);
    super(message ?? detailOf(data) ?? `The server answered ${status}${code ? ` (${code})` : ""}`);
    this.name = "GameApiError";
    this.status = status;
    this.data = data;
    this.code = code;
  }
}

/** The request could not be made: no network, no server, or no backend configured. */
export class OfflineError extends Error {
  constructor(message = "The game server cannot be reached") {
    super(message);
    this.name = "OfflineError";
  }
}

function codeOf(data: unknown): string | null {
  if (typeof data === "object" && data !== null && "code" in data) {
    const code = (data as { code: unknown }).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

function detailOf(data: unknown): string | null {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : null;
  }
  return null;
}

/** An error with an HTTP status: the server answered. */
export function httpError(
  error: unknown,
): { status: number; data: unknown; code: string | null } | null {
  if (typeof error !== "object" || error === null || !("status" in error)) return null;
  const status = (error as { status: unknown }).status;
  if (typeof status !== "number") return null;
  const data = "data" in error ? (error as { data: unknown }).data : undefined;
  return { status, data, code: codeOf(data) };
}

export interface FetchTransportOptions {
  /** Where the API lives: "" for the same origin, or "https://example.com". */
  baseUrl?: string;
  /** The JWT of the signed-in account, sent as a Bearer token. */
  getAccessToken?: () => string | null;
  /** Extra headers on every request (a session's CSRF header). */
  getHeaders?: () => Record<string, string>;
  /** Default "same-origin"; "include" for a session cookie across origins. */
  credentials?: RequestCredentials;
  /** Give up on a request after this long. Default 10000 ms. */
  timeoutMs?: number;
  fetch?: typeof fetch;
}

/** Read Django's CSRF cookie, for `getHeaders` in session mode. */
export function csrfHeader(cookieName = "csrftoken"): Record<string, string> {
  if (typeof document === "undefined") return {};
  const match = document.cookie.match(new RegExp(`(?:^|; )${cookieName}=([^;]*)`));
  return match?.[1] ? { "X-CSRFToken": decodeURIComponent(match[1]) } : {};
}

/** A transport on `fetch`, for a game without `@karni/ui`. */
export function fetchTransport(options: FetchTransportOptions = {}): Transport {
  const base = (options.baseUrl ?? "").replace(/\/$/, "");
  const timeoutMs = options.timeoutMs ?? 10_000;
  return {
    async request<T>(path: string, request: TransportRequest = {}): Promise<T> {
      const doFetch = options.fetch ?? globalThis.fetch;
      const query = new URLSearchParams();
      for (const [name, value] of Object.entries(request.query ?? {})) {
        if (value !== null && value !== undefined) query.set(name, String(value));
      }
      const url = `${base}${path}${query.size ? `?${query.toString()}` : ""}`;
      const headers: Record<string, string> = {
        Accept: "application/json",
        ...options.getHeaders?.(),
        ...request.headers,
      };
      const token = options.getAccessToken?.();
      if (token) headers.Authorization = `Bearer ${token}`;
      if (request.body !== undefined) headers["Content-Type"] = "application/json";
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      request.signal?.addEventListener("abort", () => controller.abort(), { once: true });
      let response: Response;
      try {
        response = await doFetch(url, {
          method: request.method ?? "GET",
          headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
          credentials: options.credentials ?? "same-origin",
          signal: controller.signal,
        });
      } catch (error) {
        throw new OfflineError(error instanceof Error ? error.message : undefined);
      } finally {
        clearTimeout(timer);
      }
      const text = await response.text();
      let data: unknown = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }
      if (!response.ok) throw new GameApiError(response.status, data);
      return data as T;
    },
  };
}
