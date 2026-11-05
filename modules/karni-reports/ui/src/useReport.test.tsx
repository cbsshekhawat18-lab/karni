import { KarniProvider, createKarniClient, KarniApiError } from "@karni/ui";
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { API_BASE, PDF_BYTES, REPORT_BASE, calls, ready } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";
import { makeQueryClient } from "../tests/test-utils";
import { reportKey, reportPath, useReport } from "./useReport";

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return (
    <KarniProvider
      client={createKarniClient({ baseUrl: API_BASE })}
      queryClient={makeQueryClient()}
    >
      {children}
    </KarniProvider>
  );
}

describe("useReport", () => {
  it("requests, polls the status until ready, then downloads", async () => {
    const save = vi.fn();
    const { result } = renderHook(() => useReport("product-sheet", 7, { pollInterval: 10, save }), {
      wrapper,
    });
    expect(result.current.status).toBe("idle");
    expect(result.current.isWorking).toBe(false);

    let answer: unknown;
    await act(async () => {
      answer = await result.current.request();
    });
    expect(answer).toMatchObject({ status: "pending" });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.isWorking).toBe(false);
    expect(result.current.state?.url).toBe(ready.url);
    expect(calls.requests).toBe(1);
    expect(calls.statuses).toBeGreaterThanOrEqual(2);

    let filename = "";
    await act(async () => {
      filename = await result.current.download();
    });
    expect(filename).toBe("product-sheet-7.pdf");
    expect(save).toHaveBeenCalledTimes(1);
    const [blob, name] = save.mock.calls[0] as [Blob, string];
    expect(name).toBe("product-sheet-7.pdf");
    expect(blob.size).toBe(PDF_BYTES.length);
  });

  it("stops at once when the file is already cached", async () => {
    server.use(http.post(REPORT_BASE, () => HttpResponse.json(ready)));
    const { result } = renderHook(() => useReport("product-sheet", "7", { pollInterval: 10 }), {
      wrapper,
    });
    await act(async () => {
      await result.current.request();
    });
    expect(result.current.status).toBe("ready");
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(calls.statuses).toBe(0);
  });

  it("reports a refused request as the API's error", async () => {
    server.use(
      http.post(REPORT_BASE, () => HttpResponse.json({ detail: "Not found." }, { status: 404 })),
    );
    const { result } = renderHook(() => useReport("product-sheet", 7), { wrapper });
    await act(async () => {
      await expect(result.current.request()).rejects.toBeInstanceOf(KarniApiError);
    });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(KarniApiError));
    expect(result.current.status).toBe("idle");
  });

  it("watch loads the last request's status on mount", async () => {
    server.use(http.get(`${REPORT_BASE}status/`, () => HttpResponse.json(ready)));
    const { result } = renderHook(() => useReport("product-sheet", 7, { watch: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("builds its key and path from the report and the row", () => {
    expect(reportKey("product-sheet", 7)).toEqual(["karni", "reports", "product-sheet", "7"]);
    expect(reportPath("a b", "x/y")).toBe("/reports/a%20b/x%2Fy/");
  });
});
