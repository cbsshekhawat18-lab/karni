import * as React from "react";
import {
  addToast,
  dismissToast,
  getToasts,
  subscribeToToasts,
  type ToastHandle,
  type ToastInstance,
  type ToastOptions,
} from "./toast-store";

export interface UseToastResult {
  /** Currently visible toasts (rendered by <Toaster/>). */
  toasts: readonly ToastInstance[];
  /** Full-control entry point: show any ToastOptions. */
  toast: (options: ToastOptions) => ToastHandle;
  /** Shorthand: success variant. */
  success: (title: React.ReactNode, options?: Omit<ToastOptions, "variant">) => ToastHandle;
  /** Shorthand: error variant. */
  error: (title: React.ReactNode, options?: Omit<ToastOptions, "variant">) => ToastHandle;
  /** Shorthand: info variant. */
  info: (title: React.ReactNode, options?: Omit<ToastOptions, "variant">) => ToastHandle;
  /** Dismiss one toast by id, or all when called without arguments. */
  dismiss: (id?: string) => void;
}

function makeShorthand(
  variant: "success" | "error" | "info",
): (title: React.ReactNode, options?: Omit<ToastOptions, "variant">) => ToastHandle {
  return (title, options) => addToast({ ...options, title, variant });
}

const stableApi = {
  toast: addToast,
  success: makeShorthand("success"),
  error: makeShorthand("error"),
  info: makeShorthand("info"),
  dismiss: dismissToast,
} as const;

/**
 * Imperative toast API + the live toast list.
 *
 * Requires a mounted <Toaster/> somewhere in the tree to actually render the
 * toasts. The functions themselves are stable module-level references, safe
 * to use in effects and callbacks without dependency churn.
 */
export function useToast(): UseToastResult {
  const toasts = React.useSyncExternalStore(subscribeToToasts, getToasts, getToasts);
  return React.useMemo(() => ({ toasts, ...stableApi }), [toasts]);
}
