/**
 * Human label heuristic for resource objects (contract "ResourceTable").
 *
 * Used by ResourceTable's relation cells, ResourceSelect's options and
 * ResourceDetail's relation values. Overridable everywhere it is used:
 * ResourceTable takes `getRowLabel`, ResourceSelect takes `getOptionLabel`.
 */

const LABEL_KEYS = ["name", "title", "label", "email", "str"] as const;

/**
 * Returns the first non-empty string among the `name` → `title` → `label` →
 * `email` → `str` keys, falling back to `String(id)` and finally "".
 */
export function displayLabel(obj: Record<string, unknown>): string {
  for (const key of LABEL_KEYS) {
    const value = obj[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  const id = obj["id"];
  if (id !== null && id !== undefined) return String(id);
  return "";
}
