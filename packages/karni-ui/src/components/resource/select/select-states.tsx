/**
 * ResourceSelect's replaceable parts (`slots`) and their defaults, exported
 * as `defaultResourceSelectSlots` so a project can wrap them.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { AlertIcon, CheckIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import type { ResourceNames } from "../resource-names";

export interface ResourceSelectOptionProps {
  /** The row behind the option. */
  item: Record<string, unknown>;
  /** Its label (`getOptionLabel`, else displayLabel). */
  label: React.ReactNode;
  selected: boolean;
  /** Highlighted by the keyboard or the pointer. */
  active: boolean;
}

export interface ResourceSelectChipProps {
  /** The selected row's label, or what to say when it could not be loaded. */
  label: React.ReactNode;
  /** "loading" while the row behind a preselected id loads, "failed" when it could not. */
  state: "loaded" | "loading" | "failed";
  /** Removes the value. Absent when the select is disabled. */
  onRemove?: () => void;
  /** The accessible name of the remove button: "Remove Aurora Hall". */
  removeLabel: string;
}

export interface ResourceSelectEmptyProps {
  /**
   * "none": the resource has no rows yet. "no-match": the search found
   * nothing. "no-loaded-match": search is not available and none of the
   * loaded rows match the typed text.
   */
  reason: "none" | "no-match" | "no-loaded-match";
  /** The typed text. */
  search: string;
  /** How the resource is named ("venue" / "venues"). */
  names: ResourceNames;
  /** How many rows are loaded (for "no-loaded-match"). */
  loaded: number;
}

export interface ResourceSelectLoadingProps {
  /** How many placeholder rows to show. */
  rows: number;
}

/** The replaceable parts of ResourceSelect (`slots`). */
export interface ResourceSelectSlots {
  /** One option's content (the row around it carries the listbox semantics). */
  Option: React.ComponentType<ResourceSelectOptionProps>;
  /** One selected value in `multiple` mode. */
  Chip: React.ComponentType<ResourceSelectChipProps>;
  /** While the first page of options loads. */
  Loading: React.ComponentType<ResourceSelectLoadingProps>;
  /** No options to show, and why. */
  Empty: React.ComponentType<ResourceSelectEmptyProps>;
  /** The options could not be loaded (forbidden, offline, server), with retry when it can help. */
  Error: React.ComponentType<ErrorSlotProps>;
}

export function ResourceSelectOption({
  label,
  selected,
}: ResourceSelectOptionProps): React.ReactElement {
  return (
    <>
      <span className="truncate">{label}</span>
      {selected ? <CheckIcon className="h-4 w-4 shrink-0" /> : null}
    </>
  );
}

function XIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export { XIcon as ResourceSelectClearIcon };

export function ResourceSelectChip({
  label,
  state,
  onRemove,
  removeLabel,
}: ResourceSelectChipProps): React.ReactElement {
  if (state === "loading") {
    return <Skeleton className="h-5 w-20 rounded-sm" />;
  }
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs",
        state === "failed"
          ? "border border-destructive-border bg-destructive-subtle text-foreground"
          : "bg-secondary text-secondary-foreground",
      )}
    >
      {state === "failed" ? <AlertIcon className="h-3 w-3 shrink-0 text-destructive" /> : null}
      <span className="truncate">{label}</span>
      {onRemove !== undefined ? (
        <button
          type="button"
          aria-label={removeLabel}
          className="rounded-sm opacity-70 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          onKeyDown={(event) => {
            if (event.key === "Backspace" || event.key === "Delete") {
              event.preventDefault();
              event.stopPropagation();
              onRemove();
            }
          }}
        >
          <XIcon className="h-3 w-3" />
        </button>
      ) : null}
    </span>
  );
}

const SKELETON_WIDTHS = ["w-3/4", "w-1/2", "w-2/3", "w-3/5", "w-1/2"];

export function ResourceSelectLoading({ rows }: ResourceSelectLoadingProps): React.ReactElement {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex h-8 items-center px-2">
          <Skeleton className={cn("h-3.5", SKELETON_WIDTHS[index % SKELETON_WIDTHS.length])} />
        </div>
      ))}
    </div>
  );
}

/** "No venues yet" and "No venues match “ber”" are different situations, said differently. */
export function emptyText({ reason, search, names, loaded }: ResourceSelectEmptyProps): string {
  if (reason === "no-match") return `No ${names.plural} match “${search}”`;
  if (reason === "no-loaded-match") {
    return `None of the ${loaded.toLocaleString()} loaded ${names.plural} match “${search}”`;
  }
  return `No ${names.plural} yet`;
}

export function ResourceSelectEmpty(props: ResourceSelectEmptyProps): React.ReactElement {
  return <p className="px-2 py-6 text-center text-sm text-muted-foreground">{emptyText(props)}</p>;
}

export function ResourceSelectError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState variant="inline" className="px-2 py-3" {...props} />;
}

/** ResourceSelect's own slot components, for wrapping rather than rewriting. */
export const defaultResourceSelectSlots: ResourceSelectSlots = {
  Option: ResourceSelectOption,
  Chip: ResourceSelectChip,
  Loading: ResourceSelectLoading,
  Empty: ResourceSelectEmpty,
  Error: ResourceSelectError,
};
