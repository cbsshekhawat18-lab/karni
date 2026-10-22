/**
 * ResourceTable's "View" menu: compact rows on or off, and which columns
 * show. Both are remembered per user (see ./preferences). A Radix dropdown,
 * so it is operable by keyboard (arrows, Space to toggle, Escape to close).
 * Internal to @karni/ui. ResourceTable's `viewOptions={false}` hides it.
 */
import * as React from "react";
import { Button } from "../../primitives/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../primitives/dropdown-menu";
import type { ResourceTableDensity } from "./preferences";
import { SlidersIcon } from "./table-icons";

export interface ViewOptionsProps {
  density: ResourceTableDensity;
  onDensityChange: (density: ResourceTableDensity) => void;
  columns: ReadonlyArray<{ id: string; label: string; visible: boolean }>;
  onColumnVisibilityChange: (id: string, visible: boolean) => void;
}

export function ViewOptions(props: ViewOptionsProps): React.ReactElement {
  const { density, onDensityChange, columns, onColumnVisibilityChange } = props;
  const visibleCount = columns.filter((column) => column.visible).length;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label="View options">
          <SlidersIcon className="h-4 w-4" />
          View
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 overflow-y-auto">
        <DropdownMenuCheckboxItem
          checked={density === "compact"}
          onCheckedChange={(checked) => onDensityChange(checked ? "compact" : "comfortable")}
        >
          Compact rows
        </DropdownMenuCheckboxItem>
        {columns.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Columns</DropdownMenuLabel>
            {columns.map((column) => (
              <DropdownMenuCheckboxItem
                key={column.id}
                checked={column.visible}
                // The last visible column stays: a table with no columns says nothing.
                disabled={column.visible && visibleCount === 1}
                onCheckedChange={(checked) => onColumnVisibilityChange(column.id, checked)}
                onSelect={(event) => event.preventDefault()}
              >
                {column.label}
              </DropdownMenuCheckboxItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
