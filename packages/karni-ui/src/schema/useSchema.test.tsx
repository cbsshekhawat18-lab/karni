/**
 * KarniProvider + useSchema suite (contract "Schema client"): client context,
 * the ["karni","$schema"] query (fetched + parsed once, staleTime Infinity),
 * and the error-boundary-friendly unknown-resource throw.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { Component } from "react";
import type { ReactElement, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { createKarniClient } from "./client";
import type { KarniClient } from "./client";
import { KarniProvider, useKarniClient } from "./provider";
import { SCHEMA_QUERY_KEY, useParsedSchema, useSchema } from "./useSchema";

const BASE = "http://karni.test";

function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: KarniClient, queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }): ReactElement {
    return (
      <KarniProvider client={client} queryClient={queryClient}>
        {children}
      </KarniProvider>
    );
  };
}

class CatchBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  override state: { message: string | null } = { message: null };

  static getDerivedStateFromError(error: unknown): { message: string } {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  override render(): ReactNode {
    if (this.state.message !== null) return <div role="alert">{this.state.message}</div>;
    return this.props.children;
  }
}

describe("useKarniClient", () => {
  it("returns the provided client inside <KarniProvider>", () => {
    const client = createKarniClient({ baseUrl: BASE });
    const { result } = renderHook(() => useKarniClient(), {
      wrapper: wrapperFor(client, testQueryClient()),
    });
    expect(result.current).toBe(client);
  });

  it("throws a descriptive error outside <KarniProvider>", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // React render-error noise
    expect(() => renderHook(() => useKarniClient())).toThrowError(
      /useKarniClient must be used within <KarniProvider>/,
    );
  });
});

describe("useSchema", () => {
  it("loads, parses and exposes a resource schema", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const { result } = renderHook(() => useSchema("events"), {
      wrapper: wrapperFor(client, testQueryClient()),
    });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data?.resource).toBe("events");
    expect(result.current.data?.fields.some((field) => field.name === "title")).toBe(true);
    expect(result.current.data?.operations.list?.hasSearch).toBe(true);
  });

  it("fetches and parses the document once for many consumers", async () => {
    let schemaFetches = 0;
    const inner = createKarniClient({ baseUrl: BASE });
    const counting: KarniClient = {
      ...inner,
      request: (path, options) => {
        if (path === inner.schemaUrl) schemaFetches += 1;
        return inner.request(path, options);
      },
    };
    const queryClient = testQueryClient();
    const wrapper = wrapperFor(counting, queryClient);
    const first = renderHook(() => useSchema("events"), { wrapper });
    const second = renderHook(() => useSchema("venues"), { wrapper });
    await waitFor(() => expect(first.result.current.data).toBeDefined());
    await waitFor(() => expect(second.result.current.data).toBeDefined());
    expect(schemaFetches).toBe(1);
    expect(queryClient.getQueryState(SCHEMA_QUERY_KEY)?.status).toBe("success");
  });

  it("throws for an unknown resource AFTER load, listing known resources", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // React render-error noise
    const client = createKarniClient({ baseUrl: BASE });
    const queryClient = testQueryClient();
    function Probe(): ReactElement {
      const { data } = useSchema("evnets"); // typo on purpose
      return <div>{data?.resource}</div>;
    }
    render(
      <KarniProvider client={client} queryClient={queryClient}>
        <CatchBoundary>
          <Probe />
        </CatchBoundary>
      </KarniProvider>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain('Unknown resource "evnets"');
    expect(alert.textContent).toContain("events");
    expect(alert.textContent).toContain("venues");
  });

  it("surfaces fetch errors through `error` without throwing", async () => {
    const client = createKarniClient({ baseUrl: BASE, schemaUrl: "/api/events/999/" });
    const { result } = renderHook(() => useSchema("events"), {
      wrapper: wrapperFor(client, testQueryClient()),
    });
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.data).toBeUndefined();
    expect(result.current.isLoading).toBe(false);
  });
});

describe("useParsedSchema", () => {
  it("exposes the root auth mode for the auth layer", async () => {
    const client = createKarniClient({ baseUrl: BASE });
    const { result } = renderHook(() => useParsedSchema(), {
      wrapper: wrapperFor(client, testQueryClient()),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.authMode).toBe("jwt");
  });
});
