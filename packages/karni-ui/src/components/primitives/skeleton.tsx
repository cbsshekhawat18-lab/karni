import * as React from "react";
import { cn } from "../../lib/cn";
import { overridable } from "../../primitives/registry";

export type SkeletonProps = React.HTMLAttributes<HTMLDivElement>;

const KarniSkeleton = React.forwardRef<HTMLDivElement, SkeletonProps>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />
  ),
);
KarniSkeleton.displayName = "Skeleton";

/** Loading placeholder block; size it with width/height utility classes.
 *
 * A project replaces it with its own through `primitives={{ skeleton: ... }}` on KarniProvider.
 */
export const Skeleton = overridable<SkeletonProps, HTMLDivElement>("skeleton", KarniSkeleton);
