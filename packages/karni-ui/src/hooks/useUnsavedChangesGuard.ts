/**
 * useUnsavedChangesGuard — warn before leaving a form with unsaved changes.
 *
 * Router-agnostic: the hook owns the "is anything unsaved?" state and the
 * browser's own leave warning (`beforeunload`, for reloads, closed tabs and
 * links out of the app). In-app navigation belongs to the router, so the app
 * hands the guard to its router's blocker:
 *
 *   const guard = useUnsavedChangesGuard();
 *   useBlocker({ shouldBlockFn: guard.shouldBlock, enableBeforeUnload: false }); // TanStack Router
 *   <ResourceForm resource="events" onDirtyChange={guard.setDirty} onSuccess={...} />
 *
 * `isDirty()` and `shouldBlock()` read the latest value synchronously, so a
 * navigation made inside `onSuccess` (after ResourceForm has reported the form
 * clean) is never blocked by a state update that has not rendered yet.
 *
 * Escape hatches: `confirm` replaces `window.confirm` (your own dialog),
 * `beforeUnload: false` leaves reloads alone, and `dirty` makes the hook
 * controlled by your own form state.
 */
import * as React from "react";

/** What the leave warning says. Browsers show their own text for reloads and closed tabs. */
export const UNSAVED_CHANGES_MESSAGE = "You have unsaved changes. Leave without saving them?";

export interface UseUnsavedChangesGuardOptions {
  /** Controlled mode: whether something is unsaved. Omit it and call `setDirty` instead. */
  dirty?: boolean;
  /** Turns the guard off without unmounting it (an opt-out). Default true. */
  enabled?: boolean;
  /** Warn on reload, tab close and links out of the app (`beforeunload`). Default true. */
  beforeUnload?: boolean;
  /** The question `shouldBlock` asks. Default UNSAVED_CHANGES_MESSAGE. */
  message?: string;
  /** Asks the user whether to leave; returns true to leave. Default `window.confirm`. */
  confirm?: (message: string) => boolean;
}

export interface UnsavedChangesGuard {
  /** Whether something is unsaved (re-renders when it changes). */
  dirty: boolean;
  /** Reports the form's state; pass it as ResourceForm's `onDirtyChange`. */
  setDirty: (dirty: boolean) => void;
  /** The latest state, read synchronously (for a router blocker's callback). */
  isDirty: () => boolean;
  /**
   * For a router's blocker: true when there are unsaved changes and the user
   * chose to stay; false (let the navigation happen) otherwise.
   */
  shouldBlock: () => boolean;
  /** The question asked before leaving. */
  message: string;
}

/** Tracks unsaved changes, warns on reload or close, and gives a router blocker what it needs. */
export function useUnsavedChangesGuard(
  options: UseUnsavedChangesGuardOptions = {},
): UnsavedChangesGuard {
  const {
    dirty: controlled,
    enabled = true,
    beforeUnload = true,
    message = UNSAVED_CHANGES_MESSAGE,
    confirm,
  } = options;
  const [reported, setReported] = React.useState(false);
  const dirty = enabled && (controlled ?? reported);

  const dirtyRef = React.useRef(dirty);
  dirtyRef.current = dirty;
  const confirmRef = React.useRef(confirm);
  confirmRef.current = confirm;

  const setDirty = React.useCallback(
    (next: boolean) => {
      dirtyRef.current = enabled && next;
      setReported(next);
    },
    [enabled],
  );

  React.useEffect(() => {
    if (!dirty || !beforeUnload) return undefined;
    const warn = (event: BeforeUnloadEvent): void => {
      // Re-read: a successful save may have cleared it after this render.
      if (!dirtyRef.current) return;
      event.preventDefault();
      // Older browsers show the prompt only when returnValue is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, beforeUnload]);

  const isDirty = React.useCallback(() => dirtyRef.current, []);
  const shouldBlock = React.useCallback((): boolean => {
    if (!dirtyRef.current) return false;
    const ask = confirmRef.current ?? ((text: string) => window.confirm(text));
    return !ask(message);
  }, [message]);

  return { dirty, setDirty, isDirty, shouldBlock, message };
}
