/**
 * Pure helpers behind <ResourceForm>: initial-value construction, the D3
 * submit pipeline (dirty-field PATCH granularity, null-clearing, input
 * coercions) and small formatting utilities shared with <ResourceDetail>.
 */
import type { FieldDef } from "../../../schema/types";

export type FormValues = Record<string, unknown>;

/** "published_on" / "draft-mode" → "Published on" / "Draft mode". */
export function humanizeValue(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  if (spaced === "") return value;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO-8601 (any offset) → the local "YYYY-MM-DDTHH:mm" a datetime-local input needs. */
export function toDatetimeLocal(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/**
 * datetime-local value ("YYYY-MM-DDTHH:mm[:ss]", implicitly local) →
 * ISO-8601 with an explicit UTC offset, per the submit rule in the contract.
 * Values that already carry a zone pass through untouched.
 */
export function toIsoWithOffset(value: string): string {
  if (HAS_ZONE.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMinutes);
  const offset = `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offset}`;
}

/**
 * D3 dirtiness at TOP-LEVEL field granularity: a react-hook-form dirtyFields
 * entry counts as dirty when anything in its subtree is truthy, and the whole
 * field value is then sent (DRF PATCH replaces whole field values).
 */
export function isDirtyEntry(entry: unknown): boolean {
  if (entry === true) return true;
  if (Array.isArray(entry)) return entry.some(isDirtyEntry);
  if (entry !== null && typeof entry === "object") {
    return Object.values(entry).some(isDirtyEntry);
  }
  return false;
}

/** Unwraps an (accidentally expanded) relation object to its pk. */
function pkOf(value: unknown): unknown {
  if (value !== null && typeof value === "object" && !Array.isArray(value) && "id" in value) {
    return (value as { id: unknown }).id;
  }
  return value;
}

export interface BuildFormValuesInput {
  fields: readonly FieldDef[];
  /** Edit mode: the UNEXPANDED detail record (D10). Wins over defaultValues. */
  item?: Record<string, unknown>;
  defaultValues?: Record<string, unknown>;
}

function initialFieldValue(field: FieldDef, value: unknown): unknown {
  switch (field.kind) {
    case "string":
    case "text":
      return value == null ? "" : String(value);
    case "number":
    case "integer":
      return value == null ? "" : value;
    case "boolean":
      return Boolean(value);
    case "date":
      return value == null || value === "" ? "" : String(value).slice(0, 10);
    case "datetime":
      return value == null || value === "" ? "" : toDatetimeLocal(String(value));
    case "enum":
      return value == null ? null : value;
    case "relation":
      if (field.relation?.many === true) {
        return Array.isArray(value) ? value.map(pkOf) : [];
      }
      return value == null ? null : pkOf(value);
    case "file":
      return value == null ? null : value;
    case "json":
      return value == null ? "" : JSON.stringify(value, null, 2);
    default:
      return value;
  }
}

/**
 * Builds the react-hook-form value map: every form field gets a defined,
 * controlled-input-safe initial value. Unmatched `defaultValues` keys are kept
 * verbatim (they seed `extraFields`).
 */
export function buildFormValues({ fields, item, defaultValues }: BuildFormValuesInput): FormValues {
  const out: FormValues = {};
  for (const field of fields) {
    let source: unknown = defaultValues?.[field.name];
    if (item !== undefined && field.name in item) source = item[field.name];
    out[field.name] = initialFieldValue(field, source);
  }
  if (defaultValues !== undefined) {
    for (const [key, value] of Object.entries(defaultValues)) {
      if (!(key in out)) out[key] = value;
    }
  }
  return out;
}

type CoercionResult =
  { kind: "value"; value: unknown } | { kind: "omit" } | { kind: "error"; message: string };

function val(value: unknown): CoercionResult {
  return { kind: "value", value };
}

const OMIT: CoercionResult = { kind: "omit" };

/** D3: an emptied nullable field is sent as null; a non-nullable one is omitted. */
function emptied(field: FieldDef): CoercionResult {
  return field.nullable ? val(null) : OMIT;
}

function coerceFieldValue(field: FieldDef, value: unknown): CoercionResult {
  switch (field.kind) {
    case "string":
    case "text": {
      if (value == null) return emptied(field);
      const text = String(value);
      if (text === "" && field.nullable) return val(null);
      return val(text);
    }
    case "number":
    case "integer": {
      if (value == null || value === "") return emptied(field);
      const numeric = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(numeric)) return emptied(field);
      return val(numeric);
    }
    case "boolean":
      if (value == null) return emptied(field);
      return val(Boolean(value));
    case "date":
      if (value == null || value === "") return emptied(field);
      return val(String(value).slice(0, 10));
    case "datetime":
      if (value == null || value === "") return emptied(field);
      return val(toIsoWithOffset(String(value)));
    case "enum": {
      if (value == null || value === "") return emptied(field);
      const member = (field.enumValues ?? []).find(
        (candidate) => String(candidate) === String(value),
      );
      return val(member ?? value);
    }
    case "relation": {
      if (field.relation?.many === true) {
        // M2M fields are cleared with [] — null is not a valid DRF value here.
        if (value == null) return val([]);
        return val(Array.isArray(value) ? value.map(pkOf) : [pkOf(value)]);
      }
      if (value == null || value === "") return emptied(field);
      return val(pkOf(value));
    }
    case "file": {
      if (value == null) return emptied(field);
      // An unchanged string value is the existing file's URL — never resent (D2).
      if (typeof value === "string") return OMIT;
      return val(value);
    }
    case "json": {
      if (typeof value !== "string") {
        return value == null ? emptied(field) : val(value);
      }
      if (value.trim() === "") return emptied(field);
      try {
        return val(JSON.parse(value));
      } catch {
        return { kind: "error", message: "Enter valid JSON." };
      }
    }
    default:
      return val(value);
  }
}

export interface JsonFieldError {
  name: string;
  message: string;
}

export interface PrepareSubmitInput {
  /** The writable schema fields rendered by the form. */
  fields: readonly FieldDef[];
  /** Resolver output from handleSubmit. */
  raw: FormValues;
  mode: "create" | "update";
  /** react-hook-form dirtyFields; only consulted in "update" mode (D3). */
  dirtyFields?: Record<string, unknown>;
}

export interface PreparedSubmit {
  values: Record<string, unknown>;
  /** Per-field validation failures (invalid JSON) that must block the submit. */
  jsonErrors: JsonFieldError[];
}

/**
 * The D3 submit pipeline. Create mode sends every defined value; update mode
 * sends only fields whose dirtyFields subtree is truthy — always the WHOLE
 * field value. Keys without a schema field (extraFields) pass through as-is.
 */
export function prepareSubmit({
  fields,
  raw,
  mode,
  dirtyFields,
}: PrepareSubmitInput): PreparedSubmit {
  const byName = new Map(fields.map((field) => [field.name, field]));
  const values: Record<string, unknown> = {};
  const jsonErrors: JsonFieldError[] = [];

  for (const [name, rawValue] of Object.entries(raw)) {
    if (mode === "update" && !isDirtyEntry(dirtyFields?.[name])) continue;
    const field = byName.get(name);
    if (field === undefined) {
      if (rawValue !== undefined) values[name] = rawValue;
      continue;
    }
    const result = coerceFieldValue(field, rawValue);
    if (result.kind === "error") {
      jsonErrors.push({ name, message: result.message });
    } else if (result.kind === "value" && result.value !== undefined) {
      values[name] = result.value;
    }
  }

  return { values, jsonErrors };
}
