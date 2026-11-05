/**
 * The pure part of TreeView: which nodes are visible, at which level and
 * position, and the keyboard moves of the WAI-ARIA tree pattern over them.
 *
 * Internal to @karni/ui.
 */
import type { TreeNode } from "../../../hooks/useResourceTree";

export type Node = TreeNode<Record<string, unknown>>;

/** One visible row of the tree, in display order. */
export interface VisibleRow {
  key: string;
  node: Node;
  /** 1 for the top level (aria-level). */
  level: number;
  /** Position among its siblings, from 1 (aria-posinset). */
  posinset: number;
  /** How many siblings it has, itself included (aria-setsize). */
  setsize: number;
  parentKey: string | null;
  /** Whether it has children (loaded or not). */
  expandable: boolean;
  expanded: boolean;
}

/** The node's key: its id as a string, so 5 and "5" are one node. */
export function keyOf(node: Record<string, unknown>): string {
  const id = node["id"];
  return typeof id === "string" || typeof id === "number" ? String(id) : "";
}

/**
 * The visible rows: every top node, and the children of every expanded node
 * whose children are known (`kidsOf` returns `null` while they are not).
 * A node seen twice (bad data) is shown once, so the list never loops.
 */
export function visibleRows(
  tops: readonly Node[],
  expanded: ReadonlySet<string>,
  kidsOf: (node: Node) => readonly Node[] | null,
): VisibleRow[] {
  const rows: VisibleRow[] = [];
  const seen = new Set<string>();
  const walk = (nodes: readonly Node[], level: number, parentKey: string | null): void => {
    nodes.forEach((node, index) => {
      const key = keyOf(node);
      if (seen.has(key)) return;
      seen.add(key);
      const kids = kidsOf(node);
      const expandable = node.has_children || (kids !== null && kids.length > 0);
      const open = expandable && expanded.has(key);
      rows.push({
        key,
        node,
        level,
        posinset: index + 1,
        setsize: nodes.length,
        parentKey,
        expandable,
        expanded: open,
      });
      if (open && kids !== null) walk(kids, level + 1, key);
    });
  };
  walk(tops, 1, null);
  return rows;
}

/** Every node reachable from `tops` through known children, depth first. */
export function knownNodes(
  tops: readonly Node[],
  kidsOf: (node: Node) => readonly Node[] | null,
): Node[] {
  const out: Node[] = [];
  const seen = new Set<string>();
  const stack = [...tops].reverse();
  while (stack.length > 0) {
    const node = stack.pop() as Node;
    const key = keyOf(node);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(node);
    const kids = kidsOf(node);
    if (kids !== null) stack.push(...[...kids].reverse());
  }
  return out;
}

/** The keys of the siblings of `row` (itself included) that have children: what `*` expands. */
export function expandableSiblings(rows: readonly VisibleRow[], row: VisibleRow): string[] {
  return rows
    .filter((other) => other.parentKey === row.parentKey && other.level === row.level)
    .filter((other) => other.expandable)
    .map((other) => other.key);
}

/**
 * Type-ahead: the index of the next row after `from` (wrapping) whose label
 * starts with `prefix`, ignoring case. -1 when none does.
 */
export function matchPrefix(
  rows: readonly VisibleRow[],
  from: number,
  prefix: string,
  labelOf: (node: Node) => string,
): number {
  if (rows.length === 0 || prefix === "") return -1;
  const needle = prefix.toLocaleLowerCase();
  for (let step = 1; step <= rows.length; step += 1) {
    const index = (from + step) % rows.length;
    const row = rows[index];
    if (row !== undefined && labelOf(row.node).toLocaleLowerCase().startsWith(needle)) return index;
  }
  return -1;
}
