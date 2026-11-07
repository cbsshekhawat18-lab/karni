import { act, renderHook, waitFor } from "@testing-library/react";
import { KarniProvider, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import {
  API_BASE,
  CONFIRM_ANSWER,
  POST_ANSWER,
  fakeApi,
  readText,
  recordingTransport,
} from "../tests/test-utils";
import type { FakeApi, Route } from "../tests/test-utils";
import { useProtectedFileLink, useProtectedUpload } from "./hooks";
import type { BucketTransport } from "./transport";
import { UPLOAD_REFERENCE_TYPE } from "./types";

function wrapper(api: FakeApi): (props: { children: ReactNode }) => ReactNode {
  const client = createKarniClient({ baseUrl: API_BASE, fetch: api.fetch });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <KarniProvider client={client} queryClient={queryClient}>
        {children}
      </KarniProvider>
    );
  };
}

const pdf = (): File => new File(["%PDF-1."], "guide.pdf", { type: "application/pdf" });

function uploadRoute(answer: unknown, confirm: { status?: number; body: unknown }): Route {
  return (call) => {
    if (call.url.endsWith("/products/files/manual/upload/")) return { body: answer };
    if (call.url.endsWith("/products/files/manual/confirm/")) return confirm;
    return undefined;
  };
}

function setup(route: Route, transport: BucketTransport) {
  const api = fakeApi(route);
  const hook = renderHook(
    () => useProtectedUpload({ resource: "products", field: "manual", transport }),
    { wrapper: wrapper(api) },
  );
  return { api, hook };
}

describe("useProtectedUpload", () => {
  it("sends the file through a presigned POST, then confirms it", async () => {
    const bucket = recordingTransport();
    const { api, hook } = setup(
      uploadRoute(POST_ANSWER, { body: CONFIRM_ANSWER }),
      bucket.transport,
    );
    let result: Awaited<ReturnType<typeof hook.result.current.upload>> | undefined;
    await act(async () => {
      result = await hook.result.current.upload(pdf());
    });
    expect(api.calls[0]).toMatchObject({
      method: "POST",
      url: `${API_BASE}/products/files/manual/upload/`,
      body: { name: "guide.pdf", content_type: "application/pdf", size: 7 },
    });
    const sent = bucket.requests[0];
    expect(sent?.method).toBe("POST");
    expect(sent?.url).toBe("https://bucket.example.test/");
    const form = sent?.body as FormData;
    // The policy's fields come first and the file last, as S3 requires.
    expect([...form.keys()]).toEqual(["key", "policy", "Content-Type", "file"]);
    expect(api.calls[1]).toMatchObject({
      url: `${API_BASE}/products/files/manual/confirm/`,
      body: { token: "upload-token" },
    });
    expect(result?.method).toBe("post");
    expect(result?.token).toBe("confirmed-token");
    expect(result?.value.type).toBe(UPLOAD_REFERENCE_TYPE);
    expect(result?.value.name).toBe("guide.pdf");
    expect(result !== undefined && (await readText(result.value))).toBe("confirmed-token");
    expect(hook.result.current.status).toBe("done");
    expect(hook.result.current.progress).toBe(1);
  });

  it("sends the file through a presigned PUT with the signed headers", async () => {
    const bucket = recordingTransport();
    const answer = {
      ...POST_ANSWER,
      method: "put",
      url: "https://acct.r2.example.test/bucket/key?X-Amz-Signature=x",
      fields: undefined,
      headers: { "Content-Type": "application/pdf" },
    };
    const { hook } = setup(uploadRoute(answer, { body: CONFIRM_ANSWER }), bucket.transport);
    await act(async () => {
      await hook.result.current.upload(pdf());
    });
    expect(bucket.requests[0]).toMatchObject({
      method: "PUT",
      url: answer.url,
      headers: { "Content-Type": "application/pdf" },
    });
    expect(bucket.requests[0]?.body).toBeInstanceOf(File);
  });

  it("gives the file itself on local storage, with nothing sent to a bucket", async () => {
    const bucket = recordingTransport();
    const answer = { method: "api", max_size: 1048576, content_types: [] };
    const { api, hook } = setup(uploadRoute(answer, { body: {} }), bucket.transport);
    const file = pdf();
    let value: File | undefined;
    await act(async () => {
      value = (await hook.result.current.upload(file)).value;
    });
    expect(value).toBe(file);
    expect(bucket.requests).toEqual([]);
    expect(api.calls).toHaveLength(1);
  });

  it("reports a refused confirm as an error", async () => {
    const bucket = recordingTransport();
    const refused = {
      status: 400,
      body: ["STORE012: The file was sent as text/html, not the application/pdf declared."],
    };
    const { hook } = setup(uploadRoute(POST_ANSWER, refused), bucket.transport);
    await act(async () => {
      await expect(hook.result.current.upload(pdf())).rejects.toThrow();
    });
    expect(hook.result.current.status).toBe("error");
    expect(hook.result.current.error).not.toBeNull();
    act(() => hook.result.current.reset());
    expect(hook.result.current.status).toBe("idle");
  });

  it("reports a bucket that refuses the file", async () => {
    const bucket = recordingTransport(new Error("Storage refused the file (HTTP 403)."));
    const { api, hook } = setup(
      uploadRoute(POST_ANSWER, { body: CONFIRM_ANSWER }),
      bucket.transport,
    );
    await act(async () => {
      await expect(hook.result.current.upload(pdf())).rejects.toThrow("HTTP 403");
    });
    expect(hook.result.current.error?.message).toContain("HTTP 403");
    expect(api.calls).toHaveLength(1); // nothing confirmed
  });
});

describe("useProtectedFileLink", () => {
  it("asks the download path for a signed link", async () => {
    const api = fakeApi((call) =>
      call.url.startsWith(`${API_BASE}/products/7/files/photo/`)
        ? {
            body: {
              url: "https://bucket.example.test/t.webp?sig",
              expires_in: 300,
              name: "t.webp",
            },
          }
        : undefined,
    );
    const hook = renderHook(
      () => useProtectedFileLink(`${API_BASE}/products/7/files/photo/`, { size: "small" }),
      { wrapper: wrapper(api) },
    );
    await waitFor(() =>
      expect(hook.result.current.data?.url).toBe("https://bucket.example.test/t.webp?sig"),
    );
    expect(api.calls[0]?.url).toBe(`${API_BASE}/products/7/files/photo/?size=small`);
    expect(api.calls[0]?.accept).toBe("application/json");
  });

  it("fetches nothing without a path", () => {
    const api = fakeApi(() => undefined);
    renderHook(() => useProtectedFileLink(null), { wrapper: wrapper(api) });
    expect(api.calls).toEqual([]);
  });
});
