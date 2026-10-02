import type * as React from "react";

/**
 * Module-level toast store.
 *
 * `useToast()` can be called anywhere (no provider requirement beyond a
 * mounted <Toaster/>): toasts are pushed into this store and every mounted
 * Toaster/useToast subscriber re-renders via useSyncExternalStore.
 */

export type ToastVariant = "default" | "success" | "error" | "info";

export interface ToastOptions {
  /** Stable id (defaults to an auto-generated one). Re-using an id replaces. */
  id?: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  variant?: ToastVariant;
  /** Per-toast auto-dismiss override in ms (Toaster default otherwise). */
  duration?: number;
  /** Action slot (e.g. an "Undo" button), rendered inside the toast. */
  action?: React.ReactNode;
}

export interface ToastInstance extends ToastOptions {
  id: string;
  variant: ToastVariant;
}

export interface ToastHandle {
  id: string;
  dismiss: () => void;
}

/** Oldest toasts beyond this count are dropped. */
const TOAST_LIMIT = 5;

type Listener = () => void;

let toasts: readonly ToastInstance[] = [];
const listeners = new Set<Listener>();
let counter = 0;

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribeToToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToasts(): readonly ToastInstance[] {
  return toasts;
}

export function dismissToast(id?: string): void {
  const next = id === undefined ? [] : toasts.filter((item) => item.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    emit();
  }
}

export function addToast(options: ToastOptions): ToastHandle {
  counter += 1;
  const id = options.id ?? `karni-toast-${String(counter)}`;
  const instance: ToastInstance = {
    ...options,
    id,
    variant: options.variant ?? "default",
  };
  toasts = [...toasts.filter((item) => item.id !== id), instance].slice(-TOAST_LIMIT);
  emit();
  return {
    id,
    dismiss: () => {
      dismissToast(id);
    },
  };
}

/** Test helper — clears all toasts and listeners' state (not in the barrel). */
export function resetToastStore(): void {
  toasts = [];
  counter = 0;
  emit();
}
