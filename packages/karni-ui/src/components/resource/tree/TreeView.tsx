import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import * as React from "react";
import { karniKeys } from "../../../hooks/keys";
import { listPath } from "../../../hooks/params";
import { useResourceList } from "../../../hooks/useResourceList";
import {
  treeQuery,
  useResourceAccessForest,
  useResourceAncestors,
  useResourceTree,
  type AccessForestParams,
  type TreeResponse,
} from "../../../hooks/useResourceTree";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { useKarniClient } from "../../../schema/provider";
import { useParsedSchema } from "../../../schema/useSchema";
import { describeError } from "../../../states/describe-error";
import { AlertIcon, ChevronDownIcon, SpinnerIcon } from "../../primitives/icons";
import { Input } from "../../primitives/input";
import { displayLabel } from "../displayLabel";
import { resourceNames, type ResourceLabel } from "../resource-names";
import { useDebouncedValue } from "../select/use-debounced-value";
import {
  expandableSiblings,
  keyOf,
  knownNodes,
  matchPrefix,
  visibleRows,
  type Node,
  type VisibleRow,
} from "./tree-model";
import {
  defaultTreeViewSlots,
  treeEmptyText,
  type TreeViewEmptyProps,
  type TreeViewSlots,
} from "./tree-states";

registerComponentRole("tree-view", "TreeView");

/** Experimental. A tree's selection: one id, several, or none. */
export type TreeValue = string | number | ReadonlyArray<string | number> | null;

/** Experimental. The props of TreeView. */
export interface TreeViewProps {
  /** The tree resource (a Karni `TreeModel` viewset's router prefix): "regions". */
  resource: string;
  /** Start below this node instead of at the roots. */
  root?: string | number | null;
  /** Levels each request loads (1 to 10). Deeper branches load when opened. Default 2. */
  depth?: number;
  /** The selected id (or ids with `multiple`). Without `onChange` the tree does not select. */
  value?: TreeValue;
  /** Called with the new selection and the node that was chosen or unchosen. */
  onChange?: (value: string | number | Array<string | number> | null, node: Node) => void;
  /** Select several nodes (Space or a click toggles one). */
  multiple?: boolean;
  /** Called when a node is activated (Enter, or a click). */
  onActivate?: (node: Node) => void;
  /**
   * Experimental. Show the requester's access forest (`GET /<resource>/access/`)
   * instead of the whole tree: the nodes their `tree:<path>` grants name, and
   * every node below them, can be chosen; their ancestors and the other roots
   * are shown greyed (`aria-disabled`) for navigation. `{ permission }` keeps
   * one permission's grants. Search narrows the loaded nodes.
   */
  access?: boolean | Omit<AccessForestParams, "enabled">;
  /** Ids open at first. */
  defaultExpanded?: ReadonlyArray<string | number>;
  /** Open the path to this node (its ancestors load from `ancestors/`). */
  reveal?: string | number | null;
  /** Move focus into the tree once it has nodes (the selected one, else the first). */
  autoFocus?: boolean;
  /** Defaults to displayLabel(). */
  getNodeLabel?: (node: Node) => React.ReactNode;
  /** Show the search field. Default true. */
  searchable?: boolean;
  /** Debounce for the `?search=` request in ms. Default 300. */
  searchDebounceMs?: number;
  /** How the resource is named in messages. Default: derived from `resource`. */
  resourceLabel?: ResourceLabel;
  /** Replaces parts of the tree: Node, Loading, Empty, Error. */
  slots?: Partial<TreeViewSlots>;
  id?: string;
  className?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}

const LOADING_ROWS = 5;
const TYPEAHEAD_RESET_MS = 500;

function ChevronRightIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
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
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function asLeaf(row: Record<string, unknown>): Node {
  return { ...row, has_children: false, children: [] };
}

/**
 * Experimental. A tree resource as an expandable, keyboard-driven tree.
 *
 * It loads `depth` levels from `GET /<resource>/tree/` and each deeper
 * branch when it is opened (`?root=<id>`), so a tree of any size costs one
 * request per opened branch. The search field asks the list's `?search=`
 * (or, when the API cannot search, narrows the loaded nodes) and shows the
 * matches flat. It implements the WAI-ARIA tree pattern: one tab stop
 * (roving tabindex), Up and Down move, Right opens or enters a branch, Left
 * closes it or goes to the parent, Home and End, Enter activates, Space
 * selects, `*` opens every sibling, and typing jumps to the next node whose
 * label starts with the typed text. Each item carries `aria-level`,
 * `aria-setsize`, `aria-posinset` and `aria-expanded`.
 *
 * With `access`, it shows the requester's access forest instead
 * (`GET /<resource>/access/`): granted nodes and the nodes below them can be
 * chosen, and their ancestors are greyed, shown for navigation only.
 *
 * Escape hatches: `getNodeLabel`, `slots` (Node, Loading, Empty, Error), and
 * the hooks it is built on (`useResourceTree`, `useResourceAncestors`,
 * `useResourceAccessForest`).
 */
export const TreeView = React.forwardRef<HTMLDivElement, TreeViewProps>(
  function TreeView(props, forwardedRef): React.ReactElement {
    const {
      resource,
      root = null,
      depth = 2,
      value = null,
      onChange,
      multiple = false,
      onActivate,
      access = false,
      defaultExpanded,
      reveal = null,
      autoFocus = false,
      getNodeLabel,
      searchable = true,
      searchDebounceMs = 300,
      resourceLabel,
      slots: slotOverrides,
      id,
      className,
    } = props;
    const slots = { ...defaultTreeViewSlots, ...slotOverrides };
    const names = resourceNames(resource, resourceLabel);
    const client = useKarniClient();
    const reactId = React.useId();
    const treeId = id ?? `${reactId}-tree`;
    const itemId = (key: string): string => `${treeId}-item-${key}`;
    const selectable = onChange !== undefined;

    // --- data ---------------------------------------------------------------
    const accessMode = access !== false;
    const permission = typeof access === "object" ? access.permission : undefined;
    const wholeTree = useResourceTree(resource, { root, depth, enabled: !accessMode });
    const forest = useResourceAccessForest(resource, { permission, enabled: accessMode });
    const top: UseQueryResult<TreeResponse> = accessMode ? forest : wholeTree;
    const [expanded, setExpanded] = React.useState<ReadonlySet<string>>(
      () => new Set((defaultExpanded ?? []).map(String)),
    );
    const [lazyRoots, setLazyRoots] = React.useState<readonly string[]>([]);
    const lazyQueries = useQueries({
      queries: lazyRoots.map((key) => ({
        queryKey: karniKeys.tree(resource, { root: key, depth }),
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          client.request<TreeResponse>(`${listPath(resource)}tree/`, {
            query: treeQuery({ root: key, depth }),
            signal,
          }),
        retry: false,
      })),
    });
    const lazy = new Map<string, UseQueryResult<TreeResponse>>();
    lazyRoots.forEach((key, index) => {
      const query = lazyQueries[index];
      if (query !== undefined) lazy.set(key, query);
    });
    const kidsOf = (node: Node): readonly Node[] | null =>
      node.children ?? lazy.get(keyOf(node))?.data?.results ?? null;

    const tops: readonly Node[] = top.data?.results ?? [];
    const treeRows = visibleRows(tops, expanded, kidsOf);

    // In access mode, what a grant reaches: a granted node and every node below it.
    const everything = accessMode && forest.data?.all === true;
    const reachable: ReadonlySet<string> = ((): ReadonlySet<string> => {
      const found = new Set<string>();
      if (!accessMode) return found;
      const visit = (nodes: readonly Node[], inherited: boolean): void => {
        for (const node of nodes) {
          const key = keyOf(node);
          if (found.has(key)) continue;
          const reached = inherited || everything || node["granted"] === true;
          if (reached) found.add(key);
          visit(kidsOf(node) ?? [], reached);
        }
      };
      visit(tops, false);
      return found;
    })();
    const choosable = (key: string): boolean => !accessMode || reachable.has(key);

    // An open branch whose children are not known yet loads them.
    const missingKey = treeRows
      .filter((row) => row.expanded && kidsOf(row.node) === null && !lazy.has(row.key))
      .map((row) => row.key)
      .join("\u0000");
    React.useEffect(() => {
      if (missingKey === "") return;
      const missing = missingKey.split("\u0000");
      setLazyRoots((previous) => {
        const fresh = missing.filter((key) => !previous.includes(key));
        return fresh.length > 0 ? [...previous, ...fresh] : previous;
      });
    }, [missingKey]);

    // Open the path to `reveal`.
    const ancestors = useResourceAncestors(resource, reveal ?? "", {
      enabled: reveal !== null && reveal !== "",
      retry: false,
    });
    React.useEffect(() => {
      const path = ancestors.data;
      if (path === undefined || path.length === 0) return;
      setExpanded((previous) => {
        const next = new Set(previous);
        for (const node of path) next.add(keyOf(node));
        return next.size === previous.size ? previous : next;
      });
    }, [ancestors.data]);

    // --- labels -------------------------------------------------------------
    const labelOf = React.useCallback(
      (node: Node): React.ReactNode =>
        getNodeLabel !== undefined ? getNodeLabel(node) : displayLabel(node),
      [getNodeLabel],
    );
    const labelTextOf = React.useCallback(
      (node: Node): string => {
        const label = labelOf(node);
        if (typeof label === "string") return label;
        if (typeof label === "number") return String(label);
        return displayLabel(node);
      },
      [labelOf],
    );

    // --- search -------------------------------------------------------------
    const parsed = useParsedSchema();
    const listOperation = parsed.data?.resources[resource]?.operations.list;
    const serverSearch =
      !accessMode && (listOperation === undefined || listOperation.hasSearch === true);
    const [term, setTerm] = React.useState("");
    const debounced = useDebouncedValue(term.trim(), searchDebounceMs);
    const searching = searchable && debounced !== "";
    const matches = useResourceList<Record<string, unknown>>(
      resource,
      { search: debounced, pageSize: 50 },
      { enabled: searching && serverSearch, retry: false },
    );
    const searchRows: VisibleRow[] = React.useMemo(() => {
      if (!searching) return [];
      let found: Node[];
      if (serverSearch) {
        found = (matches.data?.results ?? []).map(asLeaf);
      } else {
        const needle = debounced.toLocaleLowerCase();
        found = knownNodes(tops, kidsOf)
          .filter((node) => labelTextOf(node).toLocaleLowerCase().includes(needle))
          .map((node) => asLeaf(node));
      }
      return found.map((node, index) => ({
        key: keyOf(node),
        node,
        level: 1,
        posinset: index + 1,
        setsize: found.length,
        parentKey: null,
        expandable: false,
        expanded: false,
      }));
      // eslint-disable-next-line react-hooks/exhaustive-deps -- kidsOf reads the queries listed
    }, [searching, serverSearch, matches.data, debounced, top.data, lazyQueries, labelTextOf]);

    const rows = searching ? searchRows : treeRows;

    // --- selection ----------------------------------------------------------
    const selected: ReadonlyArray<string | number> = React.useMemo(() => {
      if (value === null || value === undefined) return [];
      return Array.isArray(value) ? value : [value as string | number];
    }, [value]);
    const isSelected = (key: string): boolean => selected.some((sel) => String(sel) === key);

    const choose = (row: VisibleRow): void => {
      if (onChange === undefined || !choosable(row.key)) return;
      const raw = row.node["id"];
      const nodeId = typeof raw === "number" || typeof raw === "string" ? raw : row.key;
      if (multiple) {
        const next = isSelected(row.key)
          ? selected.filter((sel) => String(sel) !== row.key)
          : [...selected, nodeId];
        onChange([...next], row.node);
      } else {
        onChange(nodeId, row.node);
      }
    };

    // --- focus (roving tabindex) ---------------------------------------------
    const [focusKey, setFocusKey] = React.useState<string | null>(null);
    const focusPending = React.useRef(false);
    const items = React.useRef(new Map<string, HTMLDivElement>());
    const searchRef = React.useRef<HTMLInputElement>(null);
    const moveFocus = (key: string): void => {
      focusPending.current = true;
      setFocusKey(key);
    };
    React.useLayoutEffect(() => {
      if (!focusPending.current || focusKey === null) return;
      const element = items.current.get(focusKey);
      if (element !== undefined) {
        focusPending.current = false;
        element.focus();
      }
    });
    const visibleKeys = new Set(rows.map((row) => row.key));
    const tabKey =
      focusKey !== null && visibleKeys.has(focusKey)
        ? focusKey
        : (rows.find((row) => isSelected(row.key))?.key ?? rows[0]?.key ?? null);

    // Wait for the path to a revealed node before choosing where focus lands.
    const revealKey = reveal === null || reveal === "" ? null : String(reveal);
    const revealing =
      revealKey !== null &&
      !visibleKeys.has(revealKey) &&
      ancestors.error == null &&
      (ancestors.data === undefined ||
        ancestors.data.some((node) => !expanded.has(keyOf(node))) ||
        missingKey !== "" ||
        lazyRoots.some((key) => lazy.get(key)?.isPending === true));
    const focusedOnce = React.useRef(false);
    React.useEffect(() => {
      if (!autoFocus || focusedOnce.current || tabKey === null || revealing) return;
      const target = rows.find((row) => isSelected(row.key))?.key ?? tabKey;
      focusedOnce.current = true;
      moveFocus(target);
      // eslint-disable-next-line react-hooks/exhaustive-deps -- runs as rows arrive
    }, [autoFocus, tabKey, rows.length, revealing]);

    // --- expand and collapse -------------------------------------------------
    const setOpen = (keys: readonly string[], open: boolean): void => {
      setExpanded((previous) => {
        const next = new Set(previous);
        for (const key of keys) {
          if (open) next.add(key);
          else next.delete(key);
        }
        return next;
      });
      if (open) {
        // A branch that failed to load tries again when it is opened again.
        for (const key of keys) {
          const query = lazy.get(key);
          if (query?.isError === true) void query.refetch();
        }
      }
    };
    const toggle = (row: VisibleRow): void => {
      if (!row.expandable) return;
      setOpen([row.key], !row.expanded);
    };

    // --- keyboard -----------------------------------------------------------
    const typeahead = React.useRef({ text: "", at: 0 });
    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
      const current = focusKey ?? tabKey;
      const index = rows.findIndex((row) => row.key === current);
      const row = rows[index];
      if (row === undefined) return;
      const go = (target: VisibleRow | undefined): void => {
        if (target === undefined) return;
        event.preventDefault();
        moveFocus(target.key);
      };
      switch (event.key) {
        case "ArrowDown":
          go(rows[index + 1]);
          if (rows[index + 1] === undefined) event.preventDefault();
          return;
        case "ArrowUp":
          if (index === 0 && searchable) {
            event.preventDefault();
            searchRef.current?.focus();
            return;
          }
          go(rows[index - 1]);
          return;
        case "ArrowRight":
          event.preventDefault();
          if (!row.expandable) return;
          if (!row.expanded) setOpen([row.key], true);
          else if (rows[index + 1]?.parentKey === row.key)
            moveFocus((rows[index + 1] as VisibleRow).key);
          return;
        case "ArrowLeft":
          event.preventDefault();
          if (row.expanded) setOpen([row.key], false);
          else if (row.parentKey !== null) moveFocus(row.parentKey);
          return;
        case "Home":
          go(rows[0]);
          return;
        case "End":
          go(rows[rows.length - 1]);
          return;
        case "Enter":
          event.preventDefault();
          choose(row);
          onActivate?.(row.node);
          return;
        case " ":
        case "Spacebar":
          event.preventDefault();
          choose(row);
          return;
        case "*":
          event.preventDefault();
          setOpen(expandableSiblings(rows, row), true);
          return;
        default:
          break;
      }
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const now = Date.now();
        const state = typeahead.current;
        state.text = now - state.at > TYPEAHEAD_RESET_MS ? event.key : state.text + event.key;
        state.at = now;
        // The same letter again moves on to the next node with it. A longer
        // prefix may stay on the current node.
        const repeated = [...state.text].every((char) => char === state.text[0]);
        const prefix = repeated ? event.key : state.text;
        const from = repeated ? index : index - 1;
        const found = matchPrefix(rows, from, prefix, labelTextOf);
        if (found >= 0) go(rows[found]);
      }
    };

    // --- what the tree says -------------------------------------------------
    const firstLoad = top.data === undefined && top.error == null;
    const loadError = top.data === undefined ? top.error : null;
    const searchPending =
      searching && (term.trim() !== debounced || (serverSearch && matches.isFetching));
    const searchError = searching && serverSearch ? matches.error : null;
    const failed = lazyRoots.filter((key) => lazy.get(key)?.isError === true);
    const loadingBranches = lazyRoots.filter((key) => lazy.get(key)?.isPending === true);
    const truncated =
      top.data?.truncated === true || lazyRoots.some((key) => lazy.get(key)?.data?.truncated);

    const emptyProps: TreeViewEmptyProps | null =
      rows.length > 0 || firstLoad || loadError != null || searchPending || searchError != null
        ? null
        : { reason: searching ? "no-match" : "none", search: debounced, names };

    const labelForKey = (key: string): string => {
      const found = knownNodes(tops, kidsOf).find((node) => keyOf(node) === key);
      return found !== undefined ? labelTextOf(found) : names.singular;
    };

    const announcement = ((): string => {
      if (loadError != null) {
        return describeError(loadError, { action: "view", resource: names.plural }).title;
      }
      if (firstLoad) return `Loading ${names.plural}…`;
      if (searchPending) return "Searching…";
      if (emptyProps !== null) return treeEmptyText(emptyProps);
      if (searching) {
        return `${rows.length.toLocaleString()} ${rows.length === 1 ? `${names.singular} matches` : `${names.plural} match`} “${debounced}”`;
      }
      if (loadingBranches.length > 0) return `Loading ${names.plural}…`;
      return "";
    })();

    const Item = slots.Node;
    const label = props["aria-label"] ?? capitalised(names.plural);

    const tree = (
      <div
        ref={forwardedRef}
        role="tree"
        id={treeId}
        aria-label={props["aria-labelledby"] === undefined ? label : undefined}
        aria-labelledby={props["aria-labelledby"]}
        aria-multiselectable={selectable && multiple ? true : undefined}
        aria-busy={firstLoad || searchPending || undefined}
        className="p-1"
        onKeyDown={handleKeyDown}
      >
        {rows.map((row) => {
          const rowSelected = isSelected(row.key);
          const branch = lazy.get(row.key);
          const branchLoading = row.expanded && branch?.isPending === true;
          const branchFailed = branch?.isError === true;
          const greyed = !choosable(row.key);
          return (
            <div
              key={row.key}
              ref={(element) => {
                if (element === null) items.current.delete(row.key);
                else items.current.set(row.key, element);
              }}
              role="treeitem"
              id={itemId(row.key)}
              aria-level={row.level}
              aria-setsize={row.setsize}
              aria-posinset={row.posinset}
              aria-expanded={row.expandable ? row.expanded : undefined}
              aria-selected={selectable ? rowSelected : undefined}
              aria-disabled={greyed || undefined}
              aria-busy={branchLoading || undefined}
              tabIndex={row.key === tabKey ? 0 : -1}
              onFocus={(event) => {
                if (event.target === event.currentTarget) setFocusKey(row.key);
              }}
              onClick={() => {
                moveFocus(row.key);
                if (selectable && choosable(row.key)) choose(row);
                else toggle(row);
                onActivate?.(row.node);
              }}
              className={cn(
                "flex h-8 cursor-default select-none items-center gap-1 rounded-sm px-2 text-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring aria-selected:bg-accent aria-selected:text-accent-foreground",
                greyed && "text-muted-foreground",
              )}
            >
              <span
                aria-hidden="true"
                className="shrink-0"
                style={{ width: `calc(var(--karni-tree-indent) * ${row.level - 1})` }}
              />
              {row.expandable ? (
                <span
                  aria-hidden="true"
                  data-testid="tree-toggle"
                  className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground"
                  onClick={(event) => {
                    event.stopPropagation();
                    moveFocus(row.key);
                    toggle(row);
                  }}
                >
                  {row.expanded ? (
                    <ChevronDownIcon className="h-4 w-4" />
                  ) : (
                    <ChevronRightIcon className="h-4 w-4" />
                  )}
                </span>
              ) : (
                <span aria-hidden="true" className="h-4 w-4 shrink-0" />
              )}
              <Item
                node={row.node}
                label={labelOf(row.node)}
                level={row.level}
                selected={selectable && rowSelected}
                expanded={row.expanded}
              />
              {branchLoading ? (
                <SpinnerIcon className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
              ) : null}
              {branchFailed ? <AlertIcon className="h-3 w-3 shrink-0 text-destructive" /> : null}
            </div>
          );
        })}
      </div>
    );

    const body = ((): React.ReactNode => {
      if (loadError != null) {
        return (
          <slots.Error
            error={loadError}
            context={{ action: "view", resource: names.plural }}
            onRetry={() => void top.refetch()}
            retrying={top.isFetching}
          />
        );
      }
      if (searchError != null) {
        return (
          <slots.Error
            error={searchError}
            context={{ action: "view", resource: names.plural }}
            onRetry={() => void matches.refetch()}
            retrying={matches.isFetching}
          />
        );
      }
      if (firstLoad) {
        return (
          <div
            role="tree"
            id={treeId}
            aria-label={label}
            aria-multiselectable={selectable && multiple ? true : undefined}
            aria-busy="true"
            className="p-1"
          >
            <slots.Loading rows={LOADING_ROWS} />
          </div>
        );
      }
      if (emptyProps !== null) return <slots.Empty {...emptyProps} />;
      return tree;
    })();

    return (
      <div className={cn("flex flex-col gap-2", className)}>
        {searchable ? (
          <Input
            ref={searchRef}
            type="search"
            value={term}
            aria-label={`Search ${names.plural}`}
            aria-controls={
              loadError == null && searchError == null && emptyProps === null ? treeId : undefined
            }
            placeholder={`Search ${names.plural}`}
            onChange={(event) => setTerm(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" && rows[0] !== undefined) {
                event.preventDefault();
                moveFocus(rows[0].key);
              } else if (event.key === "Escape" && term !== "") {
                event.preventDefault();
                event.stopPropagation();
                setTerm("");
              }
            }}
          />
        ) : null}
        <div className="max-h-[var(--karni-tree-max-height)] overflow-y-auto rounded-md border border-border bg-background">
          {body}
        </div>
        {failed.map((key) => (
          <p key={key} className="flex items-center gap-2 text-xs text-muted-foreground">
            <AlertIcon className="h-3 w-3 shrink-0 text-destructive" />
            <span className="min-w-0 truncate">
              Couldn't load the {names.plural} under {labelForKey(key)}.
            </span>
            <button
              type="button"
              className="font-medium text-foreground underline underline-offset-4"
              onClick={() => void lazy.get(key)?.refetch()}
            >
              Try again
            </button>
          </p>
        ))}
        {truncated && !searching ? (
          <p className="text-xs text-muted-foreground">
            Some branches are too large to show at once. Open a branch or search to see the rest.
          </p>
        ) : null}
        {searching && serverSearch && matches.data !== undefined && matches.data.next !== null ? (
          <p className="text-xs text-muted-foreground">
            Showing the first {rows.length.toLocaleString()} of{" "}
            {matches.data.count.toLocaleString()} matches. Type more to narrow.
          </p>
        ) : null}
        <span className="sr-only" role="status" aria-live="polite">
          {announcement}
        </span>
      </div>
    );
  },
);
TreeView.displayName = "TreeView";
