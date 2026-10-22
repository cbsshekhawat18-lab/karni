import * as React from "react";
import { useChangeHistory, type ChangeLogEntry } from "../../../hooks/useChangeHistory";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { Skeleton } from "../../primitives/skeleton";

registerComponentRole("change-history", "ChangeHistory");

export interface ChangeHistoryProps {
  resource: string;
  id: string | number;
  /** Entries to show (the backend paginates; default: the API's page size). */
  pageSize?: number;
  title?: React.ReactNode;
  /** Shown when the row has no recorded changes. */
  empty?: React.ReactNode;
  className?: string;
}

const ACTION_LABEL: Record<ChangeLogEntry["action"], string> = {
  create: "Created",
  update: "Updated",
  delete: "Deleted",
  restore: "Restored",
  transition: "Transitioned",
};

function formatWhen(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function Value({ value }: { value: unknown }): React.ReactElement {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (value === "[redacted]") {
    return <span className="italic text-muted-foreground">redacted</span>;
  }
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return <span className="break-words">{text}</span>;
}

function Entry({ entry }: { entry: ChangeLogEntry }): React.ReactElement {
  const fields = Object.entries(entry.diff);
  return (
    <li className="rounded-md border bg-card p-3 text-sm" data-action={entry.action}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{ACTION_LABEL[entry.action] ?? entry.action}</span>
        <time dateTime={entry.timestamp} className="text-muted-foreground">
          {formatWhen(entry.timestamp)}
        </time>
        <span className="text-muted-foreground">{entry.actor?.email ?? "—"}</span>
      </div>
      {fields.length > 0 ? (
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
          {fields.map(([name, [before, after]]) => (
            <React.Fragment key={name}>
              <dt className="font-mono text-xs text-muted-foreground">{name}</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <Value value={before} />
                <span aria-hidden="true" className="text-muted-foreground">
                  →
                </span>
                <Value value={after} />
              </dd>
            </React.Fragment>
          ))}
        </dl>
      ) : (
        <p className="mt-2 text-muted-foreground">No visible field changed.</p>
      )}
    </li>
  );
}

/**
 * The field-level change history of one row: when, by whom, what changed
 * from what to what. Reads `GET /<resource>/<id>/history/` (models that opt
 * in with `class Karni: audit = True`); fields the role may not see are
 * already absent from each diff, redacted ones say so.
 */
export function ChangeHistory({
  resource,
  id,
  pageSize,
  title = "History",
  empty = "No changes recorded.",
  className,
}: ChangeHistoryProps): React.ReactElement {
  const query = useChangeHistory(resource, id, pageSize !== undefined ? { pageSize } : undefined);
  return (
    <section className={cn("space-y-3", className)} aria-label="Change history">
      {title !== null ? <h3 className="text-base font-semibold">{title}</h3> : null}
      {query.isPending ? (
        <div className="space-y-2" data-testid="change-history-loading">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : query.error ? (
        <p role="alert" className="text-sm text-destructive">
          {query.error instanceof Error ? query.error.message : "History could not be loaded."}
        </p>
      ) : query.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ol className="space-y-2">
          {query.data.results.map((entry) => (
            <Entry key={entry.id} entry={entry} />
          ))}
        </ol>
      )}
    </section>
  );
}
