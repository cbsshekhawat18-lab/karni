/**
 * createKarniClient — the typed fetch wrapper every @karni/ui layer sits on
 * (contract "Schema client" + D6).
 *
 * Responsibilities:
 * - URL joining + query-string serialization (arrays become repeated keys,
 *   null/undefined are dropped),
 * - JSON request/response handling; a FormData body is passed through
 *   untouched with NO manual Content-Type (the D2 multipart rule),
 * - DRF error passthrough: non-2xx responses throw KarniApiError carrying the
 *   parsed body (field errors / detail / non_field_errors) verbatim,
 * - auth hook points per D6's client-owns-tokens design: the auth layer (not
 *   React) registers token injection, extra headers (session CSRF),
 *   credentials mode and a 401 handler via `setAuthHooks`. The client calls
 *   `onUnauthorized` at most ONCE per request and retries at most ONCE — a
 *   request that 401s again after a successful refresh is surfaced, never
 *   re-triggers refresh (the single-flight refresh promise itself lives in
 *   the auth layer behind this hook).
 */

export interface KarniClientOptions {
  /**
   * Origin (plus optional path prefix) requests resolve against, e.g.
   * "https://api.example.com" or "" for same-origin. Paths that already start
   * with the prefix are not double-prefixed, so operation paths taken from
   * the OpenAPI document ("/api/events/") work with any baseUrl.
   */
  baseUrl: string;
  /** Path of the OpenAPI document. Default "/api/schema/". */
  schemaUrl?: string;
  /** Initial access-token getter; `setAuthHooks` can replace it later (D6). */
  getAccessToken?: () => string | null;
  /** Custom fetch implementation (tests, SSR). Resolved per request. */
  fetch?: typeof globalThis.fetch;
}

export type KarniQueryValue =
  string | number | boolean | ReadonlyArray<string | number | boolean> | null | undefined;

export interface KarniRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Record<string, KarniQueryValue>;
  /** JSON-serialized unless it is FormData (multipart rule D2). */
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /**
   * Skip the 401 → onUnauthorized → retry cycle for this request. The auth
   * layer sets it on its own login/refresh/logout calls so a failing refresh
   * can never recurse into another refresh (D6).
   */
  skipAuthRefresh?: boolean;
}

/**
 * Hook points the auth layer registers on the client (D6). Keys present in
 * the object passed to `setAuthHooks` override the current value (an explicit
 * `undefined` clears one); absent keys are kept.
 */
export interface KarniAuthHooks {
  /** Called before every request; a non-null return is sent as Bearer. */
  getAccessToken?: () => string | null;
  /**
   * Called once when a request gets a 401 (unless `skipAuthRefresh`). Return
   * true to retry the request once with freshly-injected credentials, false
   * to surface the error. Single-flight refresh lives behind this hook.
   */
  onUnauthorized?: (error: KarniApiError) => Promise<boolean>;
  /** Extra headers merged into every request (session-mode X-CSRFToken). */
  getHeaders?: () => Record<string, string>;
  /** fetch credentials mode; session mode sets "include". */
  credentials?: RequestCredentials;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function defaultMessage(status: number, data: unknown): string {
  if (isRecord(data) && typeof data["detail"] === "string") return data["detail"];
  return `Karni API request failed with status ${status}`;
}

/** Thrown for non-2xx responses; `data` carries the parsed DRF error body. */
export class KarniApiError extends Error {
  readonly status: number;
  /** Parsed body when JSON (field errors, detail, non_field_errors), else text. */
  readonly data: unknown;

  constructor(status: number, data: unknown, message?: string) {
    super(message ?? defaultMessage(status, data));
    this.name = "KarniApiError";
    this.status = status;
    this.data = data;
  }
}

export interface KarniClient {
  readonly baseUrl: string;
  readonly schemaUrl: string;
  request<T>(path: string, options?: KarniRequestOptions): Promise<T>;
  /** D6 hook point: the auth layer wires tokens/CSRF/401 handling here. */
  setAuthHooks(hooks: KarniAuthHooks): void;
}

// --- URL handling ------------------------------------------------------------

function splitBaseUrl(baseUrl: string): { origin: string; basePath: string } {
  const match = /^(https?:\/\/[^/]+)(\/.*)?$/.exec(baseUrl);
  if (match !== null) {
    return { origin: match[1] ?? "", basePath: (match[2] ?? "").replace(/\/+$/, "") };
  }
  return { origin: "", basePath: baseUrl.replace(/\/+$/, "") };
}

function joinUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const { origin, basePath } = splitBaseUrl(baseUrl);
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (basePath !== "" && (normalized === basePath || normalized.startsWith(`${basePath}/`))) {
    return origin + normalized;
  }
  return origin + basePath + normalized;
}

function appendQuery(url: string, query: Record<string, KarniQueryValue> | undefined): string {
  if (query === undefined) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  if (qs === "") return url;
  return url.includes("?") ? `${url}&${qs}` : `${url}?${qs}`;
}

// --- body handling -----------------------------------------------------------

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return undefined;
  const text = await response.text();
  if (text === "") return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

// --- the client --------------------------------------------------------------

export function createKarniClient(options: KarniClientOptions): KarniClient {
  const { baseUrl, schemaUrl = "/api/schema/", fetch: fetchOption } = options;

  let hooks: KarniAuthHooks = {};
  if (options.getAccessToken !== undefined) {
    hooks = { getAccessToken: options.getAccessToken };
  }

  async function perform(url: string, requestOptions: KarniRequestOptions): Promise<Response> {
    const headers = new Headers({ accept: "application/json" });
    const hookHeaders = hooks.getHeaders?.();
    if (hookHeaders !== undefined) {
      for (const [name, value] of Object.entries(hookHeaders)) headers.set(name, value);
    }
    if (requestOptions.headers !== undefined) {
      for (const [name, value] of Object.entries(requestOptions.headers)) {
        headers.set(name, value);
      }
    }
    const token = hooks.getAccessToken?.() ?? null;
    if (token !== null && token !== "") headers.set("authorization", `Bearer ${token}`);

    let body: BodyInit | undefined;
    if (typeof FormData !== "undefined" && requestOptions.body instanceof FormData) {
      body = requestOptions.body; // the runtime sets the multipart boundary (D2)
    } else if (requestOptions.body !== undefined) {
      body = JSON.stringify(requestOptions.body);
      if (!headers.has("content-type")) headers.set("content-type", "application/json");
    }

    const init: RequestInit = { method: requestOptions.method ?? "GET", headers };
    if (body !== undefined) init.body = body;
    if (requestOptions.signal !== undefined) init.signal = requestOptions.signal;
    if (hooks.credentials !== undefined) init.credentials = hooks.credentials;

    const fetchImpl = fetchOption ?? globalThis.fetch;
    return fetchImpl(url, init);
  }

  return {
    baseUrl,
    schemaUrl,

    async request<T>(path: string, requestOptions: KarniRequestOptions = {}): Promise<T> {
      const url = appendQuery(joinUrl(baseUrl, path), requestOptions.query);

      let response = await perform(url, requestOptions);
      if (response.ok) return (await parseBody(response)) as T;

      const error = new KarniApiError(response.status, await parseBody(response));
      if (
        response.status === 401 &&
        hooks.onUnauthorized !== undefined &&
        requestOptions.skipAuthRefresh !== true
      ) {
        const shouldRetry = await hooks.onUnauthorized(error);
        if (shouldRetry) {
          response = await perform(url, requestOptions);
          if (response.ok) return (await parseBody(response)) as T;
          // A 401 (or anything else) after a successful refresh is surfaced
          // as-is — it never re-triggers refresh (D6).
          throw new KarniApiError(response.status, await parseBody(response));
        }
      }
      throw error;
    },

    setAuthHooks(next: KarniAuthHooks): void {
      hooks = { ...hooks, ...next };
    },
  };
}
