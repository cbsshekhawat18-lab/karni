/**
 * Test harness: renders UI inside <KarniProvider> with a fresh client (baseUrl
 * carries /api), a QueryClient with retries off, a session-mode AuthProvider
 * (a visitor unless the handlers say otherwise) and a CommerceProvider whose
 * navigation the test reads in `navigated`.
 */
import { AuthProvider, KarniProvider, Toaster, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { CommerceProvider } from "../src/routes";
import { API_BASE } from "./msw/handlers";

export interface RenderWithCommerceResult extends RenderResult {
  queryClient: QueryClient;
  navigated: string[];
}

export function renderWithCommerce(ui: ReactElement): RenderWithCommerceResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const client = createKarniClient({ baseUrl: API_BASE });
  const navigated: string[] = [];
  const result = render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="session">
        <CommerceProvider navigate={(to) => navigated.push(to)} paths={{ browse: "/shop" }}>
          {ui}
          <Toaster />
        </CommerceProvider>
      </AuthProvider>
    </KarniProvider>,
  );
  return { ...result, queryClient, navigated };
}
