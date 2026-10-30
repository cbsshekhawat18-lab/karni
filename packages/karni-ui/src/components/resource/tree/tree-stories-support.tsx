/**
 * Shared story support for the tree components: the providers and the msw
 * handlers of the simulated tree backend.
 *
 * Story support only: never imported by shipped component code.
 */
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { treeBackend, type TreeBackendOptions } from "./tree-backend";

export function TreeStoryProviders(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      {props.children}
    </KarniProvider>
  );
}

/** Story parameters that serve the tree backend with `options`. */
export function treeStoryBackend(options: TreeBackendOptions = {}): {
  msw: { handlers: unknown[] };
} {
  return { msw: { handlers: treeBackend(options).handlers } };
}
