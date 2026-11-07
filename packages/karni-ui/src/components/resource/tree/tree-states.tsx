/**
 * TreeView's replaceable parts (`slots`) and their defaults, exported as
 * `defaultTreeViewSlots` so a project can wrap them.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { CheckIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import type { ResourceNames } from "../resource-names";

/** Experimental. What the `Node` slot receives: the content of one tree item. */
export interface TreeViewNodeProps {
  /** The row behind the node (its fields, `has_children` and `children`). */
  node: Record<string, unknown>;
  /** Its label (`getNodeLabel`, else displayLabel). */
  label: React.ReactNode;
  /** 1 for the top level. */
  level: number;
  /** Whether the node is selected (always false when the tree does not select). */
  selected: boolean;
  /** Whether its branch is open. */
  expanded: boolean;
}

/** Experimental. What the `Empty` slot receives. */
export interface TreeViewEmptyProps {
  /** "none": the tree has no nodes. "no-match": the search found nothing. */
  reason: "none" | "no-match";
  search: string;
  names: ResourceNames;
}

/** Experimental. What the `Loading` slot receives. */
export interface TreeViewLoadingProps {
  rows: number;
}

/** Experimental. The replaceable parts of TreeView (`slots`). */
export interface TreeViewSlots {
  /** One node's content (the row around it carries the treeitem semantics and the toggle). */
  Node: React.ComponentType<TreeViewNodeProps>;
  /** While the first level loads. */
  Loading: React.ComponentType<TreeViewLoadingProps>;
  /** No nodes to show, and why. */
  Empty: React.ComponentType<TreeViewEmptyProps>;
  /** The tree could not be loaded (forbidden, offline, server), with retry when it can help. */
  Error: React.ComponentType<ErrorSlotProps>;
}

export function TreeViewNode({ label, selected }: TreeViewNodeProps): React.ReactElement {
  return (
    <>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {selected ? <CheckIcon className="h-4 w-4 shrink-0" /> : null}
    </>
  );
}

const SKELETON_WIDTHS = ["w-1/2", "w-2/3", "w-1/3", "w-3/5", "w-1/2"];

export function TreeViewLoading({ rows }: TreeViewLoadingProps): React.ReactElement {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className={cn("flex h-8 items-center px-2", index % 2 === 1 && "pl-8")}>
          <Skeleton className={cn("h-3.5", SKELETON_WIDTHS[index % SKELETON_WIDTHS.length])} />
        </div>
      ))}
    </div>
  );
}

/** "No regions yet" and "No regions match “ber”" are different situations, said differently. */
export function treeEmptyText({ reason, search, names }: TreeViewEmptyProps): string {
  if (reason === "no-match") return `No ${names.plural} match “${search}”`;
  return `No ${names.plural} yet`;
}

export function TreeViewEmpty(props: TreeViewEmptyProps): React.ReactElement {
  return (
    <p className="px-2 py-6 text-center text-sm text-muted-foreground">{treeEmptyText(props)}</p>
  );
}

export function TreeViewError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState variant="inline" className="px-2 py-3" {...props} />;
}

/** Experimental. TreeView's own slot components, for wrapping rather than rewriting. */
export const defaultTreeViewSlots: TreeViewSlots = {
  Node: TreeViewNode,
  Loading: TreeViewLoading,
  Empty: TreeViewEmpty,
  Error: TreeViewError,
};
