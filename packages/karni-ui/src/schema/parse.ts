/**
 * OpenAPI → ResourceSchema parser (contract "Schema client" + amendment D1).
 *
 * Parses the real drf-spectacular dialect (OAS 3.0.3):
 * - resolves $ref against components.schemas (cycle-guarded),
 * - unwraps single-member allOf, merging its siblings (drf-spectacular uses
 *   `allOf: [$ref] + readOnly/description` for annotated enum fields),
 * - maps oneOf [XEnum, NullEnum | BlankEnum] → kind "enum" (+ nullable from
 *   NullEnum, with BlankEnum's "" excluded from enumValues),
 * - handles `nullable: true` (3.0) and `type: [T, "null"]` (future-proofing),
 * - split-components merge algebra (COMPONENT_SPLIT_REQUEST=True, api B14):
 *   fields = union(response props, create-request props), readOnly = flagged
 *   OR response-only, writeOnly = flagged OR request-only, and required = the
 *   CREATE REQUEST body's required array ONLY. Resources without a create op
 *   fall back to response-only, all readOnly,
 * - kind "file" = request-side `format: binary` (the response-side format: uri
 *   is just the display URL),
 * - a formatted string that may be blank, `oneOf [{format}, {maxLength: 0}]`
 *   (drf-spectacular's form for a blank email, URL or markdown field), is
 *   that string. `format: markdown` (a MarkdownField) is kind "text",
 * - unknown/unsupported constructs land as kind "unknown" (never crash).
 *
 * This module is internal to @karni/ui (not re-exported from the barrel), but
 * sibling builders (hooks/auth/components) import it relatively.
 */

import type {
  ColumnSetDef,
  ColumnSetsDef,
  DashboardCountDef,
  DashboardDef,
  FieldDef,
  FieldGroupDef,
  FieldGroupsDef,
  FieldKind,
  OperationDef,
  ParsedSchema,
  RelatedDef,
  RelationRef,
  ResourceSchema,
  TreeRef,
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

/** "starts_at" → "Starts at", "is_public" → "Is public". */
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
 * the enum schema plus readOnly). Cycle-guarded: a cycle resolves to {}.
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
  enumLabels?: Readonly<Record<string, string>>;
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
  transitions?: Readonly<Record<string, readonly string[]>>;
  initial?: readonly string[];
  tree?: TreeRef;
  taxonomy?: string;
  protectedFile?: true;
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

/**
 * Experimental. The `x-karni-tree` extension (`{"parent": "parent", "ordered": bool}`)
 * of a tree model's component schema or of a relation pointing at one, when well formed.
 */
export function parseTreeExtension(raw: unknown): TreeRef | undefined {
  if (raw === true) return { parent: "parent", ordered: false };
  if (!isRecord(raw)) return undefined;
  const parent = typeof raw.parent === "string" && raw.parent !== "" ? raw.parent : "parent";
  return { parent, ordered: raw.ordered === true };
}

function stringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((item): item is string => typeof item === "string");
}

/** `x-karni-transitions` (state → next states) and `x-karni-initial`, when well formed. */
function lifecycleFromExtension(
  schema: SchemaObject,
): Pick<PropertyInfo, "transitions" | "initial"> {
  const raw = schema["x-karni-transitions"];
  if (!isRecord(raw)) return {};
  const transitions: Record<string, readonly string[]> = {};
  for (const [state, next] of Object.entries(raw)) {
    const targets = stringList(next);
    if (targets !== undefined) transitions[state] = targets;
  }
  const initial = stringList(schema["x-karni-initial"]);
  return initial !== undefined ? { transitions, initial } : { transitions };
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
): { values: Array<string | number>; nullable: boolean; description?: string } | undefined {
  const values: Array<string | number> = [];
  let nullable = false;
  let description: string | undefined;
  for (const member of members) {
    const resolved = resolveSchema(doc, member, seen);
    if (resolved === undefined || !Array.isArray(resolved.enum)) return undefined;
    if (description === undefined && resolved.description !== undefined && values.length === 0) {
      description = resolved.description; // the XEnum member carries the choice list
    }
    for (const value of resolved.enum) {
      if (value === null) {
        nullable = true; // NullEnum
      } else if (value !== "") {
        values.push(value); // BlankEnum's "" excluded from enumValues (D1)
      }
    }
  }
  return { values, nullable, description };
}

const CHOICE_LINE = /^\* `(.+?)` - (.*)$/;

/**
 * Splits drf-spectacular's generated choice list ("* `draft` - Draft" per
 * line, appended to a ChoiceField's description) into labels by value and
 * the human help text that remains (undefined when nothing remains). The
 * raw list is markdown a form would otherwise show verbatim as help text.
 */
export function choiceLabels(description: string | undefined): {
  labels?: Record<string, string>;
  rest?: string;
} {
  if (description === undefined) return {};
  const labels: Record<string, string> = {};
  const rest: string[] = [];
  for (const line of description.split("\n")) {
    const match = CHOICE_LINE.exec(line.trim());
    if (match !== null && match[1] !== undefined && match[2] !== undefined) {
      labels[match[1]] = match[2].trim();
    } else {
      rest.push(line);
    }
  }
  const text = rest.join("\n").trim();
  return {
    ...(Object.keys(labels).length > 0 ? { labels } : {}),
    ...(text !== "" ? { rest: text } : {}),
  };
}

function applyChoiceLabels(info: PropertyInfo, description: string | undefined): void {
  const { labels, rest } = choiceLabels(description);
  if (labels !== undefined) info.enumLabels = labels;
  info.description = rest;
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

/** True for drf-spectacular's "may be blank" member: `{type: "string", maxLength: 0}`. */
function isBlankString(schema: SchemaObject | undefined): boolean {
  return schema !== undefined && schema.type === "string" && schema.maxLength === 0;
}

/**
 * `oneOf [<formatted string>, {type: string, maxLength: 0}]`: drf-spectacular's
 * schema for a formatted string field that may be blank. Returns the string
 * member with the outer keys (readOnly, nullable, description, ...) merged in.
 */
function blankableString(
  doc: OpenApiDocument,
  schema: SchemaObject,
  members: readonly SchemaObject[],
): SchemaObject | undefined {
  if (members.length !== 2) return undefined;
  const resolved = members.map((member) => resolveSchema(doc, member));
  const blank = resolved.findIndex(isBlankString);
  const value = resolved[blank === 0 ? 1 : 0];
  if (blank === -1 || value === undefined || value.type !== "string") return undefined;
  const outer: SchemaObject = { ...schema };
  delete outer.oneOf;
  delete outer.anyOf;
  return { ...value, ...outer };
}

function analyzeProperty(doc: OpenApiDocument, raw: SchemaObject): PropertyInfo {
  const found = resolveSchema(doc, raw) ?? {};
  const members = found.oneOf ?? found.anyOf;
  const resolved =
    (Array.isArray(members) ? blankableString(doc, found, members) : undefined) ?? found;
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
    ...lifecycleFromExtension(resolved),
  };
  const tree = parseTreeExtension(resolved["x-karni-tree"] ?? raw["x-karni-tree"]);
  if (tree !== undefined) info.tree = tree;
  const taxonomy = resolved["x-karni-taxonomy"] ?? raw["x-karni-taxonomy"];
  if (typeof taxonomy === "string" && taxonomy !== "") info.taxonomy = taxonomy;

  const storage = resolved["x-karni-storage"] ?? raw["x-karni-storage"];
  if (isRecord(storage) && storage["protected"] === true) info.protectedFile = true;

  // drf-spectacular nullable/blank enums: oneOf [XEnum, BlankEnum?, NullEnum?].
  const composition = resolved.oneOf ?? resolved.anyOf;
  if (Array.isArray(composition)) {
    const combined = combineEnumMembers(doc, composition, []);
    if (combined !== undefined) {
      info.kind = "enum";
      info.enumValues = combined.values;
      info.nullable = info.nullable || combined.nullable;
      applyChoiceLabels(info, resolved.description ?? combined.description);
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
    applyChoiceLabels(info, resolved.description);
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
      } else if (resolved.format === "markdown") {
        // A MarkdownField: long text, edited with a preview and shown formatted.
        info.kind = "text";
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
  const enumLabels = requestInfo?.enumLabels ?? responseInfo?.enumLabels;
  if (enumLabels !== undefined) field.enumLabels = enumLabels;
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
  const transitions = responseInfo?.transitions ?? requestInfo?.transitions;
  if (transitions !== undefined) field.transitions = transitions;
  const initial = responseInfo?.initial ?? requestInfo?.initial;
  if (initial !== undefined) field.initial = initial;
  const tree = requestInfo?.tree ?? responseInfo?.tree;
  if (tree !== undefined && relation !== undefined) field.tree = tree;
  const taxonomy = responseInfo?.taxonomy ?? requestInfo?.taxonomy;
  if (taxonomy !== undefined && relation !== undefined) field.taxonomy = taxonomy;
  if (responseInfo?.protectedFile === true || requestInfo?.protectedFile === true) {
    field.protected = true;
  }

  return field;
}

// dashboard (x-karni-dashboard)

type DashboardParam = DashboardCountDef["params"][string];

function isScalar(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function dashboardParams(raw: unknown): DashboardCountDef["params"] | undefined {
  if (!isRecord(raw)) return undefined;
  const params: Record<string, DashboardParam> = {};
  for (const [name, value] of Object.entries(raw)) {
    if (isScalar(value)) params[name] = value;
    else if (Array.isArray(value)) params[name] = value.filter(isScalar);
  }
  return Object.keys(params).length > 0 ? params : undefined;
}

/**
 * The `x-karni-dashboard` extension of a list operation. The server fills in
 * every default, so this only checks the shapes, dropping what is malformed.
 */
export function parseDashboard(raw: unknown): DashboardDef | undefined {
  if (!isRecord(raw) || typeof raw.label !== "string") return undefined;
  const counts: DashboardCountDef[] = [];
  if (Array.isArray(raw.counts)) {
    for (const entry of raw.counts) {
      if (!isRecord(entry) || typeof entry.label !== "string") continue;
      const params = dashboardParams(entry.params);
      if (params !== undefined) counts.push({ label: entry.label, params });
    }
  }
  const whole = (value: unknown, fallback: number): number =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return {
    label: raw.label,
    order: whole(raw.order, 0),
    total: raw.total !== false,
    newDays: Math.max(0, whole(raw.new_days, 0)),
    dateField: typeof raw.date_field === "string" ? raw.date_field : null,
    by: typeof raw.by === "string" ? raw.by : null,
    values: stringList(raw.values) ?? [],
    counts,
    recent: Math.max(0, whole(raw.recent, 0)),
    columns: stringList(raw.columns) ?? null,
  };
}

// reverse relations (x-karni-related)

/**
 * Experimental. The `x-karni-related` extension of a list operation: the
 * reverse relations whose rows ResourceDetail's `related` tabs list. A
 * malformed entry is dropped.
 */
export function parseRelated(raw: unknown): RelatedDef[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const found: RelatedDef[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const { name, resource, field, param, key, label } = entry;
    if (typeof name !== "string" || typeof resource !== "string" || typeof field !== "string") {
      continue;
    }
    found.push({
      name,
      resource,
      field,
      param: typeof param === "string" && param !== "" ? param : null,
      key: typeof key === "string" && key !== "" ? key : "id",
      label: typeof label === "string" && label !== "" ? label : humanize(resource),
    });
  }
  return found;
}

// field groups and column sets (x-karni-field-groups, x-karni-column-sets)

/**
 * Experimental. The `x-karni-field-groups` extension of a list operation. A
 * group without a label or a field is dropped, and so is a field already in
 * an earlier group.
 */
export function parseFieldGroups(raw: unknown): FieldGroupsDef | undefined {
  if (!isRecord(raw) || !Array.isArray(raw.groups)) return undefined;
  const seen = new Set<string>();
  const groups: FieldGroupDef[] = [];
  for (const entry of raw.groups) {
    if (!isRecord(entry) || typeof entry.label !== "string" || entry.label === "") continue;
    const fields = (stringList(entry.fields) ?? []).filter((name) => !seen.has(name));
    for (const name of fields) seen.add(name);
    if (fields.length > 0) groups.push({ label: entry.label, fields });
  }
  if (groups.length === 0) return undefined;
  return { layout: raw.layout === "tabs" ? "tabs" : "sections", groups };
}

/**
 * Experimental. The `x-karni-column-sets` extension of a list operation. A set
 * without a name or a column is dropped. `default` falls back to the first set.
 */
export function parseColumnSets(raw: unknown): ColumnSetsDef | undefined {
  if (!isRecord(raw) || !Array.isArray(raw.sets)) return undefined;
  const sets: ColumnSetDef[] = [];
  for (const entry of raw.sets) {
    if (!isRecord(entry) || typeof entry.name !== "string" || entry.name === "") continue;
    const columns = stringList(entry.columns) ?? [];
    if (columns.length === 0 || sets.some((found) => found.name === entry.name)) continue;
    const label =
      typeof entry.label === "string" && entry.label !== "" ? entry.label : humanize(entry.name);
    sets.push({ name: entry.name, label, columns });
  }
  const first = sets[0];
  if (first === undefined) return undefined;
  const chosen = sets.find((found) => found.name === raw.default) ?? first;
  return { default: chosen.name, sets };
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
  const access = op["x-karni-access"];
  if (isRecord(access)) def.access = access;
  const honeypot = op["x-karni-honeypot"];
  if (typeof honeypot === "string" && honeypot !== "") def.honeypot = honeypot;
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
    // karni.transfer (P6): the export and import actions live under the list path.
    const exportItem = paths[`${path}export/`];
    const exportOp = isRecord(exportItem) && isRecord(exportItem.get) ? exportItem.get : undefined;
    if (exportOp !== undefined) {
      operations.export = operationDef(doc, `${path}export/`, "get", exportOp);
    }
    const importItem = paths[`${path}import/`];
    const importOp =
      isRecord(importItem) && isRecord(importItem.post) ? importItem.post : undefined;
    if (importOp !== undefined) {
      operations.import = operationDef(doc, `${path}import/`, "post", importOp);
    }
    // Tree models (experimental): tree/ under the list path, the rest under the item path.
    const treeItem = paths[`${path}tree/`];
    if (isRecord(treeItem) && isRecord(treeItem.get)) {
      operations.tree = operationDef(doc, `${path}tree/`, "get", treeItem.get);
    }
    const accessItem = paths[`${path}access/`];
    if (isRecord(accessItem) && isRecord(accessItem.get)) {
      operations.access = operationDef(doc, `${path}access/`, "get", accessItem.get);
    }
    // Taxonomies (experimental): facets/ under the list path.
    const facetsItem = paths[`${path}facets/`];
    if (isRecord(facetsItem) && isRecord(facetsItem.get)) {
      operations.facets = operationDef(doc, `${path}facets/`, "get", facetsItem.get);
    }
    if (itemPath !== undefined) {
      const base = itemPath.endsWith("/") ? itemPath : `${itemPath}/`;
      const nested: ReadonlyArray<["children" | "ancestors" | "move", "get" | "post"]> = [
        ["children", "get"],
        ["ancestors", "get"],
        ["move", "post"],
      ];
      for (const [name, method] of nested) {
        const nestedItem = paths[`${base}${name}/`];
        const op = isRecord(nestedItem) ? nestedItem[method] : undefined;
        if (isRecord(op)) operations[name] = operationDef(doc, `${base}${name}/`, method, op);
      }
    }
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

    const parsedResource: ResourceSchema = { resource, operations, fields };
    const dashboard = parseDashboard(listOp["x-karni-dashboard"]);
    if (dashboard !== undefined) parsedResource.dashboard = dashboard;
    const tree = parseTreeExtension(responseSchema?.["x-karni-tree"]);
    if (tree !== undefined) parsedResource.tree = tree;
    const related = parseRelated(listOp["x-karni-related"]);
    if (related !== undefined) parsedResource.related = related;
    const fieldGroups = parseFieldGroups(listOp["x-karni-field-groups"]);
    if (fieldGroups !== undefined) parsedResource.fieldGroups = fieldGroups;
    const columnSets = parseColumnSets(listOp["x-karni-column-sets"]);
    if (columnSets !== undefined) parsedResource.columnSets = columnSets;
    resources[resource] = parsedResource;
  }

  const parsed: ParsedSchema = { resources };
  if (authMode !== undefined) parsed.authMode = authMode;
  return parsed;
}
