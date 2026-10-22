/**
 * One row as a card, for containers narrower than ResourceTable's
 * `cardBreakpoint`: the title (the first column, or `getRowLabel`), then a
 * label: value pair per visible column, with the row's checkbox and actions.
 * The default of ResourceTable's `RowCard` slot.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { AlertIcon } from "../../primitives/icons";
import { DENSITY_CLASSES } from "./layout";
import type { ResourceTableDensity } from "./preferences";

/** Fields a card shows before "Show N more details" (hide columns in the View menu to choose them). */
const CARD_FIELDS = 8;

export interface ResourceTableCardField {
  id: string;
  label: React.ReactNode;
  value: React.ReactNode;
}

export interface ResourceTableRowCardProps<T = Record<string, unknown>> {
  row: T;
  /** The card's heading: the first column's cell, or `getRowLabel(row)`. */
  title: React.ReactNode;
  /** The other visible columns, as label: value pairs. */
  fields: readonly ResourceTableCardField[];
  /** The row's checkbox, when the table has bulk actions. */
  selection?: React.ReactNode;
  /** The row's actions (edit, delete, `rowActions`). */
  actions?: React.ReactNode;
  /** Opens the row (`onRowClick`); the title becomes a button. */
  onOpen?: () => void;
  selected: boolean;
  /** Why the last bulk action failed for this row. */
  failure?: string;
  density: ResourceTableDensity;
}

export function RowCard<T>(props: ResourceTableRowCardProps<T>): React.ReactElement {
  const { title, fields, selection, actions, onOpen, selected, failure, density } = props;
  const [expanded, setExpanded] = React.useState(false);
  const listId = React.useId();
  // A card is a summary: past CARD_FIELDS fields the rest sit behind a toggle.
  const shown = expanded ? fields : fields.slice(0, CARD_FIELDS);
  const hiddenCount = fields.length - CARD_FIELDS;
  return (
    <li
      data-state={selected ? "selected" : undefined}
      className={cn(
        "flex flex-col rounded-lg border border-border bg-card text-card-foreground data-[state=selected]:border-primary",
        DENSITY_CLASSES[density].card,
      )}
    >
      <div className="flex items-start gap-3">
        {selection !== undefined && <div className="flex h-6 items-center">{selection}</div>}
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold leading-none">
            {onOpen !== undefined ? (
              <button
                type="button"
                onClick={onOpen}
                className="max-w-full truncate rounded-sm text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {title}
              </button>
            ) : (
              <span className="block truncate">{title}</span>
            )}
          </h3>
          {failure !== undefined && (
            <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
              <AlertIcon className="h-3.5 w-3.5 shrink-0" />
              {failure}
            </p>
          )}
        </div>
      </div>
      {fields.length > 0 && (
        <dl id={listId} className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          {shown.map((field) => (
            <React.Fragment key={field.id}>
              <dt className="truncate text-muted-foreground">{field.label}</dt>
              <dd className="min-w-0 break-words text-foreground">{field.value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {hiddenCount > 0 && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => setExpanded((open) => !open)}
          className="self-start rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? "Show fewer details" : `Show ${hiddenCount} more details`}
        </button>
      )}
      {actions !== undefined && (
        // Hidden when the role may do nothing to this row (the actions render empty).
        <div className="hidden flex-wrap items-center justify-end gap-1 border-t border-border pt-2 has-[a]:flex has-[button]:flex">
          {actions}
        </div>
      )}
    </li>
  );
}
