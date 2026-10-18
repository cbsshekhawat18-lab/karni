/**
 * OpenAPI → ResourceSchema parser (contract "Schema client" + amendment D1).
 *
 * Parses the real drf-spectacular dialect (OAS 3.0.3):
 * - resolves $ref against components.schemas (cycle-guarded),
 * - unwraps single-member allOf, merging its siblings (drf-spectacular uses
 *   `allOf: [$ref] + readOnly/description` for annotated enum fields),
 * - maps oneOf [XEnum, NullEnum | BlankEnum] → kind "enum" (+ nullable from
 *   NullEnum; BlankEnum's "" excluded from enumValues),
 * - handles `nullable: true` (3.0) and `type: [T, "null"]` (future-proofing),
 * - split-components merge algebra (COMPONENT_SPLIT_REQUEST=True, api B14):
 *   fields = union(response props, create-request props); readOnly = flagged
 *   OR response-only; writeOnly = flagged OR request-only; required = the
 *   CREATE REQUEST body's required array ONLY; resources without a create op
 *   fall back to response-only, all readOnly,
 * - kind "file" = request-side `format: binary` (the response-side format: uri
 *   is just the display URL),
 * - unknown/unsupported constructs land as kind "unknown" (never crash).
 *
 * This module is internal to @karni/ui (not re-exported from the barrel), but
 * sibling builders (hooks/auth/components) import it relatively.
 */

import type {
  FieldDef,
  FieldKind,
  OperationDef,
  ParsedSchema,
  RelationRef,
  ResourceSchema,
} from "./types";

// minimal structural OpenAPI types

export interface KarniRelationExtension {
  resource?: string;
  many?: boolean;
}

export interface SchemaObject {
  default?: unknown;
  $ref?: string;
  type?: string | readonly string[];
  format?: string;
  title?: string;
  description?: string;
  enum?: ReadonlyArray<string | number | null>;
  nullable?: boolean;
  readOnly?: boolean;
  writeOnly?: boolean;
  required?: readonly string[];
  properties?: Record<string, SchemaObject>;
  items?: SchemaObject;
  allOf?: readonly SchemaObject[];
  oneOf?: readonly SchemaObject[];
  anyOf?: readonly SchemaObject[];
  maxLength?: number;
  minLength?: number;
  minimum?: number;
  maximum?: number;
  "x-karni-relation"?: KarniRelationExtension;
  [extension: string]: unknown;
}

export interface ParameterObject {
  name?: string;
  in?: string;
  required?: boolean;
  schema?: SchemaObject;
  [extension: string]: unknown;
}

export interface MediaTypeObject {
  schema?: SchemaObject;
  [extension: string]: unknown;
}

export interface RequestBodyObject {
  content?: Record<string, MediaTypeObject>;
  required?: boolean;
  [extension: string]: unknown;
}

export interface ResponseObject {
  description?: string;
  content?: Record<string, MediaTypeObject>;
  [extension: string]: unknown;
}

export interface OperationObject {
  operationId?: string;
  parameters?: readonly ParameterObject[];
  requestBody?: RequestBodyObject;
  responses?: Record<string, ResponseObject>;
  "x-karni-resource"?: string;
  [extension: string]: unknown;
}

export interface PathItemObject {
  get?: OperationObject;
  post?: OperationObject;
  put?: OperationObject;
  patch?: OperationObject;
  delete?: OperationObject;
  [extension: string]: unknown;
}

export interface OpenApiDocument {
  openapi?: string;
  paths?: Record<string, PathItemObject>;
  components?: { schemas?: Record<string, SchemaObject>; [extension: string]: unknown };
  "x-karni-auth-mode"?: string;
  [extension: string]: unknown;
}

// helpers

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** "starts_at" → "Starts at"; "is_public" → "Is public". */
export function humanize(name: string): string {
  const spaced = name.replace(/[_-]+/g, " ").trim();
  return spaced.length === 0 ? name : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const REF_PREFIX = "#/components/schemas/";

function lookupRef(doc: OpenApiDocument, ref: string): SchemaObject | undefined {
  if (!ref.startsWith(REF_PREFIX)) return undefined;
  return doc.components?.schemas?.[ref.slice(REF_PREFIX.length)];
}

/**
 * Resolves $ref chains and unwraps single-member allOf, merging siblings over
 * the resolved target (so `{allOf: [$ref StatusEnum], readOnly: true}` yields
 * the enum schema plus readOnly). Cycle-guarded; a cycle resolves to {}.
 */
export function resolveSchema(
  doc: OpenApiDocument,
  schema: SchemaObject | undefined,
  seen: readonly string[] = [],
): SchemaObject | undefined {
  if (schema === undefined) return undefined;

  if (typeof schema.$ref === "string") {
    if (seen.includes(schema.$ref)) return {};
    const target = lookupRef(doc, schema.$ref);
    if (target === undefined) return {};
    const resolved = resolveSchema(doc, target, [...seen, schema.$ref]) ?? {};
    const siblings: SchemaObject = { ...schema };
    delete siblings.$ref;
    return { ...resolved, ...siblings };
  }

  if (Array.isArray(schema.allOf) && schema.allOf.length === 1) {
    const inner = resolveSchema(doc, schema.allOf[0], seen) ?? {};
    const siblings: SchemaObject = { ...schema };
    delete siblings.allOf;
    return { ...inner, ...siblings };
  }

  return schema;
}

// per-property analysis

interface PropertyInfo {
  kind: FieldKind;
  nullable: boolean;
  enumValues?: ReadonlyArray<string | number>;
  maxLength?: number;
  min?: number;
  max?: number;
  format?: string;
  description?: string;
  title?: string;
  default?: unknown;
  readOnly: boolean;
  writeOnly: boolean;
  relation?: RelationRef;
  relationValueType?: "uuid" | "integer" | "string";
  /** True when this side emits format: binary (request side of a file field). */
  binary: boolean;
}

function normalizeType(schema: SchemaObject): { type: string | undefined; nullable: boolean } {
  // `type: [T, "null"]` is handled as future-proofing only (D1).
  if (Array.isArray(schema.type)) {
    const nonNull = schema.type.filter((t) => t !== "null");
    return { type: nonNull[0], nullable: schema.type.includes("null") || schema.nullable === true };
  }
  return {
    type: typeof schema.type === "string" ? schema.type : undefined,
    nullable: schema.nullable === true,
  };
}

function relationFromExtension(schema: SchemaObject): RelationRef | undefined {
  const ext = schema["x-karni-relation"];
  if (isRecord(ext) && typeof ext.resource === "string" && ext.resource.length > 0) {
    return { resource: ext.resource, many: ext.many === true };
  }
  return undefined;
}

function relationValueTypeOf(schema: SchemaObject): "uuid" | "integer" | "string" {
  const { type } = normalizeType(schema);
  if (type === "integer" || type === "number") return "integer";
  if (schema.format === "uuid") return "uuid";
  return "string";
}

/**
 * Combines oneOf/anyOf members when they follow the drf-spectacular enum
 * pattern `[XEnum, BlankEnum?, NullEnum?]`. Returns undefined for any other
 * composition (which then lands as kind "unknown").
 */
function combineEnumMembers(
  doc: OpenApiDocument,
  members: readonly SchemaObject[],
  seen: readonly string[],
): { values: Array<string | number>; nullable: boolean } | undefined {
  const values: Array<string | number> = [];
  let nullable = false;
  for (const member of members) {
    const resolved = resolveSchema(doc, member, seen);
    if (resolved === undefined || !Array.isArray(resolved.enum)) return undefined;
    for (const value of resolved.enum) {
      if (value === null) {
        nullable = true; // NullEnum
      } else if (value !== "") {
        values.push(value); // BlankEnum's "" excluded from enumValues (D1)
      }
    }
  }
  return { values, nullable };
}

/** True for drf-spectacular's JSONField output: a schema with no constraints at all. */
function isAnySchema(schema: SchemaObject): boolean {
  return (
    schema.type === undefined &&
    schema.enum === undefined &&
    schema.properties === undefined &&
    schema.items === undefined &&
    schema.oneOf === undefined &&
    schema.anyOf === undefined &&
    schema.allOf === undefined &&
    schema.$ref === undefined
  );
}

function analyzeProperty(doc: OpenApiDocument, raw: SchemaObject): PropertyInfo {
  const resolved = resolveSchema(doc, raw) ?? {};
  const relation = relationFromExtension(resolved);
  const { type, nullable: typeNullable } = normalizeType(resolved);

  const info: PropertyInfo = {
    kind: "unknown",
    nullable: typeNullable,
    format: resolved.format,
    description: resolved.description,
    title: resolved.title,
    default: resolved.default,
    readOnly: resolved.readOnly === true,
    writeOnly: resolved.writeOnly === true,
    maxLength: resolved.maxLength,
    min: resolved.minimum,
    max: resolved.maximum,
    relation,
    binary: false,
  };

  // drf-spectacular nullable/blank enums: oneOf [XEnum, BlankEnum?, NullEnum?].
  const composition = resolved.oneOf ?? resolved.anyOf;
  if (Array.isArray(composition)) {
    const combined = combineEnumMembers(doc, composition, []);
    if (combined !== undefined) {
      info.kind = "enum";
      info.enumValues = combined.values;
      info.nullable = info.nullable || combined.nullable;
      return info;
    }
    return info; // unsupported composition → kind "unknown"
  }

  if (Array.isArray(resolved.enum)) {
    info.kind = "enum";
    info.nullable = info.nullable || resolved.enum.includes(null);
    info.enumValues = resolved.enum.filter(
      (value): value is string | number => value !== null && value !== "",
    );
    return info;
  }

  if (relation !== undefined && !relation.many) {
    info.kind = "relation";
    info.relationValueType = relationValueTypeOf(resolved);
    return info;
  }

  switch (type) {
    case "string": {
      if (resolved.format === "binary") {
        info.kind = "file";
        info.binary = true;
      } else if (resolved.format === "date") {
        info.kind = "date";
      } else if (resolved.format === "date-time") {
        info.kind = "datetime";
      } else if (resolved.format === undefined && resolved.maxLength === undefined) {
        // CharField always emits maxLength; a bare string is a TextField.
        info.kind = "text";
      } else {
        info.kind = "string";
      }
      return info;
    }
    case "integer":
      info.kind = "integer";
      return info;
    case "number":
      info.kind = "number";
      return info;
    case "boolean":
      info.kind = "boolean";
      return info;
    case "array": {
      if (relation !== undefined) {
        info.kind = "relation";
        const items = resolveSchema(doc, resolved.items) ?? {};
        info.relationValueType = relationValueTypeOf(items);
      } else {
        info.kind = "array";
      }
      return info;
    }
    case "object":
      info.kind = "json";
      return info;
    default: {
      if (relation !== undefined) {
        // Extension present but value type undeclared — still a relation.
        info.kind = "relation";
        info.relationValueType = relationValueTypeOf(resolved);
      } else if (isAnySchema(resolved)) {
        // drf-spectacular emits `{}` for JSONField ("any" schema).
        info.kind = "json";
      }
      return info;
    }
  }
}

// split-components field merge (D1)

function mergeField(
  name: string,
  responseInfo: PropertyInfo | undefined,
  requestInfo: PropertyInfo | undefined,
  requiredSet: ReadonlySet<string>,
  hasCreateRequest: boolean,
  order: number,
): FieldDef {
  // Request side wins for write-facing facts; response side fills the gaps.
  // kind "file" is request-side format: binary (D1) — the response side of the
  // same field is a display URL (format: uri) and must not mask it.
  let kind: FieldKind;
  if (requestInfo?.binary === true) {
    kind = "file";
  } else if (requestInfo !== undefined && requestInfo.kind !== "unknown") {
    kind = requestInfo.kind;
  } else if (responseInfo !== undefined && responseInfo.kind !== "unknown") {
    kind = responseInfo.kind;
  } else {
    kind = "unknown";
  }

  const relation = requestInfo?.relation ?? responseInfo?.relation;
  const title = requestInfo?.title ?? responseInfo?.title;

  const field: FieldDef = {
    name,
    label: title !== undefined && title.length > 0 ? title : humanize(name),
    kind,
    required: requiredSet.has(name),
    readOnly:
      !hasCreateRequest ||
      responseInfo?.readOnly === true ||
      requestInfo?.readOnly === true ||
      (hasCreateRequest && responseInfo !== undefined && requestInfo === undefined),
    writeOnly:
      requestInfo?.writeOnly === true ||
      responseInfo?.writeOnly === true ||
      (responseInfo === undefined && requestInfo !== undefined),
    // Write-facing: a file is a nullable URL on the way out and a plain upload
    // on the way in, and only the request side says what a form may send.
    nullable: requestInfo !== undefined ? requestInfo.nullable : (responseInfo?.nullable ?? false),
    order,
  };

  const enumValues = requestInfo?.enumValues ?? responseInfo?.enumValues;
  const fallback = requestInfo?.default ?? responseInfo?.default;
  if (fallback !== undefined) field.default = fallback;
  if (enumValues !== undefined) field.enumValues = enumValues;
  const maxLength = requestInfo?.maxLength ?? responseInfo?.maxLength;
  if (maxLength !== undefined) field.maxLength = maxLength;
  const min = requestInfo?.min ?? responseInfo?.min;
  if (min !== undefined) field.min = min;
  const max = requestInfo?.max ?? responseInfo?.max;
  if (max !== undefined) field.max = max;
  const format = requestInfo?.format ?? responseInfo?.format;
  if (format !== undefined) field.format = format;
  const description = responseInfo?.description ?? requestInfo?.description;
  if (description !== undefined) field.description = description;
  if (relation !== undefined) {
    field.relation = relation;
    const valueType = requestInfo?.relationValueType ?? responseInfo?.relationValueType;
    if (valueType !== undefined) field.relationValueType = valueType;
  }

  return field;
}

// operation extraction

function operationDef(
  doc: OpenApiDocument,
  path: string,
  method: OperationDef["method"],
  op: OperationObject,
): OperationDef {
  const queryParams: string[] = [];
  let expandEnum: readonly string[] | undefined;
  for (const param of op.parameters ?? []) {
    if (!isRecord(param) || param.in !== "query" || typeof param.name !== "string") continue;
    queryParams.push(param.name);
    if (param.name === "expand") {
      const schema = resolveSchema(doc, param.schema);
      const items = resolveSchema(doc, schema?.items);
      const values = schema?.enum ?? items?.enum;
      if (Array.isArray(values)) {
        expandEnum = values.filter((value): value is string => typeof value === "string");
      }
    }
  }
  const def: OperationDef = {
    path,
    method,
    queryParams,
    hasSearch: queryParams.includes("search"),
  };
  if (typeof op.operationId === "string") def.operationId = op.operationId;
  if (expandEnum !== undefined) def.expandEnum = expandEnum;
  return def;
}

/** Unwraps a DRF paginated list response down to the item component schema. */
function listItemSchema(doc: OpenApiDocument, op: OperationObject): SchemaObject | undefined {
  const response =
    op.responses?.["200"] ?? op.responses?.["201"] ?? Object.values(op.responses ?? {})[0];
  const media = response?.content?.["application/json"];
  const body = resolveSchema(doc, media?.schema);
  if (body === undefined) return undefined;
  const results = resolveSchema(doc, body.properties?.["results"]);
  if (results !== undefined && results.type === "array") {
    return resolveSchema(doc, results.items);
  }
  if (body.type === "array") return resolveSchema(doc, body.items);
  return body;
}

function createRequestSchema(doc: OpenApiDocument, op: OperationObject): SchemaObject | undefined {
  const content = op.requestBody?.content;
  if (!isRecord(content)) return undefined;
  const media =
    content["application/json"] ?? content["multipart/form-data"] ?? Object.values(content)[0];
  return resolveSchema(doc, media?.schema);
}

// the parser

const METHODS = ["get", "post", "put", "patch", "delete"] as const;

/**
 * Parses an OpenAPI document (fetched from the backend's schemaUrl) into the
 * normalized registry. Tolerates anything it does not understand: unknown
 * constructs become kind "unknown" fields, paths without x-karni-resource are
 * ignored, and a malformed document yields an empty registry.
 */
export function parseOpenApi(input: unknown): ParsedSchema {
  const doc: OpenApiDocument = isRecord(input) ? (input as OpenApiDocument) : {};
  const paths = isRecord(doc.paths) ? doc.paths : {};

  const resources: Record<string, ResourceSchema> = {};
  const rawAuthMode = doc["x-karni-auth-mode"];
  const authMode = rawAuthMode === "jwt" || rawAuthMode === "session" ? rawAuthMode : undefined;

  // Pass 1: find every list operation via its x-karni-resource marker.
  const listOps: Array<{ resource: string; path: string; item: PathItemObject }> = [];
  for (const [path, item] of Object.entries(paths)) {
    if (!isRecord(item)) continue;
    const get = item.get;
    if (isRecord(get) && typeof get["x-karni-resource"] === "string") {
      listOps.push({ resource: get["x-karni-resource"], path, item });
    }
  }

  for (const { resource, path, item } of listOps) {
    const listOp = item.get;
    if (!isRecord(listOp)) continue;

    // The item path is the collection path plus a single `{param}/` segment.
    const itemEntry = Object.entries(paths).find(([candidate]) => {
      if (!candidate.startsWith(path)) return false;
      const rest = candidate.slice(path.length);
      return /^\{[^/{}]+\}\/?$/.test(rest);
    });
    const itemPath = itemEntry?.[0];
    const itemItem = itemEntry !== undefined && isRecord(itemEntry[1]) ? itemEntry[1] : undefined;

    const operations: ResourceSchema["operations"] = {
      list: operationDef(doc, path, "get", listOp),
    };
    const createOp = isRecord(item.post) ? item.post : undefined;
    if (createOp !== undefined) operations.create = operationDef(doc, path, "post", createOp);
    if (itemPath !== undefined && itemItem !== undefined) {
      for (const method of METHODS) {
        const op = itemItem[method];
        if (!isRecord(op)) continue;
        if (method === "get") operations.detail = operationDef(doc, itemPath, "get", op);
        else if (method === "patch") operations.update = operationDef(doc, itemPath, "patch", op);
        else if (method === "put" && operations.update === undefined)
          operations.update = operationDef(doc, itemPath, "put", op);
        else if (method === "delete") operations.remove = operationDef(doc, itemPath, "delete", op);
      }
    }

    // Field derivation: response component of the list op + create request body.
    const responseSchema = listItemSchema(doc, listOp);
    const requestSchema = createOp !== undefined ? createRequestSchema(doc, createOp) : undefined;
    const hasCreateRequest = requestSchema !== undefined;

    const responseProps = isRecord(responseSchema?.properties) ? responseSchema.properties : {};
    const requestProps = isRecord(requestSchema?.properties) ? requestSchema.properties : {};
    // required comes from the CREATE REQUEST body only — never the response (D1).
    const requiredSet = new Set<string>(
      Array.isArray(requestSchema?.required) ? requestSchema.required : [],
    );

    const fields: FieldDef[] = [];
    let order = 0;
    for (const [name, prop] of Object.entries(responseProps)) {
      const responseInfo = analyzeProperty(doc, prop);
      const requestProp = requestProps[name];
      const requestInfo = requestProp !== undefined ? analyzeProperty(doc, requestProp) : undefined;
      fields.push(
        mergeField(name, responseInfo, requestInfo, requiredSet, hasCreateRequest, order),
      );
      order += 1;
    }
    for (const [name, prop] of Object.entries(requestProps)) {
      if (name in responseProps) continue;
      const requestInfo = analyzeProperty(doc, prop);
      fields.push(mergeField(name, undefined, requestInfo, requiredSet, hasCreateRequest, order));
      order += 1;
    }

    resources[resource] = { resource, operations, fields };
  }

  const parsed: ParsedSchema = { resources };
  if (authMode !== undefined) parsed.authMode = authMode;
  return parsed;
}
