/**
 * useSchema — the schema registry hook (contract "Schema client").
 *
 * The OpenAPI document is fetched under the pinned ["karni", "$schema"] key
 * with staleTime Infinity and parsed ONCE inside the query function, so every
 * consumer shares a single ParsedSchema instance per fetch. The key literal
 * is duplicated from karniKeys.schema() (hooks/keys.ts) by design: both
 * modules are bound to the same D4-pinned shape and neither imports the
 * other at runtime.
 *
 * Asking for a resource the backend does not expose — after the schema has
 * loaded — throws during render (error-boundary friendly) with the list of
 * known resources, which catches typos immediately instead of rendering an
 * empty table.
 */
import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { parseOpenApi } from "./parse";
import { useKarniClient } from "./provider";
import type { ParsedSchema, ResourceSchema } from "./types";

/** D4-pinned query key for the parsed schema document. */
export const SCHEMA_QUERY_KEY = ["karni", "$schema"] as const;

/**
 * The whole parsed registry (resources + root x-karni-auth-mode). Internal to
 * the package — the auth layer reads `data.authMode` from here; apps use
 * useSchema(resource).
 */
export function useParsedSchema(): UseQueryResult<ParsedSchema> {
  const client = useKarniClient();
  return useQuery<ParsedSchema>({
    queryKey: SCHEMA_QUERY_KEY,
    staleTime: Infinity,
    queryFn: async () => parseOpenApi(await client.request<unknown>(client.schemaUrl)),
  });
}

export interface UseSchemaResult {
  data: ResourceSchema | undefined;
  isLoading: boolean;
  error: unknown;
}

export function useSchema(resource: string): UseSchemaResult {
  const query = useParsedSchema();

  if (query.data !== undefined) {
    const schema = query.data.resources[resource];
    if (schema === undefined) {
      const known = Object.keys(query.data.resources).sort();
      throw new Error(
        `Unknown resource "${resource}". Known resources: ` +
          `${known.length > 0 ? known.join(", ") : "(none — does the schema expose x-karni-resource?)"}.`,
      );
    }
    return { data: schema, isLoading: false, error: query.error };
  }

  return { data: undefined, isLoading: query.isPending, error: query.error };
}
