/**
 * Shared plumbing for the unhappy states of the resource components that
 * load one thing (ResourceDetail, ChangeHistory, ResourceImport).
 *
 * Internal to @karni/ui.
 */
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { KarniApiError } from "../../schema/client";
import { describeError } from "../../states/describe-error";
import { useOnlineStatus } from "../../states/hooks";

type RetryValue = boolean | number | ((failureCount: number, error: unknown) => boolean);

/** A 4xx answer is the server's decision (not found, forbidden, invalid): asking again gives the same answer. */
export function isClientError(error: unknown): boolean {
  return error instanceof KarniApiError && error.status >= 400 && error.status < 500;
}

/**
 * The query client's own retry policy, except that a 4xx is never retried:
 * TanStack's default (three retries with backoff) would hold a "Couldn't
 * find this event" back for seven seconds.
 */
export function useRetryUnlessClientError(): (failureCount: number, error: unknown) => boolean {
  const configured = useQueryClient().getDefaultOptions().queries?.retry as RetryValue | undefined;
  return React.useCallback(
    (failureCount: number, error: unknown): boolean => {
      if (isClientError(error)) return false;
      if (typeof configured === "function") return configured(failureCount, error);
      if (typeof configured === "number") return failureCount < configured;
      if (typeof configured === "boolean") return configured;
      return failureCount < 3;
    },
    [configured],
  );
}

/**
 * Stands for "the request is waiting for a connection": TanStack Query
 * pauses queries while the browser is offline instead of failing them, and
 * this is what the Error slot receives then (describeError words it as
 * "You're offline").
 */
export function offlineError(): TypeError {
  return new TypeError("The browser is offline.");
}

/**
 * Calls `retry` when the connection comes back while `error` is a network
 * failure, so an offline error clears itself without a click.
 */
export function useRetryWhenOnline(error: unknown, retry: () => void): void {
  const online = useOnlineStatus();
  const wasOnline = React.useRef(online);
  const retryRef = React.useRef(retry);
  retryRef.current = retry;
  const network =
    error !== null &&
    error !== undefined &&
    ["offline", "network"].includes(describeError(error).kind);
  React.useEffect(() => {
    const cameBack = online && !wasOnline.current;
    wasOnline.current = online;
    if (cameBack && network) retryRef.current();
  }, [online, network]);
}
