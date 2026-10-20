import "@testing-library/jest-dom/vitest";
import { File as NodeFile } from "node:buffer";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./tests/msw/server";

// --- jsdom polyfills required by Radix UI primitives ------------------------

class ResizeObserverStub {
  observe(): void {
    // intentionally empty: jsdom has no layout
  }
  unobserve(): void {
    // intentionally empty
  }
  disconnect(): void {
    // intentionally empty
  }
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

if (typeof Element.prototype.hasPointerCapture !== "function") {
  Element.prototype.hasPointerCapture = () => false;
}
if (typeof Element.prototype.setPointerCapture !== "function") {
  Element.prototype.setPointerCapture = () => undefined;
}
if (typeof Element.prototype.releasePointerCapture !== "function") {
  Element.prototype.releasePointerCapture = () => undefined;
}
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => undefined;
}

// jsdom's Blob/File implement only slice/size/type — no arrayBuffer, text or
// stream. Node's fetch (undici) serializes a FormData file part by iterating
// `part.stream()` inside an async generator, so POSTing a File through msw
// hangs forever without these. Backed by jsdom's own FileReader; the streams
// are the Node-native ReadableStream undici expects (async-iterable).
function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("FileReader failed"));
    reader.readAsArrayBuffer(blob);
  });
}

if (typeof Blob.prototype.arrayBuffer !== "function") {
  Blob.prototype.arrayBuffer = function arrayBuffer(this: Blob): Promise<ArrayBuffer> {
    return blobToArrayBuffer(this);
  };
}
if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = async function text(this: Blob): Promise<string> {
    return new TextDecoder().decode(await blobToArrayBuffer(this));
  };
}
if (typeof Blob.prototype.stream !== "function") {
  Blob.prototype.stream = function stream(this: Blob): ReadableStream<Uint8Array<ArrayBuffer>> {
    const bytes = blobToArrayBuffer(this);
    return new ReadableStream<Uint8Array<ArrayBuffer>>({
      async start(controller) {
        controller.enqueue(new Uint8Array(await bytes));
        controller.close();
      },
    });
  };
}

// --- fetch with files: keep their names --------------------------------------
// Vitest's jsdom environment hands a jsdom FormData to Node's fetch by copying
// each file into a plain Blob, which drops its name: the part goes out as
// "blob". A browser sends the file's own name. So a body holding files is
// rebuilt as Node's FormData with Node Files first, and the multipart tests
// see what a browser would send.
const NodeFormData = (await new Response(new URLSearchParams("probe=1")).formData())
  .constructor as typeof FormData;
async function withNamedFiles(body: FormData): Promise<FormData> {
  const rebuilt = new NodeFormData();
  for (const [key, value] of body.entries()) {
    if (typeof value === "string") {
      rebuilt.append(key, value);
    } else {
      const bytes = new Uint8Array(await value.arrayBuffer());
      const file = new NodeFile([bytes], value.name, { type: value.type });
      rebuilt.append(key, file as unknown as Blob, value.name);
    }
  }
  return rebuilt;
}

/** Wraps the current fetch (msw's, once the server listens) so files keep their names. */
function keepFileNames(): () => void {
  const inner = globalThis.fetch;
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (init?.body instanceof FormData) {
      return inner(input, { ...init, body: await withNamedFiles(init.body) });
    }
    return inner(input, init);
  };
  return () => {
    globalThis.fetch = inner;
  };
}

// --- MSW server lifecycle (handlers live in tests/msw/) ----------------------

let restoreFetch: () => void = () => undefined;
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  restoreFetch = keepFileNames(); // above msw's fetch, which builds the Request
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => {
  restoreFetch();
  server.close();
});
