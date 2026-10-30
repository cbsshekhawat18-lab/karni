import * as React from "react";
import { useResourceAncestors } from "../../../hooks/useResourceTree";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { AlertIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import { displayLabel } from "../displayLabel";
import { resourceNames, type ResourceLabel } from "../resource-names";

registerComponentRole("tree-breadcrumb", "TreeBreadcrumb");

export interface TreeBreadcrumbProps {
  /** The tree resource: "regions". */
  resource: string;
  /** The node whose path is shown. */
  id: string | number;
  /** The node itself, whose label ends the path. Without it the path ends at the parent. */
  item?: Record<string, unknown>;
  /** The link of an ancestor (its detail page). Without it, and without `onNavigate`, ancestors are text. */
  href?: (node: Record<string, unknown>) => string | undefined;
  /** Called when an ancestor is chosen (client-side navigation). */
  onNavigate?: (node: Record<string, unknown>) => void;
  /** Defaults to displayLabel(). */
  getNodeLabel?: (node: Record<string, unknown>) => React.ReactNode;
  /** How the resource is named. Default: derived from `resource`. */
  resourceLabel?: ResourceLabel;
  className?: string;
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Experimental. The path from the root to one node of a tree resource, as a
 * breadcrumb (`GET /<resource>/<id>/ancestors/`).
 *
 * A `<nav>` with an ordered list: each ancestor (a link with `href`, a
 * button with only `onNavigate`, else text), then the node itself marked
 * `aria-current="page"`. A root has no path, so nothing renders. While the
 * path loads a placeholder keeps its line, and a failed load says so with a
 * way to try again. ResourceDetail shows it above a tree resource's record.
 */
export function TreeBreadcrumb(props: TreeBreadcrumbProps): React.ReactElement | null {
  const { resource, id, item, href, onNavigate, getNodeLabel, resourceLabel, className } = props;
  const names = resourceNames(resource, resourceLabel);
  const ancestors = useResourceAncestors(resource, id, { retry: false });
  const labelOf = (node: Record<string, unknown>): React.ReactNode =>
    getNodeLabel !== undefined ? getNodeLabel(node) : displayLabel(node);

  if (ancestors.isPending) {
    return (
      <div className={cn("flex h-5 items-center", className)} aria-hidden="true">
        <Skeleton className="h-3.5 w-48" />
      </div>
    );
  }
  if (ancestors.isError) {
    return (
      <p className={cn("flex items-center gap-2 text-sm text-muted-foreground", className)}>
        <AlertIcon className="h-3.5 w-3.5 shrink-0 text-destructive" />
        <span>Couldn't load where this {names.singular} sits in the tree.</span>
        <button
          type="button"
          className="font-medium text-foreground underline underline-offset-4"
          onClick={() => void ancestors.refetch()}
        >
          Try again
        </button>
      </p>
    );
  }
  const path = ancestors.data;
  if (path.length === 0) return null;

  const crumb = (node: Record<string, unknown>): React.ReactNode => {
    const link = href?.(node);
    const label = labelOf(node);
    const className =
      "rounded-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
    if (link !== undefined) {
      return (
        <a
          href={link}
          className={className}
          onClick={(event) => {
            if (onNavigate === undefined) return;
            event.preventDefault();
            onNavigate(node);
          }}
        >
          {label}
        </a>
      );
    }
    if (onNavigate !== undefined) {
      return (
        <button type="button" className={className} onClick={() => onNavigate(node)}>
          {label}
        </button>
      );
    }
    return <span className="text-muted-foreground">{label}</span>;
  };

  return (
    <nav aria-label={`${capitalised(names.singular)} path`} className={className}>
      <ol className="flex flex-wrap items-center gap-1.5 text-sm">
        {path.map((node, index) => (
          <li key={String(node["id"] ?? index)} className="flex items-center gap-1.5">
            {crumb(node)}
            <span aria-hidden="true" className="text-muted-foreground">
              /
            </span>
          </li>
        ))}
        {item !== undefined ? (
          <li className="flex items-center">
            <span aria-current="page" className="font-medium text-foreground">
              {labelOf(item)}
            </span>
          </li>
        ) : null}
      </ol>
    </nav>
  );
}
