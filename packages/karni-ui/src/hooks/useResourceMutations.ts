/**
 * Create / update / remove mutations for one resource (contract "Hooks" +
 * D2, D3, D11).
 *
 * - `create` → `POST /<resource>/`
 * - `update` → `PATCH /<resource>/<id>/` with `{ id, values }`
 * - `remove` → `DELETE /<resource>/<id>/`
 *
 * Every successful mutation invalidates `karniKeys.resource(resource)` (all
 * list + detail entries of the resource) plus any `options.invalidateKeys` —
 * never the bare `["karni"]` root (D4), which would nuke the cached schema.
 *
 * ## Multipart (D2)
 * Payloads containing a top-level `File` (or an array containing one) are
 * encoded as FormData — on create AND PATCH — with arrays as repeated keys,
 * json values JSON-stringified, and no manual Content-Type. Unchanged file
 * values (the URL string the backend returned) are omitted from PATCH
 * payloads so they are never re-submitted as uploads.
 *
 * ## PATCH granularity — contract for the form builder (D3)
 * `update` sends EXACTLY the keys present in `values`; it never diffs or
 * drops fields itself (beyond the file-URL omission above). ResourceForm
 * must therefore build `values` at TOP-LEVEL FIELD granularity from
 * react-hook-form's `dirtyFields`: when ANY leaf inside a field's subtree is
 * dirty (nested object, array member, multi-relation), include that field's
 * ENTIRE current value — never a partial subtree, because DRF PATCH replaces
 * the whole field value. An emptied nullable field must be sent as `null`
 * (not `""`/`undefined`): a key that is absent is simply left unchanged by
 * the backend, and `undefined` does not survive JSON serialization.
 */
import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useCallback } from "react";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { encodeBody, fileFieldNames, omitUnchangedFileUrls } from "./multipart";
import { detailPath, listPath } from "./params";
import type { ResourceMutationsOptions } from "./types";

/** Result bundle — the three mutations, each a full TanStack mutation object. */
export interface ResourceMutations<T> {
  create: UseMutationResult<T, unknown, Record<string, unknown>>;
  update: UseMutationResult<T, unknown, { id: string | number; values: Record<string, unknown> }>;
  remove: UseMutationResult<void, unknown, string | number>;
}

/** Create, update and remove mutations for a resource; each success refreshes the resource's cached lists and items. */
export function useResourceMutations<T = Record<string, unknown>>(
  resource: string,
  options?: ResourceMutationsOptions,
): ResourceMutations<T> {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const invalidateKeys = options?.invalidateKeys;

  const invalidate = useCallback(async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) });
    if (invalidateKeys !== undefined) {
      await Promise.all(
        invalidateKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      );
    }
  }, [queryClient, resource, invalidateKeys]);

  const create = useMutation<T, unknown, Record<string, unknown>>({
    mutationFn: (values) =>
      client.request<T>(listPath(resource), { method: "POST", body: encodeBody(values) }),
    onSuccess: () => invalidate(),
  });

  const update = useMutation<T, unknown, { id: string | number; values: Record<string, unknown> }>({
    mutationFn: ({ id, values }) => {
      const fileFields = fileFieldNames(queryClient.getQueryData(karniKeys.schema()), resource);
      const prepared = omitUnchangedFileUrls(values, fileFields);
      return client.request<T>(detailPath(resource, id), {
        method: "PATCH",
        body: encodeBody(prepared),
      });
    },
    onSuccess: () => invalidate(),
  });

  // `void` lives in the annotation, not in call-site type arguments: eslint's
  // strict no-invalid-void-type only permits it in type-reference positions.
  const remove: UseMutationResult<void, unknown, string | number> = useMutation({
    mutationFn: async (id: string | number): Promise<void> => {
      await client.request(detailPath(resource, id), { method: "DELETE" });
    },
    onSuccess: () => invalidate(),
  });

  return { create, update, remove };
}
