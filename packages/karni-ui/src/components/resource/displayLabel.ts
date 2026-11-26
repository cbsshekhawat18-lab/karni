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

/**
 * A person's name, from an expanded user: "First Last", else
 * their `name` or email, else the id.
 */
export function personName(obj: Record<string, unknown>): string {
  const parts = [obj["first_name"], obj["last_name"]]
    .filter((part): part is string => typeof part === "string" && part.trim().length > 0)
    .map((part) => part.trim());
  if (parts.length > 0) return parts.join(" ");
  return displayLabel(obj);
}

/** What `relationLabel` reads of a field: its relation and whether it is a person. */
export interface LabelledField {
  relation?: { label?: string } | undefined;
  person?: true | undefined;
}

/**
 * How a related row is named where a relation shows it: the
 * field its model names its rows by (`class Karni: label`, published in
 * `x-karni-relation`), a person's name, else displayLabel's guess.
 */
export function relationLabel(field: LabelledField, obj: Record<string, unknown>): string {
  const named = field.relation?.label;
  if (named !== undefined) {
    const value = obj[named];
    if ((typeof value === "string" && value.trim() !== "") || typeof value === "number") {
      return String(value);
    }
  }
  if (field.person === true) return personName(obj);
  return displayLabel(obj);
}
