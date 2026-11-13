// The products this browser looked at last, newest first (kept in this browser only).
const KEY = "shop.recently-viewed";
const KEEP = 8;

export function readRecent(): string[] {
  try {
    const found: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(found)
      ? found.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

export function rememberViewed(id: string): void {
  try {
    const next = [id, ...readRecent().filter((known) => known !== id)].slice(
      0,
      KEEP,
    );
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage is off (a private window): nothing is remembered
  }
}
