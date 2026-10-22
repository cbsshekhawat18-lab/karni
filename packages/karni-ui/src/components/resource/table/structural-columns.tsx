/**
 * ResourceTable's structural columns: the selection checkboxes (bulk select)
 * and the row actions (edit, `rowActions`, delete). Their ids start with
 * "__", so they are never sortable, never in the column menu and never URL
 * state. Internal to @karni/ui.
 */
import type { ColumnDef } from "@tanstack/react-table";
import * as React from "react";
import { cn } from "../../../lib/cn";
import { Button } from "../../primitives/button";
import { Checkbox } from "../../primitives/checkbox";

export const SELECT_COLUMN = "__select__";
export const ACTIONS_COLUMN = "__actions__";

export function isStructural(columnId: string): boolean {
  return columnId === SELECT_COLUMN || columnId === ACTIONS_COLUMN;
}

export function selectionColumn<T>(options: {
  rowLabel: (row: T) => string;
  resourceLabel: string;
}): ColumnDef<T> {
  const { rowLabel, resourceLabel } = options;
  return {
    id: SELECT_COLUMN,
    enableSorting: false,
    enableHiding: false,
    header: ({ table }) => (
      <Checkbox
        aria-label={`Select all ${resourceLabel} on this page`}
        checked={
          table.getIsAllPageRowsSelected()
            ? true
            : table.getIsSomePageRowsSelected()
              ? "indeterminate"
              : false
        }
        onCheckedChange={(checked) => table.toggleAllPageRowsSelected(checked === true)}
      />
    ),
    cell: ({ row }) => (
      <div className="flex items-center" onClick={(event) => event.stopPropagation()}>
        <Checkbox
          aria-label={`Select ${rowLabel(row.original)}`}
          checked={row.getIsSelected()}
          onCheckedChange={(checked) => row.toggleSelected(checked === true)}
        />
      </div>
    ),
  };
}

export interface RowActionsOptions<T> {
  rowActions?: (row: T) => React.ReactNode;
  onEdit?: (row: T) => void;
  /** Whether this row's edit action is offered (the role may change it). */
  canEdit: (row: T) => boolean;
  /** Present when deletes are enabled; asks to confirm, then deletes. */
  onDelete?: (row: T, trigger: HTMLButtonElement) => void;
  canDelete: (row: T) => boolean;
  /** Button geometry for the current density. */
  buttonClassName: string;
}

/** The actions of one row, in the order a row reads: edit, custom, delete. */
export function RowActions<T>(props: RowActionsOptions<T> & { row: T }): React.ReactElement {
  const { row, rowActions, onEdit, canEdit, onDelete, canDelete, buttonClassName } = props;
  return (
    <>
      {onEdit !== undefined && canEdit(row) && (
        <Button variant="ghost" size="sm" className={buttonClassName} onClick={() => onEdit(row)}>
          Edit
        </Button>
      )}
      {rowActions?.(row)}
      {onDelete !== undefined && canDelete(row) && (
        <Button
          variant="ghost"
          size="sm"
          className={cn("text-destructive hover:text-destructive", buttonClassName)}
          onClick={(event) => onDelete(row, event.currentTarget)}
        >
          Delete
        </Button>
      )}
    </>
  );
}

export function actionsColumn<T>(options: RowActionsOptions<T>): ColumnDef<T> {
  return {
    id: ACTIONS_COLUMN,
    enableSorting: false,
    enableHiding: false,
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div
        className="flex items-center justify-end gap-1"
        onClick={(event) => event.stopPropagation()}
      >
        <RowActions {...options} row={row.original} />
      </div>
    ),
  };
}
