/**
 * Schema → TanStack column derivation (contract "ResourceTable" + D5).
 *
 * - Domain fields first, in declaration order; writeOnly / json / file /
 *   unknown fields are skipped unless the consumer explicitly names them in
 *   the `columns` prop.
 * - Audit fields (AUDIT_FIELDS: id, created_at, updated_at, created_by,
 *   updated_by) are hidden by default. A `columns` entry naming one (without
 *   `hidden: true`) or `showAuditFields` brings it back, after the domain
 *   columns, in AUDIT_FIELDS order.
 * - Column ids equal schema field names verbatim — that IS the DRF `ordering`
 *   contract (D5).
 * - relation / json / file / array / unknown columns are unsortable by
 *   default; the per-field `sortable` override wins both ways.
 * - Cells: booleans → check icon, dates localized, enum labels prettified,
 *   relations → displayLabel of the expanded object else the raw id in
 *   <code>. The label heuristic is overridable via `getRowLabel`.
 */
import type { ColumnDef } from "@tanstack/react-table";
import * as React from "react";
import { humanize } from "../../../schema/parse";
import type { FieldDef, FieldKind } from "../../../schema/types";
import { CheckIcon } from "../../primitives/icons";
import { isAuditField, partitionAuditFields } from "../audit-fields";
import { displayLabel } from "../displayLabel";
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

function EmptyValue(): React.ReactElement {
  return (
    <span aria-hidden="true" className="text-muted-foreground">
      –
    </span>
  );
}

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

function relationItem(item: unknown, label: RowLabeler): React.ReactNode {
  if (item === null || item === undefined) return <EmptyValue />;
  if (typeof item === "object" && !Array.isArray(item)) return label(asRecord(item));
  return <IdCode value={item} />;
}

function RelationCell({ value, label }: { value: unknown; label: RowLabeler }): React.ReactElement {
  if (value === null || value === undefined) return <EmptyValue />;
  if (Array.isArray(value)) {
    if (value.length === 0) return <EmptyValue />;
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
        {value.map((item, index) => (
          <React.Fragment key={index}>{relationItem(item, label)}</React.Fragment>
        ))}
      </span>
    );
  }
  return <>{relationItem(value, label)}</>;
}

function dateText(value: unknown, withTime: boolean): string {
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return withTime ? parsed.toLocaleString() : parsed.toLocaleDateString();
}

function FileCell({ value }: { value: unknown }): React.ReactElement {
  if (typeof value === "string" && value.length > 0) {
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
): React.ReactNode {
  if (value === null || value === undefined) return <EmptyValue />;
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
      return <RelationCell value={value} label={getRowLabel ?? displayLabel} />;
    case "number":
    case "integer":
      return (
        <span className="tabular-nums">
          {typeof value === "number" ? value.toLocaleString() : String(value)}
        </span>
      );
    case "file":
      return <FileCell value={value} />;
    case "json":
      return <JsonCell value={value} />;
    case "array":
      return Array.isArray(value) ? value.map((item) => String(item)).join(", ") : String(value);
    case "text":
      return (
        <span className="block max-w-xs truncate" title={String(value)}>
          {String(value)}
        </span>
      );
    default:
      return String(value);
  }
}

/** ColumnDef.header only takes a string or a render function — wrap nodes. */
function headerTemplate<T>(content: React.ReactNode): ColumnDef<T>["header"] {
  return typeof content === "string" ? content : () => content;
}

export interface DeriveColumnsArgs<T> {
  fields: readonly FieldDef[];
  columns?: ReadonlyArray<ResourceColumn<T>>;
  getRowLabel?: RowLabeler;
  /** Show every audit field (AUDIT_FIELDS) without naming each in `columns`. */
  showAuditFields?: boolean;
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
        : (ctx) => renderFieldCell(field, ctx.getValue(), getRowLabel),
    enableSorting: override?.sortable ?? !UNSORTABLE_KINDS.has(field.kind),
  };
}

/**
 * Builds the derived column set: domain columns (schema order), then any
 * shown audit columns (AUDIT_FIELDS order), then `columns` entries naming
 * fields the schema does not declare — plain accessor columns (escape hatch
 * for computed or server-extra keys). `columns` overrides merge onto their
 * fields; naming a default-skipped field (json, audit, ...) shows it.
 */
export function deriveColumns<T>(args: DeriveColumnsArgs<T>): Array<ColumnDef<T>> {
  const pending = new Map<string, ResourceColumn<T>>(
    (args.columns ?? []).map((column) => [column.field, column]),
  );
  const defs: Array<ColumnDef<T>> = [];
  const { domain, audit } = partitionAuditFields(args.fields);

  for (const field of [...domain, ...audit]) {
    const override = pending.get(field.name);
    pending.delete(field.name);
    if (override?.hidden === true) continue;
    if (override === undefined) {
      if (field.writeOnly || DEFAULT_SKIPPED_KINDS.has(field.kind)) continue;
      if (args.showAuditFields !== true && isAuditField(field)) continue;
    }
    defs.push(columnForField(field, override, args.getRowLabel));
  }

  for (const [name, override] of pending) {
    if (override.hidden === true) continue;
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
