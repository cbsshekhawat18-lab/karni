/**
 * Test harness: a KarniClient whose `fetch` is a scripted fake (no server, no
 * MSW), a fresh QueryClient, and a recording bucket transport.
 */
import { KarniProvider, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import type { BucketRequest, BucketTransport } from "../src/transport";

export const API_BASE = "http://localhost/api";

export interface Call {
  method: string;
  url: string;
  body: unknown;
  accept: string | null;
}

export type Route = (call: Call) => { status?: number; body: unknown } | undefined;

export interface FakeApi {
  calls: Call[];
  fetch: typeof globalThis.fetch;
}

export function fakeApi(route: Route): FakeApi {
  const calls: Call[] = [];
  const fetch: typeof globalThis.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const headers = new Headers(init?.headers);
    const text = typeof init?.body === "string" ? init.body : undefined;
    const call: Call = {
      method: init?.method ?? "GET",
      url,
      body: text !== undefined ? (JSON.parse(text) as unknown) : init?.body,
      accept: headers.get("accept"),
    };
    calls.push(call);
    const answer = route(call) ?? { status: 404, body: { detail: "Not found." } };
    return new Response(JSON.stringify(answer.body), {
      status: answer.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  };
  return { calls, fetch };
}

export interface RecordingTransport {
  requests: BucketRequest[];
  transport: BucketTransport;
}

/** A bucket that accepts everything, reporting progress in two steps. */
export function recordingTransport(fail?: Error): RecordingTransport {
  const requests: BucketRequest[] = [];
  const transport: BucketTransport = async (request) => {
    requests.push(request);
    request.onProgress(50, 100);
    if (fail !== undefined) throw fail;
    request.onProgress(100, 100);
  };
  return { requests, transport };
}

export function renderWithKarni(ui: ReactElement, api: FakeApi): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const client = createKarniClient({ baseUrl: API_BASE, fetch: api.fetch });
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

export const POST_ANSWER = {
  method: "post",
  url: "https://bucket.example.test/",
  fields: {
    key: "protected/products/manuals/ab12/guide.pdf",
    policy: "p",
    "Content-Type": "application/pdf",
  },
  token: "upload-token",
  name: "guide.pdf",
  max_size: 1048576,
  content_types: ["application/pdf"],
  expires_in: 900,
};

export const CONFIRM_ANSWER = {
  token: "confirmed-token",
  name: "guide.pdf",
  size: 7,
  content_type: "application/pdf",
};

/** A file's text (jsdom's File has no text()). */
export function readText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

const fileProperty = { type: "string", format: "binary", nullable: true, "x-karni-storage": {} };

function body(ref: string): Record<string, unknown> {
  return {
    content: {
      "application/json": { schema: { $ref: `#/components/schemas/${ref}` } },
      "multipart/form-data": { schema: { $ref: `#/components/schemas/${ref}` } },
    },
  };
}

function answer(ref: string): Record<string, unknown> {
  return { content: { "application/json": { schema: { $ref: `#/components/schemas/${ref}` } } } };
}

/** The OpenAPI document of a products resource with a protected manual, as Karni emits it. */
export const PRODUCTS_SCHEMA: Record<string, unknown> = {
  openapi: "3.0.3",
  info: { title: "Products", version: "1" },
  "x-karni-auth-mode": "jwt",
  paths: {
    "/api/products/": {
      get: {
        operationId: "products_list",
        "x-karni-resource": "products",
        parameters: [],
        responses: { "200": { ...answer("PaginatedProductList"), description: "" } },
      },
      post: {
        operationId: "products_create",
        requestBody: { ...body("ProductRequest"), required: true },
        responses: { "201": { ...answer("Product"), description: "" } },
      },
    },
    "/api/products/{id}/": {
      get: {
        operationId: "products_retrieve",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "string" } }],
        responses: { "200": { ...answer("Product"), description: "" } },
      },
      patch: {
        operationId: "products_partial_update",
        parameters: [{ name: "id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: body("PatchedProductRequest"),
        responses: { "200": { ...answer("Product"), description: "" } },
      },
    },
  },
  components: {
    schemas: {
      Product: {
        type: "object",
        required: ["id", "name"],
        properties: {
          id: { type: "string", readOnly: true },
          name: { type: "string", maxLength: 100 },
          manual: { type: "string", format: "uri", nullable: true, "x-karni-storage": {} },
        },
      },
      ProductRequest: {
        type: "object",
        required: ["name"],
        properties: {
          name: { type: "string", maxLength: 100, minLength: 1 },
          manual: fileProperty,
        },
      },
      PatchedProductRequest: {
        type: "object",
        properties: {
          name: { type: "string", maxLength: 100, minLength: 1 },
          manual: fileProperty,
        },
      },
      PaginatedProductList: {
        type: "object",
        required: ["count", "results"],
        properties: {
          count: { type: "integer" },
          next: { type: "string", nullable: true },
          previous: { type: "string", nullable: true },
          results: { type: "array", items: { $ref: "#/components/schemas/Product" } },
        },
      },
    },
  },
};
