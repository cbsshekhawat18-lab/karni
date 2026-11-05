import { afterEach, describe, expect, it, vi } from "vitest";
import { BucketUploadError, xhrTransport } from "./transport";

class FakeXhr {
  static last: FakeXhr | null = null;
  static status = 204;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = "";
  upload: {
    onprogress:
      ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  aborted = false;

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: unknown): void {
    this.body = body;
    this.upload.onprogress?.({ lengthComputable: true, loaded: 3, total: 4 });
    this.status = FakeXhr.status;
    if (this.status === 0) this.onerror?.();
    else this.onload?.();
  }

  abort(): void {
    this.aborted = true;
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  FakeXhr.status = 204;
});

describe("xhrTransport", () => {
  it("sends with the headers and reports progress", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const progress: number[] = [];
    const file = new File(["abcd"], "a.txt", { type: "text/plain" });
    await xhrTransport({
      method: "PUT",
      url: "https://bucket.example.test/key",
      body: file,
      headers: { "Content-Type": "text/plain" },
      onProgress: (loaded, total) => progress.push(loaded / total),
    });
    expect(FakeXhr.last?.method).toBe("PUT");
    expect(FakeXhr.last?.headers).toEqual({ "Content-Type": "text/plain" });
    expect(FakeXhr.last?.body).toBe(file);
    expect(progress).toEqual([0.75]);
  });

  it("rejects when the bucket refuses or cannot be reached", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const request = {
      method: "POST" as const,
      url: "https://bucket.example.test/",
      body: new FormData(),
      headers: {},
      onProgress: () => undefined,
    };
    FakeXhr.status = 403;
    await expect(xhrTransport(request)).rejects.toBeInstanceOf(BucketUploadError);
    FakeXhr.status = 0;
    await expect(xhrTransport(request)).rejects.toThrow("CORS");
  });

  it("aborts with the signal", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const controller = new AbortController();
    controller.abort();
    await expect(
      xhrTransport({
        method: "PUT",
        url: "https://bucket.example.test/key",
        body: new File(["x"], "x.txt"),
        headers: {},
        onProgress: () => undefined,
        signal: controller.signal,
      }),
    ).rejects.toThrow("cancelled");
    expect(FakeXhr.last?.aborted).toBe(true);
  });
});
