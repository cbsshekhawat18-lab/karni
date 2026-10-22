import * as React from "react";
import { useChangeHistory, type ChangeLogEntry } from "../../../hooks/useChangeHistory";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { useDelayedFlag, useOnlineStatus } from "../../../states/hooks";
import { Skeleton } from "../../primitives/skeleton";
import { EmptyValue } from "../empty-value";
import { singularNoun } from "../nouns";
import { offlineError, useRetryUnlessClientError, useRetryWhenOnline } from "../query-state";

registerComponentRole("change-history", "ChangeHistory");

/** What the `Loading` slot receives. */
export interface ChangeHistoryLoadingProps {
  /** How many entry placeholders to draw. */
  rows: number;
  /** True once loading has taken longer than SLOW_AFTER_MS (500ms): show the placeholder now. */
  slow: boolean;
}

/** What the `Empty` slot receives: the row has no recorded change. */
export interface ChangeHistoryEmptyProps {
  /** The `empty` prop ("No changes recorded." by default). */
  children: React.ReactNode;
}

/** What the `Entry` slot receives: one recorded change. */
export interface ChangeHistoryEntryProps {
  entry: ChangeLogEntry;
}

/**
 * The replaceable parts of ChangeHistory. Pass any subset as `slots`;
 * `defaultChangeHistorySlots` holds Karni's own, to wrap them.
 */
export interface ChangeHistorySlots {
  Loading: React.ComponentType<ChangeHistoryLoadingProps>;
  /** Any failure: offline, server error, 403, a model that keeps no history (404). */
  Error: React.ComponentType<ErrorSlotProps>;
  Empty: React.ComponentType<ChangeHistoryEmptyProps>;
  /** One entry of the list (rendered inside its <li>). */
  Entry: React.ComponentType<ChangeHistoryEntryProps>;
}

export interface ChangeHistoryProps {
  resource: string;
  id: string | number;
  /** Entries to show (the backend paginates; default: the API's page size). */
  pageSize?: number;
  title?: React.ReactNode;
  /** Shown when the row has no recorded changes. */
  empty?: React.ReactNode;
  /** The resource in words, singular, for messages ("the history of this event"). Default: from `resource`. */
  resourceLabel?: string;
  /** Replace parts of the list: Loading, Error, Empty, Entry. */
  slots?: Partial<ChangeHistorySlots>;
  className?: string;
}

const ACTION_LABEL: Record<ChangeLogEntry["action"], string> = {
  create: "Created",
  update: "Updated",
  delete: "Deleted",
  restore: "Restored",
};

function formatWhen(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function Value({ value }: { value: unknown }): React.ReactElement {
  if (value === null || value === undefined || value === "") {
    return <EmptyValue />;
  }
  if (value === "[redacted]") {
    return <span className="italic text-muted-foreground">redacted</span>;
  }
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return <span className="break-words">{text}</span>;
}

function DefaultEntry({ entry }: ChangeHistoryEntryProps): React.ReactElement {
  const fields = Object.entries(entry.diff);
  return (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{ACTION_LABEL[entry.action] ?? entry.action}</span>
        <time dateTime={entry.timestamp} className="text-muted-foreground">
          {formatWhen(entry.timestamp)}
        </time>
        <span className="text-muted-foreground">
          {entry.actor?.email ?? <EmptyValue label="no user recorded" />}
        </span>
      </div>
      {fields.length > 0 ? (
        <dl className="mt-2 grid grid-cols-[max-content_1fr] items-baseline gap-x-3 gap-y-1">
          {fields.map(([name, [before, after]]) => (
            <React.Fragment key={name}>
              <dt className="font-mono text-xs text-muted-foreground">{name}</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <Value value={before} />
                <span aria-hidden="true" className="text-muted-foreground">
                  →
                </span>
                <span className="sr-only">changed to</span>
                <Value value={after} />
              </dd>
            </React.Fragment>
          ))}
        </dl>
      ) : (
        <p className="mt-2 text-muted-foreground">No visible field changed.</p>
      )}
    </>
  );
}

/** Entry cards in the list's own layout, drawn only once loading is slow (the space is held). */
function DefaultLoading({ rows, slow }: ChangeHistoryLoadingProps): React.ReactElement {
  return (
    <div
      className={cn("space-y-2", !slow && "invisible")}
      aria-hidden="true"
      data-testid="change-history-loading"
    >
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="rounded-md border bg-card p-3 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Skeleton className="my-0.5 h-4 w-16" />
            <Skeleton className="my-0.5 h-4 w-36" />
            <Skeleton className="my-0.5 h-4 w-28" />
          </div>
          <div className="mt-2 grid grid-cols-[max-content_1fr] items-center gap-x-3 gap-y-1">
            <Skeleton className="h-3 w-16" />
            <Skeleton className={cn("my-0.5 h-4", index % 2 === 0 ? "w-40" : "w-32")} />
            <Skeleton className="h-3 w-12" />
            <Skeleton className={cn("my-0.5 h-4", index % 2 === 0 ? "w-32" : "w-48")} />
          </div>
        </div>
      ))}
    </div>
  );
}

function DefaultEmpty({ children }: ChangeHistoryEmptyProps): React.ReactElement {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultChangeHistorySlots: ChangeHistorySlots = {
  Loading: DefaultLoading,
  Error: ErrorState,
  Empty: DefaultEmpty,
  Entry: DefaultEntry,
};

/** Placeholder entries while the history loads (a page rarely starts with more on screen). */
const PLACEHOLDER_ENTRIES = 3;

/**
 * The field-level change history of one row: when, by whom, what changed
 * from what to what. Reads `GET /<resource>/<id>/history/` (models that opt
 * in with `class Karni: audit = True`); fields the role may not see are
 * already absent from each diff, redacted ones say so, and an empty value
 * is the shared EmptyValue (a dash, read as "empty").
 *
 * States: entry placeholders while it loads (drawn after 500ms); failures
 * in describeError's words with "Try again" when it can help — a 403 reads
 * "You can't view the history of this <resource>"; offline says so and
 * reloads when the connection returns. Escape hatch: `slots`.
 */
export function ChangeHistory({
  resource,
  id,
  pageSize,
  title = "History",
  empty = "No changes recorded.",
  resourceLabel,
  slots,
  className,
}: ChangeHistoryProps): React.ReactElement {
  const Slots: ChangeHistorySlots = { ...defaultChangeHistorySlots, ...slots };
  const label = resourceLabel ?? singularNoun(resource);
  const retry = useRetryUnlessClientError();
  const online = useOnlineStatus();
  const query = useChangeHistory(resource, id, pageSize !== undefined ? { pageSize } : undefined, {
    retry,
  });
  const error = query.data === undefined ? query.error : null;
  const offline =
    query.data === undefined && error == null && (!online || query.fetchStatus === "paused");
  const loading = query.data === undefined && error == null && !offline;
  const slow = useDelayedFlag(loading);
  const refetch = React.useCallback((): void => {
    void query.refetch();
  }, [query]);
  useRetryWhenOnline(error, refetch);
  const context = { action: "view", resource: `the history of this ${label}` };

  let body: React.ReactNode;
  if (error !== null && error !== undefined) {
    body = (
      <Slots.Error error={error} context={context} onRetry={refetch} retrying={query.isFetching} />
    );
  } else if (offline) {
    body = (
      <Slots.Error error={offlineError()} context={context} onRetry={refetch} retrying={false} />
    );
  } else if (query.data === undefined) {
    body = (
      <>
        <span role="status" className="sr-only">
          {slow ? "Loading the history…" : ""}
        </span>
        <Slots.Loading
          rows={Math.min(pageSize ?? PLACEHOLDER_ENTRIES, PLACEHOLDER_ENTRIES)}
          slow={slow}
        />
      </>
    );
  } else if (query.data.results.length === 0) {
    body = <Slots.Empty>{empty}</Slots.Empty>;
  } else {
    body = (
      <ol className="space-y-2">
        {query.data.results.map((entry) => (
          <li
            key={entry.id}
            className="rounded-md border bg-card p-3 text-sm"
            data-action={entry.action}
          >
            <Slots.Entry entry={entry} />
          </li>
        ))}
      </ol>
    );
  }

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label="Change history"
      aria-busy={loading || undefined}
    >
      {title !== null ? <h3 className="text-base font-semibold">{title}</h3> : null}
      {body}
    </section>
  );
}
