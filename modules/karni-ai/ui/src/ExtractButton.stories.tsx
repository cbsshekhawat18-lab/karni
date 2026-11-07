import { KarniProvider, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import type { Meta, StoryObj } from "@storybook/react";
import type { ReactElement } from "react";
import { ExtractButton } from "./ExtractButton";
import type { ExtractResult } from "./types";

/**
 * Stories run against a stubbed KarniClient (the client's injectable `fetch`),
 * so no backend, no model and no MSW worker are needed.
 */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const preview: ExtractResult = {
  id: "3f2b8a4e-1c2d-4e5f-8a9b-0c1d2e3f4a5b",
  resource: "products",
  source: { kind: "url", label: "https://shop.example.com/garden" },
  status: "previewed",
  rows: [
    { name: "Garden hose", sku: "GH-100", price: "19.90", category: "Garden" },
    { name: "Rake", sku: "RK-200", category: "Kitchen" },
  ],
  problems: [
    { row: 2, field: "price", message: "'twelve' is not in the expected form.", source: "schema" },
    {
      row: 2,
      field: "category",
      message: "no category with name 'Kitchen' (or it is not visible to you).",
      source: "preview",
    },
  ],
  result: { rows_total: 2, created: 1, updated: 0, unchanged: 0, errors: 1, skipped: 1 },
  commit: "/api/products/import/3f2b8a4e-1c2d-4e5f-8a9b-0c1d2e3f4a5b/commit/",
  job: {
    id: "3f2b8a4e-1c2d-4e5f-8a9b-0c1d2e3f4a5b",
    model: "catalog.product",
    status: "previewed",
    file_name: "Extracted from https://shop.example.com/garden",
    format: "csv",
    columns: ["name", "sku", "price", "category"],
    mapping: { name: "name", sku: "sku", price: "price", category: "category" },
    rows_total: 2,
    rows_done: 2,
    async: false,
    result: { rows_total: 2, created: 1, updated: 0, unchanged: 0, errors: 1, skipped: 1 },
    problems: [],
    error: null,
    batch: null,
    created_at: "2026-10-31T10:00:00Z",
  },
  usage: { provider: "test", model: "test", input_tokens: 812, output_tokens: 96, cost: null },
};

function withBackend(answer: unknown, status: number): (Story: () => ReactElement) => ReactElement {
  const client = createKarniClient({
    baseUrl: "/api",
    fetch: async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/commit/")) return jsonResponse({ ...preview.job, status: "done" });
      if (url.includes("/import/")) return jsonResponse(preview.job);
      return jsonResponse(answer, status);
    },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Decorator(Story) {
    return (
      <KarniProvider client={client} queryClient={queryClient}>
        <Story />
      </KarniProvider>
    );
  };
}

const meta = {
  title: "AI/ExtractButton",
  component: ExtractButton,
  tags: ["autodocs"],
  args: { resource: "products", resourceLabel: "products" },
} satisfies Meta<typeof ExtractButton>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Any source reads into the preview: proposed rows, problems, counts, then Commit. */
export const Default: Story = { decorators: [withBackend(preview, 201)] };

/** Only a web page. */
export const WebPageOnly: Story = {
  args: { sources: ["url"], children: "Read a page" },
  decorators: [withBackend(preview, 201)],
};

/** A refused address, in the backend's words. */
export const Refused: Story = {
  decorators: [
    withBackend(
      {
        code: "AI011",
        detail: "intranet.example.com resolves to 10.0.0.7, which is not a public address.",
      },
      400,
    ),
  ],
};
