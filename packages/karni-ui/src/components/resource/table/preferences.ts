/**
 * Per-user table preferences kept in localStorage: row density (one choice
 * per user, for every table) and the columns a user hid (per table). The key
 * carries the signed-in user's id when an AuthProvider knows it, so people
 * sharing a browser keep their own. Without one it is "anonymous".
 *
 * Storage failures (private mode, quota, a server render) fall back to the
 * defaults silently: a preference is a convenience, never a requirement.
 * Internal to @karni/ui. ResourceTable's `density` / `onDensityChange` props
 * are the escape hatch.
 */
import * as React from "react";

export type ResourceTableDensity = "comfortable" | "compact";

const PREFIX = "karni:table";

export function densityKey(userId: string | number | undefined): string {
  return `${PREFIX}:density:${userId === undefined ? "anonymous" : String(userId)}`;
}

export function hiddenColumnsKey(namespace: string, userId: string | number | undefined): string {
  return `${PREFIX}:columns:${namespace}:${userId === undefined ? "anonymous" : String(userId)}`;
}

function readStorage(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A full or blocked storage only loses the preference.
  }
}

/**
 * A value remembered under `key`, re-read when the key changes (another user
 * signs in). `parse` returns undefined for anything it does not recognise.
 */
export function useStoredPreference<V>(
  key: string,
  fallback: V,
  parse: (raw: string) => V | undefined,
  serialize: (value: V) => string,
): [V, (value: V) => void] {
  const read = React.useCallback((): V => {
    const raw = readStorage(key);
    return raw === null ? fallback : (parse(raw) ?? fallback);
  }, [key, fallback, parse]);
  const [state, setState] = React.useState<{ key: string; value: V }>(() => ({
    key,
    value: read(),
  }));
  // Another identity (or table) means another remembered value.
  const current = state.key === key ? state.value : read();
  if (state.key !== key) setState({ key, value: current });
  const set = React.useCallback(
    (value: V) => {
      setState({ key, value });
      writeStorage(key, serialize(value));
    },
    [key, serialize],
  );
  return [current, set];
}

export function parseDensity(raw: string): ResourceTableDensity | undefined {
  return raw === "compact" || raw === "comfortable" ? raw : undefined;
}

export function parseColumnList(raw: string): readonly string[] | undefined {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string")
      ? (parsed as string[])
      : undefined;
  } catch {
    return undefined;
  }
}

export const asString = (value: string): string => value;
export const serializeColumnList = (value: readonly string[]): string => JSON.stringify(value);
