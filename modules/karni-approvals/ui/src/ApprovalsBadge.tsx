/**
 * <ApprovalsBadge> — how many pending changes the signed-in user may decide.
 *
 * Reads `GET /pending-changes/count/` (optionally polling) and renders a
 * token-styled count; nothing at zero unless `showZero`. Drop it in a nav
 * next to the link to the queue.
 */
import { cn } from "@karni/ui";
import type { ReactElement } from "react";
import { usePendingCount } from "./hooks";

export interface ApprovalsBadgeProps {
  /** `false` (default) = fetch once; a number = refetch every N milliseconds. */
  poll?: false | number;
  /** Render "0" instead of nothing when there is nothing to decide. */
  showZero?: boolean;
  className?: string;
  /** Accessible label; the count is appended. Default "Pending approvals". */
  label?: string;
}

export function ApprovalsBadge({
  poll,
  showZero = false,
  className,
  label = "Pending approvals",
}: ApprovalsBadgeProps): ReactElement | null {
  const query = usePendingCount(poll !== undefined ? { poll } : undefined);
  const count = query.data?.pending ?? 0;
  if (query.data === undefined || (count === 0 && !showZero)) return null;
  return (
    <span
      role="status"
      aria-label={`${label}: ${count}`}
      data-testid="approvals-badge"
      className={cn(
        "inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold",
        count > 0 ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
        className,
      )}
    >
      {count}
    </span>
  );
}
