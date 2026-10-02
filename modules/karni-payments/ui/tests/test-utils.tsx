/**
 * Test harness: renders UI inside <KarniProvider> with a fresh KarniClient
 * (baseUrl carries /api, G9) and a fresh QueryClient with retries disabled.
 */
import { KarniProvider, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { API_BASE } from "./msw/handlers";

export interface RenderWithKarniResult extends RenderResult {
  queryClient: QueryClient;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithKarni(
  ui: ReactElement,
  options?: { queryClient?: QueryClient },
): RenderWithKarniResult {
  const queryClient = options?.queryClient ?? makeQueryClient();
  const client = createKarniClient({ baseUrl: API_BASE });
  const result = render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
  return { ...result, queryClient };
}
