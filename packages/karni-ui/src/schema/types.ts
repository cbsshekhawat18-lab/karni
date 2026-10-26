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
  /**
   * A lifecycle field (a StateField on the server): every state mapped to the
   * states it may move to, from `x-karni-transitions`. A terminal state maps
   * to `[]`. A display hint only: the server refuses an illegal move.
   */
  transitions?: Readonly<Record<string, readonly string[]>>;
  /** The states a new row may start in (`x-karni-initial`), with `transitions`. */
  initial?: readonly string[];
  /** Declaration order in the schema (response props first, request-only appended). */
  order: number;
}

/** One named count on the dashboard: a label and the list filters it counts with. */
export interface DashboardCountDef {
  label: string;
  /**
   * List query parameters. A value `"today"`, `"today-7"` or `"today+1"` is a
   * date relative to the day the page is viewed.
   */
  params: Readonly<
    Record<string, string | number | boolean | ReadonlyArray<string | number | boolean>>
  >;
}

/**
 * A model's `Karni.dashboard` declaration, normalized by the server and
 * published as `x-karni-dashboard` on the list operation.
 */
export interface DashboardDef {
  /** The section heading ("Orders"). */
  label: string;
  /** Sections sort by this, then by label. */
  order: number;
  /** A count of every row the user may read. */
  total: boolean;
  /** A count of the rows created in the last N days (0: none). */
  newDays: number;
  /** What "new" and "newest" are measured by (`created_at`), or null. */
  dateField: string | null;
  /** A count per value of this field (a StateField, choices or boolean), or null. */
  by: string | null;
  /** The values of `by` that get a count. */
  values: readonly string[];
  /** Named counts, each with its filters. */
  counts: readonly DashboardCountDef[];
  /** How many of the newest rows the table shows (0: no table). */
  recent: number;
  /** The table's columns. Null: ResourceTable's default columns. */
  columns: readonly string[] | null;
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
  /**
   * `x-karni-honeypot` on a public create: the name of a field no person
   * fills in. ResourceForm renders it hidden and sends it only when filled.
   */
  honeypot?: string;
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
  /** The model's dashboard declaration (`x-karni-dashboard`), when it opts in. */
  dashboard?: DashboardDef;
}

/** The whole parsed registry, produced once per schema fetch by parseOpenApi. */
export interface ParsedSchema {
  /** Keyed by router prefix (x-karni-resource). */
  resources: Record<string, ResourceSchema>;
  /** From the schema root's x-karni-auth-mode (api B14). Undefined when absent. */
  authMode?: "jwt" | "session";
}
