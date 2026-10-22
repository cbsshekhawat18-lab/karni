/**
 * Audit fields: the columns every Karni resource carries because every model
 * inherits BaseModel (`deleted_at` is never exposed by the API). They are
 * record bookkeeping, not domain data, so the generic resource components
 * de-emphasise them: ResourceTable hides them by default (escape hatches:
 * `columns` entries and `showAuditFields`), ResourceDetail renders them last
 * in a muted "Record" group.
 *
 * This list is the single source of truth. Edit it here and every generic
 * component follows. Its order is also the display order whenever audit
 * fields are shown, whatever order the schema declares them in.
 */
import type { FieldDef } from "../../schema/types";

/** The audit field names (`created_at`, `created_by`, …) that tables hide and detail views group last. */
export const AUDIT_FIELDS: readonly string[] = Object.freeze([
  "id",
  "created_at",
  "updated_at",
  "created_by",
  "updated_by",
]);

/**
 * True for a schema field that is one of AUDIT_FIELDS. The backend always
 * emits these readOnly. A writable field that merely shares a name (a natural
 * `id` key, say) is domain data and is never treated as audit.
 */
export function isAuditField(field: Pick<FieldDef, "name" | "readOnly">): boolean {
  return field.readOnly && AUDIT_FIELDS.includes(field.name);
}

/**
 * Splits fields into domain fields (schema order kept) and audit fields
 * (AUDIT_FIELDS order).
 */
export function partitionAuditFields<F extends Pick<FieldDef, "name" | "readOnly">>(
  fields: readonly F[],
): { domain: F[]; audit: F[] } {
  const domain: F[] = [];
  const audit: F[] = [];
  for (const field of fields) {
    (isAuditField(field) ? audit : domain).push(field);
  }
  audit.sort((a, b) => AUDIT_FIELDS.indexOf(a.name) - AUDIT_FIELDS.indexOf(b.name));
  return { domain, audit };
}
