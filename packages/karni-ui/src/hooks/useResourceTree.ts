/**
 * Experimental. Hooks for a tree resource (a Karni `TreeModel`): its nested
 * nodes, a node's children and ancestors, and moving or deleting a branch.
 *
 * - `useResourceTree` → `GET /<resource>/tree/?root=&depth=`
 * - `useResourceChildren` → `GET /<resource>/<id>/children/` (paginated)
 * - `useResourceAncestors` → `GET /<resource>/<id>/ancestors/` (root first)
 * - `useTreeMutations` → `POST /<resource>/<id>/move/` and
 *   `DELETE /<resource>/<id>/?branch=true`
 *
 * Every key lives under `karniKeys.resource(resource)`, so any mutation of
 * the resource (these, or `useResourceMutations`) refreshes them.
 *
 * Escape hatch: each query hook forwards TanStack Query options except
 * `queryKey`/`queryFn`.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useCallback } from "react";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { detailPath, listPath } from "./params";
import type { Paginated } from "./types";

/**
 * Experimental. One node of a tree response: the row's own fields, whether
 * it has children, and its children when they were loaded (`null`: not loaded,
 * so ask for them with `root`).
 */
export type TreeNode<T extends object = Record<string, unknown>> = T & {
  has_children: boolean;
  children: Array<TreeNode<T>> | null;
};

/** Experimental. The `tree/` answer: the top nodes, nested, and whether the node limit cut it. */
export interface TreeResponse<T extends object = Record<string, unknown>> {
  results: Array<TreeNode<T>>;
  /** True when the server's node limit cut the answer: some nodes have `children: null`. */
  truncated: boolean;
}

/** Experimental. What `useResourceTree` asks for. */
export interface ResourceTreeParams {
  /** The node whose children are the top level. Absent or null: the roots. */
  root?: string | number | null;
  /** Levels to load (1 to 10). Default: the server's (2). */
  depth?: number;
  /** Set false to wait (for example until a popover opens). Default true. */
  enabled?: boolean;
}

/** Experimental. What `useResourceChildren` asks for. */
export interface ResourceChildrenParams {
  page?: number;
  pageSize?: number;
  enabled?: boolean;
}

/** Experimental. The body of a move: the new parent (null for a root) and, on an ordered tree, the position. */
export interface TreeMoveInput {
  id: string | number;
  parent: string | number | null;
  /** 0 is first among the new siblings. Absent: last. Ordered trees only. */
  position?: number;
}

/** Experimental. The two tree writes: `move` and `removeBranch`. */
export interface TreeMutations<T extends object = Record<string, unknown>> {
  move: UseMutationResult<TreeNode<T>, unknown, TreeMoveInput>;
  /** Deletes the node and every live node below it (`DELETE ?branch=true`). */
  removeBranch: UseMutationResult<void, unknown, string | number>;
}

/** The query string of a `tree/` request. */
export function treeQuery(params?: ResourceTreeParams): Record<string, string> {
  const query: Record<string, string> = {};
  if (params?.root !== undefined && params.root !== null) query.root = String(params.root);
  if (params?.depth !== undefined) query.depth = String(params.depth);
  return query;
}

/** Experimental. The nested nodes of a tree resource (`GET /<resource>/tree/`), under `root` or from the roots. */
export function useResourceTree<T extends object = Record<string, unknown>>(
  resource: string,
  params?: ResourceTreeParams,
  options?: Omit<UseQueryOptions<TreeResponse<T>>, "queryKey" | "queryFn">,
): UseQueryResult<TreeResponse<T>> {
  const client = useKarniClient();
  return useQuery<TreeResponse<T>>({
    ...options,
    enabled: (options?.enabled ?? true) && params?.enabled !== false,
    queryKey: karniKeys.tree(resource, params),
    queryFn: ({ signal }) =>
      client.request<TreeResponse<T>>(`${listPath(resource)}tree/`, {
        query: treeQuery(params),
        signal,
      }),
  });
}

/** Experimental. One page of a node's children (`GET /<resource>/<id>/children/`). */
export function useResourceChildren<T extends object = Record<string, unknown>>(
  resource: string,
  id: string | number,
  params?: ResourceChildrenParams,
  options?: Omit<UseQueryOptions<Paginated<TreeNode<T>>>, "queryKey" | "queryFn">,
): UseQueryResult<Paginated<TreeNode<T>>> {
  const client = useKarniClient();
  const query: Record<string, string> = {};
  if (params?.page !== undefined) query.page = String(params.page);
  if (params?.pageSize !== undefined) query.page_size = String(params.pageSize);
  return useQuery<Paginated<TreeNode<T>>>({
    ...options,
    enabled: (options?.enabled ?? true) && params?.enabled !== false,
    queryKey: karniKeys.children(resource, id, params),
    queryFn: ({ signal }) =>
      client.request<Paginated<TreeNode<T>>>(`${detailPath(resource, id)}children/`, {
        query,
        signal,
      }),
  });
}

/** Experimental. The nodes above one node, root first (`GET /<resource>/<id>/ancestors/`). */
export function useResourceAncestors<T extends object = Record<string, unknown>>(
  resource: string,
  id: string | number,
  options?: Omit<UseQueryOptions<Array<TreeNode<T>>>, "queryKey" | "queryFn">,
): UseQueryResult<Array<TreeNode<T>>> {
  const client = useKarniClient();
  return useQuery<Array<TreeNode<T>>>({
    ...options,
    queryKey: karniKeys.ancestors(resource, id),
    queryFn: ({ signal }) =>
      client.request<Array<TreeNode<T>>>(`${detailPath(resource, id)}ancestors/`, { signal }),
  });
}

/** Experimental. Move a node or delete a branch. Each success refreshes every query of the resource. */
export function useTreeMutations<T extends object = Record<string, unknown>>(
  resource: string,
): TreeMutations<T> {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) }),
    [queryClient, resource],
  );
  const move = useMutation<TreeNode<T>, unknown, TreeMoveInput>({
    mutationFn: ({ id, parent, position }) =>
      client.request<TreeNode<T>>(`${detailPath(resource, id)}move/`, {
        method: "POST",
        body: position === undefined ? { parent } : { parent, position },
      }),
    onSuccess: () => invalidate(),
  });
  const removeBranch: UseMutationResult<void, unknown, string | number> = useMutation({
    mutationFn: async (id: string | number): Promise<void> => {
      await client.request(detailPath(resource, id), {
        method: "DELETE",
        query: { branch: "true" },
      });
    },
    onSuccess: () => invalidate(),
  });
  return { move, removeBranch };
}
