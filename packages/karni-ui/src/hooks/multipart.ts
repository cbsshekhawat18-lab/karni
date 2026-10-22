/**
 * Mutation body encoding (contract D2) + PATCH file-URL omission.
 *
 * D2: after the form's `transformSubmit` has run, a payload containing any
 * top-level `File` (or an array containing one) is encoded as `FormData`.
 * Everything else is sent as JSON. FormData rules:
 * - arrays append as repeated keys,
 * - plain objects/arrays-of-objects (json fields) are JSON-stringified,
 * - numbers/booleans are stringified,
 * - `null`/`undefined` entries are OMITTED: multipart cannot express null
 *   (DRF would parse the string "null"). To null a field, send a JSON PATCH
 *   without the file field instead,
 * - Content-Type is never set manually: fetch derives the multipart boundary.
 *
 * PATCH omission (D2): a string value on a file-kind field is the unchanged
 * display URL the backend returned (D1: response-side `format: uri`). Sending
 * it back would 400 ("not a file"), so it is dropped from PATCH payloads.
 * Field kinds come from the cached parsed schema when present. Without it the
 * payload passes through untouched (graceful degradation).
 *
 * Internal module: not re-exported from the barrel.
 */

function isFileValue(value: unknown): value is File {
  return typeof File !== "undefined" && value instanceof File;
}

function isBlobValue(value: unknown): value is Blob {
  return typeof Blob !== "undefined" && value instanceof Blob;
}

/** True when any top-level value is a File, or an array containing one (D2). */
export function containsFile(values: Record<string, unknown>): boolean {
  return Object.values(values).some(
    (value) =>
      isFileValue(value) || (Array.isArray(value) && value.some((item) => isFileValue(item))),
  );
}

function appendFormValue(form: FormData, key: string, value: unknown): void {
  if (value === null || value === undefined) return;
  if (isFileValue(value) || isBlobValue(value)) {
    form.append(key, value);
    return;
  }
  if (typeof value === "object") {
    form.append(key, JSON.stringify(value));
    return;
  }
  form.append(key, String(value));
}

/** Encodes a payload as FormData per the D2 rules above. */
export function toFormData(values: Record<string, unknown>): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) appendFormValue(form, key, item);
    } else {
      appendFormValue(form, key, value);
    }
  }
  return form;
}

/**
 * D2 dispatch: FormData when a top-level File is present, the payload itself
 * (JSON-serialized by the client) otherwise. Applies to create AND PATCH.
 */
export function encodeBody(values: Record<string, unknown>): Record<string, unknown> | FormData {
  return containsFile(values) ? toFormData(values) : values;
}

/**
 * Extracts the file-kind field names of `resource` from the cached parsed
 * schema (`karniKeys.schema()`'s cache entry). Every access is guarded: an
 * absent cache entry or an unexpected shape yields an empty set, never a
 * throw.
 */
export function fileFieldNames(cachedSchema: unknown, resource: string): ReadonlySet<string> {
  const names = new Set<string>();
  if (typeof cachedSchema !== "object" || cachedSchema === null) return names;
  const resources = (cachedSchema as Record<string, unknown>).resources;
  if (typeof resources !== "object" || resources === null) return names;
  const entry = (resources as Record<string, unknown>)[resource];
  if (typeof entry !== "object" || entry === null) return names;
  const fields = (entry as Record<string, unknown>).fields;
  if (!Array.isArray(fields)) return names;
  for (const field of fields as readonly unknown[]) {
    if (typeof field !== "object" || field === null) continue;
    const { name, kind } = field as Record<string, unknown>;
    if (typeof name === "string" && kind === "file") names.add(name);
  }
  return names;
}

function isStringOrStringArray(value: unknown): boolean {
  if (typeof value === "string") return true;
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/**
 * Drops unchanged file values from a PATCH payload (D2). Strings (or arrays
 * of strings) on file-kind fields are the backend's display URLs, not new
 * uploads.
 */
export function omitUnchangedFileUrls(
  values: Record<string, unknown>,
  fileFields: ReadonlySet<string>,
): Record<string, unknown> {
  if (fileFields.size === 0) return values;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    if (fileFields.has(key) && isStringOrStringArray(value)) continue;
    out[key] = value;
  }
  return out;
}
