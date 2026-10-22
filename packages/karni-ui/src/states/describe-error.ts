/**
 * describeError — any failure in plain words, never a raw status code.
 *
 * Every Karni component that shows an error goes through this, so a 403 reads
 * "You can't delete events" everywhere and a dropped connection reads "You're
 * offline" rather than "Failed to fetch". Projects call it too, for their own
 * error UI; replace a component's whole error panel through its `slots`.
 */
import { KarniApiError } from "../schema/client";

export type KarniErrorKind =
  | "offline"
  | "network"
  | "unauthenticated"
  | "forbidden"
  | "not-found"
  | "validation"
  | "conflict"
  | "rate-limited"
  | "timeout"
  | "server"
  | "unknown";

/** What the user was doing, so the message can name it ("You can't delete events."). */
export interface KarniErrorContext {
  /** A verb: "view", "create", "edit", "delete", "export", "import", or your own. */
  action?: string;
  /** What it was done to, as the sentence needs it: "events", "this event". */
  resource?: string;
}

export interface KarniErrorDescription {
  kind: KarniErrorKind;
  /** A short headline in plain words. */
  title: string;
  /** What to do next. */
  description: string;
  /** Whether the same request can succeed if tried again. */
  retryable: boolean;
  /** The server's own explanation, when it gave one worth showing (never for 5xx). */
  detail?: string;
  /** The HTTP status, for logs and project code; never shown to the user. */
  status?: number;
}

/** DRF's stock sentences add nothing to the plain-words message, so they are not repeated as `detail`. */
const STOCK_DETAILS = new Set([
  "You do not have permission to perform this action.",
  "Authentication credentials were not provided.",
  "Not found.",
  "No Page matches the given query.",
]);

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function serverDetail(error: KarniApiError): string | undefined {
  const data = error.data;
  if (typeof data === "object" && data !== null && !Array.isArray(data)) {
    const detail = (data as Record<string, unknown>)["detail"];
    if (typeof detail === "string" && detail.trim() !== "" && !STOCK_DETAILS.has(detail.trim())) {
      return detail.trim();
    }
  }
  return undefined;
}

function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/** fetch rejects with a TypeError when the request never got a response. */
function isNetworkFailure(error: unknown): boolean {
  return error instanceof TypeError;
}

function isTimeout(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    ["TimeoutError", "AbortError"].includes(String((error as { name?: unknown }).name))
  );
}

/** Classifies `error` and words it for the person using the app. */
export function describeError(
  error: unknown,
  context: KarniErrorContext = {},
): KarniErrorDescription {
  const { action, resource } = context;
  if (error instanceof KarniApiError) {
    const status = error.status;
    const detail = status < 500 ? serverDetail(error) : undefined;
    const base = { status, ...(detail !== undefined ? { detail } : {}) };
    if (status === 401) {
      return {
        ...base,
        kind: "unauthenticated",
        title: "Your session has ended",
        description: "Sign in again to continue.",
        retryable: false,
      };
    }
    if (status === 403) {
      const what = [action, resource].filter(Boolean).join(" ");
      return {
        ...base,
        kind: "forbidden",
        title: what ? `You can't ${what}` : "You don't have access to this",
        description: "Your role doesn't allow it. Ask an administrator if you need access.",
        retryable: false,
      };
    }
    if (status === 404 || status === 410) {
      return {
        ...base,
        kind: "not-found",
        title: resource ? `Couldn't find ${resource}` : "Not found",
        description: "It may have been deleted, or it isn't available to you.",
        retryable: false,
      };
    }
    if (status === 400 || status === 422) {
      return {
        ...base,
        kind: "validation",
        title: "Some details need attention",
        description: "Check the highlighted fields, then try again.",
        retryable: false,
      };
    }
    if (status === 409 || status === 412) {
      return {
        ...base,
        kind: "conflict",
        title: "This changed while you were working",
        description: "Reload to see the latest version, then try again.",
        retryable: false,
      };
    }
    if (status === 429) {
      return {
        ...base,
        kind: "rate-limited",
        title: "Too many requests",
        description: "Wait a moment, then try again.",
        retryable: true,
      };
    }
    if (status === 408 || status === 504) {
      return {
        ...base,
        kind: "timeout",
        title: "The server took too long to answer",
        description: "Try again in a moment.",
        retryable: true,
      };
    }
    if (status >= 500) {
      return {
        ...base,
        kind: "server",
        title: "Something went wrong on our side",
        description: "Try again. If it keeps happening, tell the site's administrator.",
        retryable: true,
      };
    }
  }
  if (isNetworkFailure(error)) {
    return isOffline()
      ? {
          kind: "offline",
          title: "You're offline",
          description: "Check your connection, then try again.",
          retryable: true,
        }
      : {
          kind: "network",
          title: "Couldn't reach the server",
          description: "Check your connection, then try again.",
          retryable: true,
        };
  }
  if (isTimeout(error)) {
    return {
      kind: "timeout",
      title: "The request took too long",
      description: "Try again in a moment.",
      retryable: true,
    };
  }
  return {
    kind: "unknown",
    title: action ? `Couldn't ${action}${resource ? ` ${resource}` : ""}` : "Something went wrong",
    description: "Try again.",
    retryable: true,
  };
}

/** `describeError(...).title`, capitalised, for one-line contexts (toasts, inline text). */
export function errorSummary(error: unknown, context?: KarniErrorContext): string {
  return capitalised(describeError(error, context).title);
}
