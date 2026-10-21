/**
 * ResourceTable's narrow layout: each row a card (the RowCard slot), with a
 * "select all on this page" checkbox and a sort choice above them, since the
 * column headers are gone. Internal to @karni/ui.
 */
import { flexRender, type Row, type Table } from "@tanstack/react-table";
import * as React from "react";
import { cn } from "../../../lib/cn";
import { Checkbox } from "../../primitives/checkbox";
import { Select } from "../../primitives/select";
import type { ResourceTableDensity } from "./preferences";
import type { ResourceTableRowCardProps } from "./RowCard";
import { ACTIONS_COLUMN, SELECT_COLUMN } from "./structural-columns";

export interface CardListProps<T> {
  table: Table<T>;
  caption: string;
  resourceLabel: string;
  density: ResourceTableDensity;
  Card: React.ComponentType<ResourceTableRowCardProps<unknown>>;
  rowLabel: (row: T) => string;
  /** Overrides the first column as each card's title. */
  useRowLabelAsTitle: boolean;
  onRowClick?: (row: T) => void;
  failures: Readonly<Record<string, string>>;
  /** Plain-text column names, for the sort choice. */
  columnLabel: (columnId: string) => string;
  /** The current ordering and a way to change it ("" is the default order). */
  ordering: string;
  onOrderingChange: (ordering: string) => void;
  busy: boolean;
  dimmed: boolean;
}

function cellOf<T>(row: Row<T>, columnId: string): React.ReactNode {
  const cell = row.getVisibleCells().find((candidate) => candidate.column.id === columnId);
  return cell === undefined ? null : flexRender(cell.column.columnDef.cell, cell.getContext());
}

export function CardList<T>(props: CardListProps<T>): React.ReactElement {
  const {
    table,
    caption,
    resourceLabel,
    density,
    Card,
    rowLabel,
    useRowLabelAsTitle,
    onRowClick,
    failures,
    columnLabel,
    ordering,
    onOrderingChange,
    busy,
    dimmed,
  } = props;
  const columns = table.getVisibleLeafColumns();
  const selectable = columns.some((column) => column.id === SELECT_COLUMN);
  const hasActions = columns.some((column) => column.id === ACTIONS_COLUMN);
  const dataColumns = columns.filter(
    (column) => column.id !== SELECT_COLUMN && column.id !== ACTIONS_COLUMN,
  );
  const [titleColumn, ...rest] = dataColumns;
  const sortable = dataColumns.filter((column) => column.getCanSort());
  const sortOptions = sortable.flatMap((column) => [
    { value: column.id, label: `${columnLabel(column.id)}, ascending` },
    { value: `-${column.id}`, label: `${columnLabel(column.id)}, descending` },
  ]);
  const sortValue = sortOptions.some((option) => option.value === ordering) ? ordering : null;
  const labels = new Map<string, React.ReactNode>(
    table
      .getFlatHeaders()
      .map((header) => [
        header.column.id,
        flexRender(header.column.columnDef.header, header.getContext()),
      ]),
  );

  return (
    <div className="flex flex-col gap-3">
      {(selectable || sortOptions.length > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {selectable ? (
            <label className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={
                  table.getIsAllPageRowsSelected()
                    ? true
                    : table.getIsSomePageRowsSelected()
                      ? "indeterminate"
                      : false
                }
                onCheckedChange={(checked) => table.toggleAllPageRowsSelected(checked === true)}
              />
              Select all {resourceLabel} on this page
            </label>
          ) : (
            <span />
          )}
          {sortOptions.length > 0 && (
            <Select
              aria-label="Sort by"
              className="h-9 w-auto min-w-40"
              value={sortValue}
              placeholder="Sort by"
              clearable
              clearLabel="Sort: default order"
              disabled={busy}
              options={sortOptions}
              onValueChange={(next) => onOrderingChange(next ?? "")}
            />
          )}
        </div>
      )}
      <ul aria-label={caption} className={cn("flex flex-col gap-3", dimmed && "opacity-60")}>
        {table.getRowModel().rows.map((row) => {
          const title =
            useRowLabelAsTitle || titleColumn === undefined
              ? rowLabel(row.original)
              : cellOf(row, titleColumn.id);
          return (
            <Card
              key={row.id}
              row={row.original}
              title={title}
              fields={rest.map((column) => ({
                id: column.id,
                label: labels.get(column.id) ?? columnLabel(column.id),
                value: cellOf(row, column.id),
              }))}
              selection={
                selectable ? (
                  <Checkbox
                    aria-label={`Select ${rowLabel(row.original)}`}
                    checked={row.getIsSelected()}
                    onCheckedChange={(checked) => row.toggleSelected(checked === true)}
                  />
                ) : undefined
              }
              actions={hasActions ? cellOf(row, ACTIONS_COLUMN) : undefined}
              onOpen={onRowClick !== undefined ? () => onRowClick(row.original) : undefined}
              selected={row.getIsSelected()}
              failure={failures[row.id]}
              density={density}
            />
          );
        })}
      </ul>
    </div>
  );
}
