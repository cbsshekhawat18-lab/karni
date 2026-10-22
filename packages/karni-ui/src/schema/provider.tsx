/**
 * <KarniProvider> — wires the Karni client into React (contract "Schema
 * client"). Wraps TanStack's QueryClientProvider, creating a QueryClient when
 * none is given (the `queryClient` prop is the escape hatch for apps that
 * already have one), and provides the client via context for every hook and
 * component in the package.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { KarniPrimitivesProvider, type KarniPrimitiveOverrides } from "../primitives/registry";
import type { KarniClient } from "./client";

const KarniClientContext = createContext<KarniClient | null>(null);

export interface KarniProviderProps {
  client: KarniClient;
  /** Bring your own QueryClient; one is created (once) when omitted. */
  queryClient?: QueryClient;
  /**
   * The project's own primitives, by role: `{ button: Button, input: Input }`.
   * Every Karni component then renders them in place of Karni's (see
   * KarniPrimitivesProvider for the contract).
   */
  primitives?: KarniPrimitiveOverrides;
  children?: ReactNode;
}

const NO_PRIMITIVES: KarniPrimitiveOverrides = {};

/** Rendered once at the app root, it provides the Karni client and a TanStack QueryClient to everything inside it. */
export function KarniProvider(props: KarniProviderProps): ReactElement {
  const { client, queryClient, primitives = NO_PRIMITIVES, children } = props;
  // Lazy initial state so the fallback QueryClient is created exactly once
  // per provider instance, never on re-renders.
  const [ownQueryClient] = useState(() => queryClient ?? new QueryClient());
  return (
    <QueryClientProvider client={queryClient ?? ownQueryClient}>
      <KarniClientContext.Provider value={client}>
        <KarniPrimitivesProvider value={primitives}>{children}</KarniPrimitivesProvider>
      </KarniClientContext.Provider>
    </QueryClientProvider>
  );
}

/** Returns the Karni client from `KarniProvider` and throws a descriptive error outside one. */
export function useKarniClient(): KarniClient {
  const client = useContext(KarniClientContext);
  if (client === null) {
    throw new Error(
      "useKarniClient must be used within <KarniProvider>. " +
        "Wrap your app in <KarniProvider client={createKarniClient({ baseUrl })}>.",
    );
  }
  return client;
}
