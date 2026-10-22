/**
 * <ApprovalsQueue> shows the pending changes the signed-in user may decide,
 * each with its diff, its maker, its progress and Approve / Reject with a
 * reason. It reads `GET /pending-changes/` through @karni/ui's
 * `useResourceList` and decides through `POST …/approve/` or `…/reject/`.
 * The backend enforces every rule (the maker cannot decide, scope, roles)
 * and answers 403 with the reason, which is shown on the item.
 *
 * Escape hatches: `renderItem` replaces an item's body, `empty` the empty
 * state, `params` adds list filters, `className` merges onto the list.
 */
import { Button, Skeleton, cn } from "@karni/ui";
import { useState, type ReactElement, type ReactNode } from "react";
import { useDecidePendingChange, usePendingChanges } from "./hooks";
import type { PendingChange } from "./types";

export interface ApprovalsQueueProps {
  /** Extra list params (filters merge over `status: "pending"`). */
  params?: { filters?: Record<string, string | number | boolean>; pageSize?: number };
  /** Shown when nothing is pending. */
  empty?: ReactNode;
  /** Replaces an item's body (the Approve/Reject row stays). */
  renderItem?: (change: PendingChange) => ReactNode;
  /** Called after a decision is recorded. */
  onDecided?: (change: PendingChange) => void;
  className?: string;
}

function errorText(error: unknown): string {
  if (error instanceof Error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === "object" && data !== null && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return error.message;
  }
  return "The decision could not be recorded.";
}

/**
 * No value: a muted dash that screen readers read as `label`. The same markup
 * as @karni/ui's EmptyValue, which is newer than this package's ^0.3.0 peer range.
 */
function Empty({ label = "empty" }: { label?: string }): ReactElement {
  return (
    <span className="text-muted-foreground">
      <span aria-hidden="true">–</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

function Value({ value }: { value: unknown }): ReactElement {
  if (value === null || value === undefined || value === "") {
    return <Empty />;
  }
  return (
    <span className="break-words">
      {typeof value === "object" ? JSON.stringify(value) : String(value)}
    </span>
  );
}

function Diff({ change }: { change: PendingChange }): ReactElement {
  const entries = Object.entries(change.changes);
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {change.action === "delete" ? "Deletes the row." : "No field values."}
      </p>
    );
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
      {entries.map(([name, [before, after]]) => (
        <div key={name} className="contents">
          <dt className="font-mono text-xs text-muted-foreground">{name}</dt>
          <dd className="flex flex-wrap items-center gap-2">
            <Value value={before} />
            <span aria-hidden="true" className="text-muted-foreground">
              →
            </span>
            <Value value={after} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Item(props: {
  change: PendingChange;
  renderItem?: (change: PendingChange) => ReactNode;
  onDecided?: (change: PendingChange) => void;
}): ReactElement {
  const { change, renderItem, onDecided } = props;
  const decide = useDecidePendingChange();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = decide.isPending;

  const run = (verdict: "approve" | "reject"): void => {
    setError(null);
    decide.mutate(
      { id: change.id, verdict, reason },
      {
        onSuccess: (decided) => onDecided?.(decided),
        onError: (failure) => setError(errorText(failure)),
      },
    );
  };

  return (
    <li
      className="space-y-3 rounded-md border border-border bg-card p-4"
      data-action={change.action}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="space-y-0.5">
          <p className="font-medium">{change.summary || change.model}</p>
          <p className="text-xs text-muted-foreground">
            {change.action} · {change.model} · by{" "}
            {change.maker?.email ?? <Empty label="no user recorded" />} · {change.approvals}/
            {change.required} approvals
          </p>
        </div>
        <time dateTime={change.created_at} className="text-xs text-muted-foreground">
          {new Date(change.created_at).toLocaleString()}
        </time>
      </div>
      {renderItem !== undefined ? renderItem(change) : <Diff change={change} />}
      {change.decisions.length > 0 && (
        <ul className="space-y-1 text-xs text-muted-foreground">
          {change.decisions.map((decision) => (
            <li key={decision.id}>
              {decision.verdict === "approve" ? "Approved" : "Rejected"} by{" "}
              {decision.checker?.email ?? <Empty label="no user recorded" />}
              {decision.reason !== "" ? `: ${decision.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Reason (optional)"
          aria-label={`Reason for ${change.summary}`}
          className="h-9 min-w-48 flex-1 rounded-md border border-input bg-background px-3 text-sm"
        />
        <Button size="sm" disabled={busy} onClick={() => run("approve")}>
          Approve
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => run("reject")}>
          Reject
        </Button>
      </div>
      {error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </li>
  );
}

export function ApprovalsQueue({
  params,
  empty = "Nothing waiting for your approval.",
  renderItem,
  onDecided,
  className,
}: ApprovalsQueueProps): ReactElement {
  const query = usePendingChanges(params);
  if (query.isPending) {
    return (
      <div className="space-y-2" data-testid="approvals-queue-loading">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (query.error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorText(query.error)}
      </p>
    );
  }
  const results = query.data?.results ?? [];
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ol className={cn("space-y-3", className)} aria-label="Pending changes">
      {results.map((change) => (
        <Item key={change.id} change={change} renderItem={renderItem} onDecided={onDecided} />
      ))}
    </ol>
  );
}
