import * as React from "react";
import { cn } from "../../lib/cn";

/** What a screen reader says for a field that has no value. */
export const EMPTY_VALUE_LABEL = "empty";

export interface EmptyValueProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Read by screen readers in place of the dash. Default "empty". */
  label?: string;
}

/**
 * A field that has no value (null, "", an empty list), the same in every
 * Karni component: ResourceTable's cells, ResourceDetail's rows and
 * ChangeHistory's before/after values. Sighted users see a muted en dash;
 * screen readers hear "empty" instead of "dash" or nothing.
 *
 * A field the role may not read is never rendered as empty: it has no row
 * or cell at all, so an empty value never hints that a hidden one exists.
 */
export const EmptyValue = React.forwardRef<HTMLSpanElement, EmptyValueProps>(
  ({ label = EMPTY_VALUE_LABEL, className, ...props }, ref) => (
    <span ref={ref} className={cn("text-muted-foreground", className)} {...props}>
      <span aria-hidden="true">–</span>
      <span className="sr-only">{label}</span>
    </span>
  ),
);
EmptyValue.displayName = "EmptyValue";
