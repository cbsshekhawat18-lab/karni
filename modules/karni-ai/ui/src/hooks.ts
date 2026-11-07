/**
 * `useExtract(resource)`: a mutation that posts one source to `POST /api/ai/extract/`
 * and resolves with the import preview of the rows read from it. Experimental.
 *
 * Nothing is saved: confirm the preview with `@karni/ui`'s
 * `useImportActions(resource).commit` (the import's own commit). The answer's
 * import job is put in `@karni/ui`'s import job cache, so `useImportJob(resource, id)`
 * has it without a request.
 */
import { importJobKey, KarniApiError, karniKeys, useKarniClient } from "@karni/ui";
import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import type { ExtractInput, ExtractRefusal, ExtractResult } from "./types";

/** Experimental. The extraction endpoint, relative to the client's base URL (it carries `/api`). */
export const EXTRACT_PATH = "/ai/extract/";

/** Experimental. The refusal an extraction answered with (`{code, detail}`), else undefined. */
export function extractRefusal(error: unknown): ExtractRefusal | undefined {
  if (!(error instanceof KarniApiError) || typeof error.data !== "object" || error.data === null) {
    return undefined;
  }
  const data = error.data as Record<string, unknown>;
  const code = data["code"];
  const detail = data["detail"];
  if (typeof code === "string" && /^AI\d{3}$/.test(code) && typeof detail === "string") {
    return { code, detail };
  }
  return undefined;
}

/** Experimental. Posts one source for `resource` (a router prefix) and resolves with the preview. */
export function useExtract(
  resource: string,
): UseMutationResult<ExtractResult, unknown, ExtractInput> {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  return useMutation<ExtractResult, unknown, ExtractInput>({
    mutationFn: (input) => {
      if ("file" in input) {
        const form = new FormData();
        form.append("resource", resource);
        form.append("file", input.file);
        return client.request<ExtractResult>(EXTRACT_PATH, { method: "POST", body: form });
      }
      return client.request<ExtractResult>(EXTRACT_PATH, {
        method: "POST",
        body: { resource, ...input },
      });
    },
    onSuccess: (result) => {
      queryClient.setQueryData(importJobKey(resource, result.id), result.job);
      // The caller's usage list (GET /api/ai/) has one more call.
      void queryClient.invalidateQueries({ queryKey: karniKeys.resource("ai") });
    },
  });
}
