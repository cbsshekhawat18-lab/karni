/**
 * Schema → TanStack column derivation (contract "ResourceTable" + D5).
 *
 * - Domain fields first, in declaration order. writeOnly / json / file /
 *   unknown fields and markdown (a MarkdownField's long text) are skipped
 *   unless the consumer explicitly names them in the `columns` prop.
 * - A column set (`only`) shows exactly its fields, in its
 *   order, whatever their kind. `columns` still overrides them, and its
 *   entries naming fields the schema does not declare are still appended.
 * - Audit fields (AUDIT_FIELDS: id, created_at, updated_at, created_by,
 *   updated_by) are hidden by default. A `columns` entry naming one (without
 *   `hidden: true`) or `showAuditFields` brings it back, after the domain
 *   columns, in AUDIT_FIELDS order.
 * - Column ids equal schema field names verbatim: that IS the DRF `ordering`
 *   contract (D5).
 * - relation / json / file / array / unknown columns are unsortable by
 *   default. The per-field `sortable` override wins both ways.
 * - Cells: booleans → check icon, dates localized, enum labels prettified,
 *   markdown → a one-line plain-text excerpt,
 *   relations → displayLabel of the expanded object else the raw id in
 *   <code>. The label heuristic is overridable via `getRowLabel`.
 */
import type { ColumnDef } from "@tanstack/react-table";
import * as React from "react";
import { humanize } from "../../../schema/parse";
import type { FieldDef, FieldKind } from "../../../schema/types";
import { protectedFileLinkFor } from "../protected-file";
import { CheckIcon } from "../../primitives/icons";
import { isAuditField, partitionAuditFields } from "../audit-fields";
import { personName, relationLabel } from "../displayLabel";
import { EmptyValue } from "../empty-value";
import { isMarkdownField, markdownExcerpt } from "../markdown-field";
import { formatMoneyValue, formatNumberValue } from "../number-value";
import { RecordLink } from "../record-links";
import { asRecord, enumLabel } from "./table-utils";

/** Per-field override merged over the schema-derived column. */
export interface ResourceColumn<T = Record<string, unknown>> {
  field: string;
  header?: React.ReactNode;
  cell?: (row: T) => React.ReactNode;
  hidden?: boolean;
  sortable?: boolean;
}

type RowLabeler = (row: Record<string, unknown>) => string;

const DEFAULT_SKIPPED_KINDS: ReadonlySet<FieldKind> = new Set(["json", "file", "unknown"]);
const UNSORTABLE_KINDS: ReadonlySet<FieldKind> = new Set([
  "relation",
  "json",
  "file",
  "array",
  "unknown",
]);

function BooleanCell({ value }: { value: boolean }): React.ReactElement {
  return value ? (
    <span className="inline-flex items-center text-foreground">
      <CheckIcon className="h-4 w-4" />
      <span className="sr-only">Yes</span>
    </span>
  ) : (
    <span className="inline-flex items-center text-muted-foreground">
      <span aria-hidden="true">–</span>
      <span className="sr-only">No</span>
    </span>
  );
}

function IdCode({ value }: { value: unknown }): React.ReactElement {
  return <code className="rounded bg-muted px-1 py-0.5 text-xs">{String(value)}</code>;
}

function relationItem(item: unknown, label: RowLabeler, resource?: string): React.ReactNode {
  if (item === null || item === undefined) return <EmptyValue />;
  if (typeof item === "object" && !Array.isArray(item)) {
    return (
      <RecordLink resource={resource} row={item}>
        {label(asRecord(item))}
      </RecordLink>
    );
  }
  return <IdCode value={item} />;
}

function RelationCell({
  value,
  label,
  resource,
}: {
  value: unknown;
  label: RowLabeler;
  resource?: string;
}): React.ReactElement {
  if (value === null || value === undefined) return <EmptyValue />;
  if (Array.isArray(value)) {
    if (value.length === 0) return <EmptyValue />;
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
        {value.map((item, index) => (
          <React.Fragment key={index}>{relationItem(item, label, resource)}</React.Fragment>
        ))}
      </span>
    );
  }
  return <>{relationItem(value, label, resource)}</>;
}

function dateText(value: unknown, withTime: boolean): string {
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return withTime ? parsed.toLocaleString() : parsed.toLocaleDateString();
}

function FileCell({ field, value }: { field: FieldDef; value: unknown }): React.ReactElement {
  if (typeof value === "string" && value.length > 0) {
    const Protected = protectedFileLinkFor(field);
    if (Protected !== null) {
      return (
        <span onClick={(event) => event.stopPropagation()}>
          <Protected href={value} className="text-primary underline underline-offset-4" />
        </span>
      );
    }
    const name = value.split("/").filter(Boolean).pop() ?? value;
    return (
      <a
        href={value}
        target="_blank"
        rel="noreferrer"
        className="text-primary underline underline-offset-4"
        onClick={(event) => event.stopPropagation()}
      >
        {name}
      </a>
    );
  }
  if (typeof File !== "undefined" && value instanceof File) return <>{value.name}</>;
  return <EmptyValue />;
}

function JsonCell({ value }: { value: unknown }): React.ReactElement {
  let text: string;
  try {
    text = JSON.stringify(value) ?? String(value);
  } catch {
    text = String(value);
  }
  const shown = text.length > 80 ? `${text.slice(0, 80)}…` : text;
  return (
    <code className="rounded bg-muted px-1 py-0.5 text-xs" title={text}>
      {shown}
    </code>
  );
}

/**
 * Default cell renderer for a schema field's value. Exported for reuse by
 * custom cells that want the stock formatting for other fields.
 */
export function renderFieldCell(
  field: FieldDef,
  value: unknown,
  getRowLabel?: RowLabeler,
  row?: Readonly<Record<string, unknown>> | null,
): React.ReactNode {
  // The same empty rendering as ResourceDetail: a dash, read as "empty".
  if (value === null || value === undefined || value === "") return <EmptyValue />;
  const money = formatMoneyValue(field, value, row);
  if (money !== null) return <span className="tabular-nums">{money}</span>;
  // A person (x-karni-user): their name once the table expanded them, never the id.
  if (field.person === true && typeof value === "object" && !Array.isArray(value)) {
    return <>{(getRowLabel ?? personName)(asRecord(value))}</>;
  }
  switch (field.kind) {
    case "boolean":
      return <BooleanCell value={value === true} />;
    case "date":
      return dateText(value, false);
    case "datetime":
      return dateText(value, true);
    case "enum":
      return typeof value === "string" || typeof value === "number"
        ? enumLabel(value, field.enumLabels)
        : String(value);
    case "relation":
      return (
        <RelationCell
          value={value}
          label={getRowLabel ?? ((item) => relationLabel(field, item))}
          resource={field.relation?.resource}
        />
      );
    case "number":
    case "integer":
      return (
        <span className="tabular-nums">
          {typeof value === "number" ? formatNumberValue(field, value) : String(value)}
        </span>
      );
    case "file":
      return <FileCell field={field} value={value} />;
    case "json":
      return <JsonCell value={value} />;
    case "array":
      return Array.isArray(value) ? value.map((item) => String(item)).join(", ") : String(value);
    case "text": {
      const text = isMarkdownField(field) ? markdownExcerpt(String(value)) : String(value);
      return (
        <span className="block max-w-80 truncate" title={text}>
          {text}
        </span>
      );
    }
    default:
      return String(value);
  }
}

/** ColumnDef.header only takes a string or a render function, so nodes get wrapped. */
function headerTemplate<T>(content: React.ReactNode): ColumnDef<T>["header"] {
  return typeof content === "string" ? content : () => content;
}

export interface DeriveColumnsArgs<T> {
  fields: readonly FieldDef[];
  columns?: ReadonlyArray<ResourceColumn<T>>;
  getRowLabel?: RowLabeler;
  /** Show every audit field (AUDIT_FIELDS) without naming each in `columns`. */
  showAuditFields?: boolean;
  /** A column set: exactly these fields, in this order. */
  only?: readonly string[];
}

function columnForField<T>(
  field: FieldDef,
  override: ResourceColumn<T> | undefined,
  getRowLabel: RowLabeler | undefined,
): ColumnDef<T> {
  const customCell = override?.cell;
  return {
    id: field.name,
    accessorFn: (row) => asRecord(row)[field.name],
    header: headerTemplate(override?.header ?? field.label),
    cell:
      customCell !== undefined
        ? (ctx) => customCell(ctx.row.original)
        : (ctx) =>
            renderFieldCell(
              field,
              ctx.getValue(),
              getRowLabel,
              ctx.row.original as Readonly<Record<string, unknown>>,
            ),
    enableSorting: override?.sortable ?? !UNSORTABLE_KINDS.has(field.kind),
  };
}

/**
 * Builds the derived column set: domain columns (schema order), then any
 * shown audit columns (AUDIT_FIELDS order), then `columns` entries naming
 * fields the schema does not declare, as plain accessor columns (escape hatch
 * for computed or server-extra keys). `columns` overrides merge onto their
 * fields, and naming a default-skipped field (json, audit, ...) shows it.
 */
export function deriveColumns<T>(args: DeriveColumnsArgs<T>): Array<ColumnDef<T>> {
  const pending = new Map<string, ResourceColumn<T>>(
    (args.columns ?? []).map((column) => [column.field, column]),
  );
  const defs: Array<ColumnDef<T>> = [];
  const { domain, audit } = partitionAuditFields(args.fields);
  const byName = new Map(args.fields.map((field) => [field.name, field]));
  const only = args.only;
  const ordered =
    only !== undefined
      ? only
          .map((name) => byName.get(name))
          .filter((field): field is FieldDef => field !== undefined && !field.writeOnly)
      : [...domain, ...audit];

  for (const field of ordered) {
    const override = pending.get(field.name);
    pending.delete(field.name);
    if (override?.hidden === true) continue;
    if (override === undefined && only === undefined) {
      if (field.writeOnly || DEFAULT_SKIPPED_KINDS.has(field.kind)) continue;
      if (isMarkdownField(field)) continue;
      if (args.showAuditFields !== true && isAuditField(field)) continue;
    }
    defs.push(columnForField(field, override, args.getRowLabel));
  }

  for (const [name, override] of pending) {
    if (override.hidden === true) continue;
    // With a column set, the set decides which schema fields show.
    if (only !== undefined && byName.has(name)) continue;
    const customCell = override.cell;
    defs.push({
      id: name,
      accessorFn: (row) => asRecord(row)[name],
      header: headerTemplate(override.header ?? humanize(name)),
      cell:
        customCell !== undefined
          ? (ctx) => customCell(ctx.row.original)
          : (ctx) => {
              const value = ctx.getValue();
              return value === null || value === undefined ? <EmptyValue /> : String(value);
            },
      enableSorting: override.sortable ?? false,
    });
  }

  return defs;
}
