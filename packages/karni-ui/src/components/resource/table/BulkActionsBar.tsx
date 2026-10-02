/**
 * Selected-count toolbar for ResourceTable's bulk select (D5): shows how many
 * rows are selected (selection persists across pages), a clear affordance and
 * one button per configured bulk action.
 * Internal to @karni/ui — the public surface is ResourceTable's props.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { Button } from "../../primitives/button";

export interface BulkAction {
  label: React.ReactNode;
  onClick: (selectedIds: string[]) => void;
  destructive?: boolean;
}

export interface BulkActionsBarProps {
  /** Row ids (String(row.id), D5) currently selected, across all pages. */
  selectedIds: readonly string[];
  bulkActions: ReadonlyArray<BulkAction>;
  onClear: () => void;
  className?: string;
}

export function BulkActionsBar(props: BulkActionsBarProps): React.ReactElement {
  const { selectedIds, bulkActions, onClear, className } = props;
  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2",
        className,
      )}
    >
      <p className="text-sm font-medium text-foreground">{selectedIds.length} selected</p>
      <Button variant="ghost" size="sm" onClick={onClear}>
        Clear
      </Button>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {bulkActions.map((action, index) => (
          <Button
            key={index}
            variant={action.destructive === true ? "destructive" : "outline"}
            size="sm"
            onClick={() => action.onClick([...selectedIds])}
          >
            {action.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
