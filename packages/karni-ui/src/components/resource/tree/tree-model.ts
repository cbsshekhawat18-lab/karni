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

/**
 * A copy of the loaded tree cut down to the nodes `isMatch` accepts and the
 * nodes above them, so a search result keeps its ancestors. `matched` holds
 * the keys that matched themselves.
 */
export function pruneToMatches(
  tops: readonly Node[],
  kidsOf: (node: Node) => readonly Node[] | null,
  isMatch: (node: Node) => boolean,
): { tops: Node[]; matched: Set<string> } {
  const matched = new Set<string>();
  const seen = new Set<string>();
  const cut = (node: Node): Node | null => {
    const key = keyOf(node);
    if (seen.has(key)) return null;
    seen.add(key);
    const kept = (kidsOf(node) ?? []).map(cut).filter((kid): kid is Node => kid !== null);
    const self = isMatch(node);
    if (self) matched.add(key);
    if (!self && kept.length === 0) return null;
    return { ...node, has_children: kept.length > 0, children: kept };
  };
  return { tops: tops.map(cut).filter((node): node is Node => node !== null), matched };
}

/**
 * A forest of search results from each match and the nodes above it (root
 * first, as `ancestors/` answers). Shared ancestors appear once. A match
 * whose path is not known yet stands at the top.
 */
export function forestFromPaths(found: ReadonlyArray<{ match: Node; above: readonly Node[] }>): {
  tops: Node[];
  matched: Set<string>;
} {
  const byKey = new Map<string, Node>();
  const tops: Node[] = [];
  const matched = new Set<string>();
  const place = (node: Node, parent: Node | null): Node => {
    const key = keyOf(node);
    const existing = byKey.get(key);
    if (existing !== undefined) return existing;
    const fresh: Node = { ...node, has_children: false, children: [] };
    byKey.set(key, fresh);
    if (parent === null) {
      tops.push(fresh);
    } else {
      (parent.children as Node[]).push(fresh);
      parent.has_children = true;
    }
    return fresh;
  };
  for (const { match, above } of found) {
    let parent: Node | null = null;
    for (const node of above) parent = place(node, parent);
    place(match, parent);
    matched.add(keyOf(match));
  }
  return { tops, matched };
}
