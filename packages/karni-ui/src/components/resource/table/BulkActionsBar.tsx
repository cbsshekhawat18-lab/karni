/**
 * Selected-count toolbar for ResourceTable's bulk select (D5): how many rows
 * are selected (selection persists across pages) and what "all" covers, a
 * clear affordance, one button per bulk action, and what happened last time
 * (a failure in plain words, or which rows failed). The table runs the
 * actions (confirming destructive ones first). This bar only presents them.
 * The default of ResourceTable's `BulkActions` slot.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { ErrorState } from "../../../states/ErrorState";
import { PendingButton } from "../../../states/PendingButton";
import { Button } from "../../primitives/button";
import { AlertIcon } from "../../primitives/icons";

/** What a bulk action may report back: the rows it could not handle, and why. */
export interface BulkResult {
  /** Each failed row's id (String(row.id)) and the reason to show on that row. */
  failed?: ReadonlyArray<{ id: string; reason: string }>;
}

/**
 * What `BulkAction.onClick` returns: nothing (the 0.3 contract, kept), or a
 * promise of nothing or a `BulkResult`.
 */
// eslint-disable-next-line @typescript-eslint/no-invalid-void-type -- a callback may return nothing or a promise; void is the precise contract
export type BulkActionReturn = void | Promise<void | BulkResult>;

export interface BulkAction {
  label: React.ReactNode;
  /**
   * Runs the action on the selected ids. Return a promise to have the table
   * show progress, report failures and deselect the rows that succeeded.
   * Resolve a `BulkResult` to mark the rows that failed. A plain `void`
   * return leaves the selection as it is.
   */
  onClick: (selectedIds: string[]) => BulkActionReturn;
  destructive?: boolean;
  /**
   * Ask before running. Default: true for destructive actions. An object
   * words the question ("Archive 3 events?" by default).
   */
  confirm?:
    boolean | { title?: React.ReactNode; description?: React.ReactNode; confirmLabel?: string };
  /** Announced while the action runs ("Archiving…"). */
  pendingLabel?: string;
}

/** What the last bulk action came to, for the bar to report. */
export type BulkOutcome =
  | { kind: "failed"; actionLabel: string; error: unknown; count: number }
  | { kind: "partial"; actionLabel: string; failed: number; total: number };

export interface BulkActionsBarProps {
  /** Row ids (String(row.id), D5) currently selected, across all pages. */
  selectedIds: readonly string[];
  bulkActions: ReadonlyArray<BulkAction>;
  onClear: () => void;
  /** Runs (or asks to confirm) the action at `index`. `trigger` gets focus back after a dialog. */
  onAction?: (index: number, trigger: HTMLButtonElement | null) => void;
  /** The action running now, by index. */
  runningIndex?: number | null;
  /** The last action's failure or partial failure, reported until the next one. */
  outcome?: BulkOutcome | null;
  /** Rows on the current page, and whether all of them are selected. */
  pageRowCount?: number;
  allPageRowsSelected?: boolean;
  /** Everything matching the current search and filters (DRF `count`). */
  totalCount?: number;
  /** The resource, plural ("events"). */
  resourceLabel?: string;
  className?: string;
}

export function BulkActionsBar(props: BulkActionsBarProps): React.ReactElement {
  const {
    selectedIds,
    bulkActions,
    onClear,
    onAction,
    runningIndex = null,
    outcome = null,
    pageRowCount,
    allPageRowsSelected = false,
    totalCount,
    resourceLabel = "rows",
    className,
  } = props;
  const buttons = React.useRef<Array<HTMLButtonElement | null>>([]);
  const count = selectedIds.length;
  const others =
    allPageRowsSelected && totalCount !== undefined && pageRowCount !== undefined
      ? totalCount - count
      : 0;

  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className={cn(
        "flex flex-col gap-2 rounded-md border border-border bg-muted px-3 py-2",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium text-foreground">{count} selected</p>
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {bulkActions.map((action, index) => (
            <PendingButton
              key={index}
              ref={(element) => {
                buttons.current[index] = element;
              }}
              variant={action.destructive === true ? "destructive" : "outline"}
              size="sm"
              pending={runningIndex === index}
              pendingLabel={action.pendingLabel ?? "Working…"}
              disabled={runningIndex !== null && runningIndex !== index}
              onClick={() => {
                if (onAction !== undefined) onAction(index, buttons.current[index] ?? null);
                else void action.onClick([...selectedIds]);
              }}
            >
              {action.label}
            </PendingButton>
          ))}
        </div>
      </div>
      {others > 0 && (
        <p className="text-xs text-muted-foreground">
          All {count} {resourceLabel} on this page are selected. The other {others.toLocaleString()}{" "}
          matching {resourceLabel} are not.
        </p>
      )}
      {outcome?.kind === "partial" && (
        <p role="alert" className="flex items-center gap-2 text-sm text-foreground">
          <AlertIcon className="h-4 w-4 shrink-0 text-destructive" />
          {outcome.actionLabel} failed for {outcome.failed} of {outcome.total} {resourceLabel}. The
          rows that failed say why and stay selected. The others are done.
        </p>
      )}
      {outcome?.kind === "failed" && (
        <ErrorState
          variant="inline"
          error={outcome.error}
          context={{
            action: outcome.actionLabel.toLowerCase(),
            resource: `${outcome.count} ${resourceLabel}`,
          }}
        />
      )}
    </div>
  );
}
