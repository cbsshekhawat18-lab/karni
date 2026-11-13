import { KarniApiError } from "../../schema/client";

/** Field messages and a general message read from a 400 body. */
export interface FormErrors {
  fields: Record<string, string[]>;
  general: string | null;
}

function messages(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  return [];
}

/**
 * Reads `{errors: {field: [msg]}}` (the preferences contract) or a plain
 * `{field: [msg]}` body (DRF) from an API error.
 */
export function readFormErrors(error: unknown): FormErrors {
  const out: FormErrors = { fields: {}, general: null };
  if (!(error instanceof KarniApiError)) {
    out.general = "The change was not saved. Try again.";
    return out;
  }
  const data = error.data;
  if (typeof data !== "object" || data === null) {
    out.general = "The change was not saved. Try again.";
    return out;
  }
  const body = data as Record<string, unknown>;
  const nested = body["errors"];
  const source =
    typeof nested === "object" && nested !== null && !Array.isArray(nested)
      ? (nested as Record<string, unknown>)
      : body;
  for (const [name, value] of Object.entries(source)) {
    if (name === "code" || name === "detail" || name === "errors") continue;
    const found = messages(value);
    if (found.length > 0) out.fields[name] = found;
  }
  const detail = typeof body["detail"] === "string" ? body["detail"] : null;
  if (Object.keys(out.fields).length === 0) out.general = detail ?? "The change was not saved.";
  return out;
}
