import * as React from "react";
import { useResourceItem } from "../../../hooks/useResourceItem";
import type { ResourceItemParams } from "../../../hooks/types";
import { cn } from "../../../lib/cn";
import type { FieldDef } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { Button } from "../../primitives/button";
import { Skeleton } from "../../primitives/skeleton";
import { partitionAuditFields } from "../audit-fields";
import { displayLabel } from "../displayLabel";
import { humanizeValue } from "../form/prepare";
import { registerComponentRole } from "../../../lib/roles";

registerComponentRole("detail-view", "ResourceDetail");

export interface ResourceDetailFieldOverride {
  label?: string;
  hidden?: boolean;
  render?: (value: unknown, item: Record<string, unknown>) => React.ReactNode;
}

export interface ResourceDetailProps {
  resource: string;
  id: string | number;
  fields?: Record<string, ResourceDetailFieldOverride>;
  /** Appended below the field list (e.g. a child <ResourceTable>). */
  sections?: ReadonlyArray<React.ReactNode>;
  expand?: readonly string[];
  title?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

function fileBasename(url: string): string {
  const withoutQuery = url.split(/[?#]/, 1)[0] ?? url;
  const segments = withoutQuery.split("/").filter((segment) => segment !== "");
  return segments[segments.length - 1] ?? url;
}

function formatDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (match !== null) {
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return date.toLocaleDateString();
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function RelationEntry({ value }: { value: unknown }): React.ReactElement {
  if (value !== null && typeof value === "object") {
    return <>{displayLabel(value as Record<string, unknown>)}</>;
  }
  return <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{String(value)}</code>;
}

function RelationValue({ value }: { value: unknown }): React.ReactElement {
  if (Array.isArray(value)) {
    if (value.length === 0) return <EmptyValue />;
    return (
      <span className="flex flex-wrap gap-1.5">
        {value.map((entry, index) => (
          <span
            key={index}
            className="inline-flex items-center rounded-sm bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground"
          >
            <RelationEntry value={entry} />
          </span>
        ))}
      </span>
    );
  }
  return <RelationEntry value={value} />;
}

function EmptyValue(): React.ReactElement {
  return <span className="text-muted-foreground">—</span>;
}

/** Default value renderer per field kind; overridable per field via `fields`. */
function DefaultValue({ field, value }: { field: FieldDef; value: unknown }): React.ReactElement {
  if (value === undefined || value === null || value === "") return <EmptyValue />;
  switch (field.kind) {
    case "boolean":
      return <>{value ? "Yes" : "No"}</>;
    case "date":
      return <>{formatDate(String(value))}</>;
    case "datetime":
      return <>{formatDateTime(String(value))}</>;
    case "enum":
      return <>{field.enumLabels?.[String(value)] ?? humanizeValue(String(value))}</>;
    case "relation":
      return <RelationValue value={value} />;
    case "file":
      return (
        <a
          href={String(value)}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-primary underline underline-offset-4"
        >
          {fileBasename(String(value))}
        </a>
      );
    case "json":
      return (
        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(value, null, 2)}
        </pre>
      );
    case "number":
    case "integer":
      return <>{typeof value === "number" ? value.toLocaleString() : String(value)}</>;
    case "array":
      return <>{Array.isArray(value) ? value.map(String).join(", ") : String(value)}</>;
    default:
      return <>{String(value)}</>;
  }
}

function DetailSkeleton({ className }: { className?: string }): React.ReactElement {
  return (
    <div role="status" aria-label="Loading details" className={cn("space-y-4", className)}>
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-48 sm:col-span-2" />
        </div>
      ))}
    </div>
  );
}

function DetailError({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry: () => void;
  className?: string;
}): React.ReactElement {
  return (
    <div
      role="alert"
      className={cn(
        "space-y-3 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive",
        className,
      )}
    >
      <p>{error instanceof Error ? error.message : String(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

function DetailRow(props: {
  field: FieldDef;
  item: Record<string, unknown>;
  override: ResourceDetailFieldOverride | undefined;
  muted: boolean;
}): React.ReactElement {
  const { field, item, override, muted } = props;
  const value = item[field.name];
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-1 sm:grid-cols-3 sm:gap-4",
        muted ? "py-2 text-xs" : "py-3 text-sm",
      )}
    >
      <dt className="font-medium text-muted-foreground">{override?.label ?? field.label}</dt>
      <dd className={cn("sm:col-span-2", muted ? "text-muted-foreground" : "text-foreground")}>
        {override?.render !== undefined ? (
          override.render(value, item)
        ) : (
          <DefaultValue field={field} value={value} />
        )}
      </dd>
    </div>
  );
}

/**
 * Schema-driven read view (contract "ResourceDetail"): a definition list of
 * every non-writeOnly field — domain fields first (schema order), then the
 * audit fields (AUDIT_FIELDS: id, created_at, updated_at, created_by,
 * updated_by) in a visually muted "Record" group. Relations render through
 * displayLabel when the object is expanded (the field is in `expand`), else
 * as the raw id in <code>. Escape hatches: per-field `fields` overrides
 * (label/hidden/render — audit fields included), appended `sections`, and the
 * title/actions header slots.
 */
export function ResourceDetail(props: ResourceDetailProps): React.ReactElement {
  const { resource, id, fields, sections, expand, title, actions, className } = props;
  const recordHeadingId = React.useId();
  const schemaResult = useSchema(resource);
  const params: ResourceItemParams | undefined = React.useMemo(
    () => (expand !== undefined && expand.length > 0 ? { expand } : undefined),
    [expand],
  );
  const itemQuery = useResourceItem(resource, id, params);

  const error = schemaResult.error ?? itemQuery.error;
  if (error != null) {
    return (
      <DetailError
        error={error}
        onRetry={() => {
          void itemQuery.refetch();
        }}
        className={className}
      />
    );
  }
  if (schemaResult.data === undefined || itemQuery.data === undefined) {
    return <DetailSkeleton className={className} />;
  }

  const item = itemQuery.data;
  const visibleFields = schemaResult.data.fields.filter(
    (field) =>
      !field.writeOnly && field.kind !== "unknown" && fields?.[field.name]?.hidden !== true,
  );
  const { domain, audit } = partitionAuditFields(visibleFields);

  return (
    <div className={cn("space-y-6", className)}>
      {title !== undefined || actions !== undefined ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {title !== undefined ? (
            <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          ) : (
            <div />
          )}
          {actions !== undefined ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <dl className="divide-y divide-border">
        {domain.map((field) => (
          <DetailRow
            key={field.name}
            field={field}
            item={item}
            override={fields?.[field.name]}
            muted={false}
          />
        ))}
      </dl>
      {audit.length > 0 ? (
        <section
          aria-labelledby={recordHeadingId}
          className="rounded-md border border-border bg-muted/40 px-4 py-2"
        >
          <h3
            id={recordHeadingId}
            className="py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Record
          </h3>
          <dl className="divide-y divide-border">
            {audit.map((field) => (
              <DetailRow
                key={field.name}
                field={field}
                item={item}
                override={fields?.[field.name]}
                muted
              />
            ))}
          </dl>
        </section>
      ) : null}
      {sections !== undefined && sections.length > 0 ? (
        <div className="space-y-6">
          {sections.map((section, index) => (
            <div key={index}>{section}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
