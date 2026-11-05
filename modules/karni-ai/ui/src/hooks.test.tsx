import { KarniApiError, KarniProvider, createKarniClient, importJobKey } from "@karni/ui";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { API_BASE, extractFixture, jobFixture, state } from "../tests/msw/server";
import { makeQueryClient } from "../tests/test-utils";
import { extractRefusal, useExtract } from "./hooks";

function setup() {
  const queryClient = makeQueryClient();
  const client = createKarniClient({ baseUrl: API_BASE });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  const hook = renderHook(() => useExtract("products"), { wrapper });
  return { ...hook, queryClient };
}

describe("useExtract", () => {
  it("posts text as JSON with the resource and caches the import job", async () => {
    const { result, queryClient } = setup();
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ text: "Name: Hose" });
    });
    expect(answer).toEqual(extractFixture);
    expect(state.bodies).toEqual([{ resource: "products", text: "Name: Hose" }]);
    expect(queryClient.getQueryData(importJobKey("products", jobFixture.id))).toEqual(jobFixture);
  });

  it("posts a URL as JSON", async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.mutateAsync({ url: "https://shop.example.com/" });
    });
    expect(state.bodies).toEqual([{ resource: "products", url: "https://shop.example.com/" }]);
  });

  it("posts a PDF as multipart", async () => {
    const { result } = setup();
    const file = new File(["%PDF-1.4"], "list.pdf", { type: "application/pdf" });
    await act(async () => {
      await result.current.mutateAsync({ file });
    });
    const raw = String(state.bodies[0]?.["multipart"]);
    expect(raw).toMatch(/name="resource"\r\n\r\nproducts/);
    expect(raw).toMatch(/name="file"; filename="[^"]+"\r\nContent-Type: application\/pdf/);
  });

  it("rejects with the refusal, which extractRefusal reads", async () => {
    state.answer = { code: "AI011", detail: "127.0.0.1 is not a public address." };
    state.status = 400;
    const { result } = setup();
    act(() => result.current.mutate({ url: "http://127.0.0.1/" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(KarniApiError);
    expect(extractRefusal(result.current.error)).toEqual({
      code: "AI011",
      detail: "127.0.0.1 is not a public address.",
    });
    expect(extractRefusal(new Error("x"))).toBeUndefined();
  });
});
