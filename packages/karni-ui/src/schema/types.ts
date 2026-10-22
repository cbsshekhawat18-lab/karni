/**
 * Normalized schema registry types (karni-ui-contract.md "Schema client" + D1).
 *
 * The OpenAPI document served by the karni backend (drf-spectacular, OAS 3.0.3,
 * COMPONENT_SPLIT_REQUEST=True per api contract B14) is parsed ONCE into these
 * shapes. Every generic component consumes FieldDef/ResourceSchema, never raw
 * OpenAPI.
 */

export type FieldKind =
  | "string"
  | "text"
  | "number"
  | "integer"
  | "boolean"
  | "date"
  | "datetime"
  | "enum"
  | "relation"
  | "file"
  | "json"
  | "array"
  | "unknown";

/** Derived from the x-karni-relation vendor extension (api contract B13). */
export interface RelationRef {
  resource: string;
  many: boolean;
}

export interface FieldDef {
  name: string;
  /** Humanized from the property name (or the schema `title` when present). */
  label: string;
  kind: FieldKind;
  /** From the CREATE request body's required array only (D1). */
  required: boolean;
  /** Flagged readOnly OR present only in the response component (D1). */
  readOnly: boolean;
  /** Flagged writeOnly OR present only in the request component (D1). */
  writeOnly: boolean;
  nullable: boolean;
  /** Enum members. BlankEnum's "" and NullEnum's null are never members (D1/D3). */
  enumValues?: ReadonlyArray<string | number>;
  /** Choice labels by value, from drf-spectacular's "* `value` - Label" description lines. */
  enumLabels?: Readonly<Record<string, string>>;
  /** The schema's `default` (a model default): forms start from it on create. */
  default?: unknown;
  maxLength?: number;
  min?: number;
  max?: number;
  format?: string;
  /** Schema `description`, surfaced as field help text. */
  description?: string;
  /** Present only when x-karni-relation was emitted (degrades gracefully). */
  relation?: RelationRef;
  /**
   * Underlying pk value type of a relation field, derived from the property's
   * own emitted type/format, never assumed (D3). Drives zodFor's relation
   * value schema (uuid string vs integer).
   */
  relationValueType?: "uuid" | "integer" | "string";
  /** Declaration order in the schema (response props first, request-only appended). */
  order: number;
}

/**
 * An operation's `x-karni-access` rule as the backend publishes it: the access
 * predicate governing the operation, e.g. `{"role": ["staff"]}`,
 * `{"owned": "organizer"}`, `{"any": [...]}`. A display hint only: the server
 * enforces it.
 */
export type KarniAccessRule = Readonly<Record<string, unknown>>;

export interface OperationDef {
  path: string;
  method: "get" | "post" | "put" | "patch" | "delete";
  operationId?: string;
  /** Declared query parameter names. The filter bar derives from these (D5). */
  queryParams: readonly string[];
  /** Allowed expand keys when the expand param declares an enum (D5). */
  expandEnum?: readonly string[];
  /** True when the operation declares a `search` query parameter (api B14). */
  hasSearch?: boolean;
  /** The operation's `x-karni-access` rule, when the backend published one. */
  access?: KarniAccessRule;
}

export interface ResourceSchema {
  /** Router prefix, e.g. "events" (from x-karni-resource). */
  resource: string;
  operations: {
    list?: OperationDef;
    detail?: OperationDef;
    create?: OperationDef;
    update?: OperationDef;
    remove?: OperationDef;
    /** `GET /<resource>/export/`: the list as a CSV/XLSX file (karni.transfer, P6). */
    export?: OperationDef;
    /** `POST /<resource>/import/`: the import flow (upload, preview, commit). */
    import?: OperationDef;
  };
  /** Ordered by declaration. Unknown constructs land as kind "unknown". */
  fields: readonly FieldDef[];
}

/** The whole parsed registry, produced once per schema fetch by parseOpenApi. */
export interface ParsedSchema {
  /** Keyed by router prefix (x-karni-resource). */
  resources: Record<string, ResourceSchema>;
  /** From the schema root's x-karni-auth-mode (api B14). Undefined when absent. */
  authMode?: "jwt" | "session";
}
