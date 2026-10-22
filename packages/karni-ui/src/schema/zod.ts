/**
 * zodFor: runtime Zod schema generation from a ResourceSchema (contract
 * "Schema client" + D3).
 *
 * Rules:
 * - mode "create": the create request's required fields are required, the
 *   rest are `.optional()`. Mode "update": ALL fields are optional, with
 *   `.nullable()` nested INSIDE `.optional()` so `undefined` means "not
 *   touched" and `null` means "clear this nullable field".
 * - readOnly fields are excluded, writeOnly fields are included.
 * - nullable / maxLength / min / max and the email / url / uuid string
 *   formats map onto the obvious Zod validators.
 * - enum → z.enum when every member is a string, otherwise a union of
 *   z.literal. "" (BlankEnum) and null (NullEnum) are never members: the
 *   parser already stripped them, and nullability travels on the field.
 * - relation values take their schema from the property's own emitted
 *   type/format (integer pk vs uuid pk), arrays of it when `many`.
 * - file → File-or-string. When `File` does not exist (SSR) it degrades to
 *   z.string() so imports never crash.
 * - json → z.unknown(), number/integer coerce (form inputs produce strings).
 * - datetime accepts datetime-local input ("YYYY-MM-DDTHH:mm[:ss]") and
 *   transforms it to full ISO-8601 with offset on submit (D3).
 */
import { z } from "zod";
import type { ZodObject, ZodRawShape, ZodTypeAny } from "zod";
import type { FieldDef, ResourceSchema } from "./types";

const REQUIRED_MESSAGE = "This field is required.";

/** datetime-local output: no timezone designator at the end. */
const LOCAL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?$/;

function toIsoWithOffset(value: string): string {
  if (!LOCAL_DATETIME.test(value)) return value; // already zoned (or server-side format)
  const date = new Date(value); // datetime-local strings parse as local time
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString();
}

function enumSchema(values: ReadonlyArray<string | number>): ZodTypeAny {
  if (values.length === 0) return z.never();
  if (values.every((value): value is string => typeof value === "string")) {
    return z.enum(values as [string, ...string[]]);
  }
  const literals = values.map((value) => z.literal(value));
  if (literals.length === 1) return literals[0];
  return z.union(literals as unknown as [ZodTypeAny, ZodTypeAny, ...ZodTypeAny[]]);
}

function stringSchema(field: FieldDef, requireNonEmpty: boolean): ZodTypeAny {
  let schema = z.string();
  // DRF's own wording, so a value reads the same whether the browser or the
  // server rejects it.
  if (field.format === "email") schema = schema.email("Enter a valid email address.");
  else if (field.format === "uri" || field.format === "url")
    schema = schema.url("Enter a valid URL.");
  else if (field.format === "uuid") schema = schema.uuid("Must be a valid UUID.");
  if (field.maxLength !== undefined) {
    schema = schema.max(
      field.maxLength,
      `Ensure this field has no more than ${field.maxLength} characters.`,
    );
  }
  if (requireNonEmpty) schema = schema.min(1, REQUIRED_MESSAGE);
  return schema;
}

function numberSchema(field: FieldDef, integer: boolean): ZodTypeAny {
  let schema = z.coerce.number();
  if (integer) schema = schema.int();
  if (field.min !== undefined) schema = schema.min(field.min);
  if (field.max !== undefined) schema = schema.max(field.max);
  return schema;
}

function relationValueSchema(field: FieldDef, coerce: boolean): ZodTypeAny {
  switch (field.relationValueType) {
    case "uuid":
      return z.string({ required_error: REQUIRED_MESSAGE }).uuid();
    case "integer":
      return coerce
        ? z.coerce.number().int()
        : z.number({ required_error: REQUIRED_MESSAGE }).int();
    default:
      return z.string({ required_error: REQUIRED_MESSAGE }).min(1, REQUIRED_MESSAGE);
  }
}

/**
 * A single relation input left empty arrives as "" (an untouched select) or
 * null (a cleared one). A nullable relation then carries null (DRF's
 * allow_null). A required non-nullable one fails with REQUIRED_MESSAGE
 * instead of "Invalid uuid" / "Expected string, received null". An optional
 * non-nullable one is omitted. Integer ids typed as strings are coerced.
 */
function singleRelationSchema(field: FieldDef, requireNonEmpty: boolean): ZodTypeAny {
  const value = relationValueSchema(field, false);
  let target: ZodTypeAny = field.nullable ? value.nullable() : value;
  if (!requireNonEmpty) target = target.optional();
  return z.preprocess((raw) => {
    if (raw === "" || raw === null || raw === undefined) return field.nullable ? null : undefined;
    if (field.relationValueType === "integer" && typeof raw === "string" && raw.trim() !== "") {
      const parsed = Number(raw);
      return Number.isNaN(parsed) ? raw : parsed;
    }
    return raw;
  }, target);
}

function fileSchema(): ZodTypeAny {
  if (typeof File === "undefined") return z.string();
  return z.union([z.instanceof(File), z.string()]);
}

function baseSchemaFor(field: FieldDef, requireNonEmpty: boolean): ZodTypeAny {
  switch (field.kind) {
    case "string":
    case "text":
      return stringSchema(field, requireNonEmpty);
    case "integer":
      return numberSchema(field, true);
    case "number":
      return numberSchema(field, false);
    case "boolean":
      return z.boolean();
    case "date": {
      const schema = z.string();
      return requireNonEmpty ? schema.min(1, REQUIRED_MESSAGE) : schema;
    }
    case "datetime": {
      const schema = requireNonEmpty ? z.string().min(1, REQUIRED_MESSAGE) : z.string();
      return schema.transform(toIsoWithOffset);
    }
    case "enum":
      return enumSchema(field.enumValues ?? []);
    case "relation": {
      if (field.relation?.many === true) return z.array(relationValueSchema(field, true));
      return singleRelationSchema(field, requireNonEmpty);
    }
    case "file":
      return fileSchema();
    case "json":
      return z.unknown();
    case "array":
      return z.array(z.unknown());
    case "unknown":
      return z.unknown();
  }
}

/** Builds a Zod validator for a resource's create or update payload from its schema. */
export function zodFor(schema: ResourceSchema, mode: "create" | "update"): ZodObject<ZodRawShape> {
  const shape: ZodRawShape = {};

  for (const field of schema.fields) {
    if (field.readOnly) continue; // writeOnly stays in (D3)

    // A required string provided as "" must fail in BOTH modes: DRF rejects
    // blank values on required CharFields; in update mode the field may be
    // omitted entirely instead.
    const requireNonEmpty = field.required;
    let fieldSchema = baseSchemaFor(field, requireNonEmpty);

    if (field.nullable) fieldSchema = fieldSchema.nullable();
    // D3: in update mode .nullable() sits INSIDE .optional() — undefined
    // means untouched, null clears.
    if (mode === "update" || !field.required) fieldSchema = fieldSchema.optional();

    shape[field.name] = fieldSchema;
  }

  return z.object(shape);
}
