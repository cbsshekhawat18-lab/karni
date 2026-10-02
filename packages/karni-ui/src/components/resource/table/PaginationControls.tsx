/**
 * ResourceTable's server-mode pagination row (DRF PageNumberPagination:
 * `{count, next, previous, results}` with `page` / `page_size` params).
 * Internal to @karni/ui — the public surface is ResourceTable's props.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { Button } from "../../primitives/button";

export interface PaginationControlsProps {
  /** 1-based current page. */
  page: number;
  pageCount: number;
  /** Total item count across all pages (DRF `count`). */
  totalCount: number;
  /** From DRF `previous` / `next` — the server is the authority. */
  hasPrevious: boolean;
  hasNext: boolean;
  onPageChange: (page: number) => void;
  className?: string;
}

export function PaginationControls(props: PaginationControlsProps): React.ReactElement {
  const { page, pageCount, totalCount, hasPrevious, hasNext, onPageChange, className } = props;
  return (
    <nav
      aria-label="Pagination"
      className={cn("flex flex-wrap items-center justify-between gap-3", className)}
    >
      <p className="text-sm text-muted-foreground">
        Page {page} of {pageCount} · {totalCount} {totalCount === 1 ? "item" : "items"}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!hasPrevious}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasNext}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
