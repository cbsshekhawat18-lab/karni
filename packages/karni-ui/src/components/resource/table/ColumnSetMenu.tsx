/**
 * ResourceTable's column set selector (experimental): a menu button named
 * after the set shown, with one choice per preset of the model's
 * `Karni.column_sets`. The choice is
 * remembered per user and table (see ./preferences). A Radix dropdown with
 * radio items, so it is operable by keyboard (arrows, Enter, Escape).
 * Internal to @karni/ui. ResourceTable's `columnSets={false}` hides it.
 */
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import * as React from "react";
import type { ColumnSetDef } from "../../../schema/types";
import { Button } from "../../primitives/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "../../primitives/dropdown-menu";
import { CheckIcon } from "../../primitives/icons";
import { ColumnsIcon } from "./table-icons";

export interface ColumnSetMenuProps {
  sets: readonly ColumnSetDef[];
  /** The preset shown. */
  value: string;
  onChange: (name: string) => void;
}

export function ColumnSetMenu({ sets, value, onChange }: ColumnSetMenuProps): React.ReactElement {
  const current = sets.find((found) => found.name === value) ?? sets[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={`Column set: ${current?.label ?? ""}`}
          data-karni-column-set={current?.name}
        >
          <ColumnsIcon className="h-4 w-4" />
          {current?.label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 overflow-y-auto">
        <DropdownMenuLabel>Column set</DropdownMenuLabel>
        <DropdownMenuPrimitive.RadioGroup value={current?.name} onValueChange={onChange}>
          {sets.map((found) => (
            <DropdownMenuPrimitive.RadioItem
              key={found.name}
              value={found.name}
              className="relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground"
            >
              <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <DropdownMenuPrimitive.ItemIndicator>
                  <CheckIcon className="h-4 w-4" />
                </DropdownMenuPrimitive.ItemIndicator>
              </span>
              {found.label}
            </DropdownMenuPrimitive.RadioItem>
          ))}
        </DropdownMenuPrimitive.RadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
