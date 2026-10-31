/**
 * Simulated karni_ai backend: `POST /api/ai/extract/` records each body and
 * answers `state.answer` (a preview, or a refusal with `state.status`), and
 * the import's commit marks the job done. `resetMswData()` runs after every test.
 */
import type { ImportJob } from "@karni/ui";
import { HttpResponse, http } from "msw";
import type { ExtractResult } from "../../src/types";

export const API_BASE = "http://localhost/api";

export const jobFixture: ImportJob = {
  id: "3f2b8a4e-1c2d-4e5f-8a9b-0c1d2e3f4a5b",
  model: "catalog.product",
  status: "previewed",
  file_name: "Extracted from text",
  format: "csv",
  columns: ["name", "sku", "price"],
  mapping: { name: "name", sku: "sku", price: "price" },
  rows_total: 2,
  rows_done: 2,
  async: false,
  result: { rows_total: 2, created: 1, updated: 0, unchanged: 0, errors: 1, skipped: 1 },
  problems: [{ row: 3, field: "price", message: "This field is required." }],
  error: null,
  batch: null,
  created_at: "2026-10-31T10:00:00Z",
};

export const extractFixture: ExtractResult = {
  id: jobFixture.id,
  resource: "products",
  source: { kind: "text", label: "text" },
  status: "previewed",
  rows: [
    { name: "Garden hose", sku: "GH-100", price: "19.90", tags: ["outdoor", "water"] },
    { name: "Rake", sku: "RK-200" },
  ],
  problems: [
    { row: 2, field: "price", message: "'abc' is not in the expected form.", source: "schema" },
    { row: 2, field: "price", message: "This field is required.", source: "preview" },
  ],
  result: jobFixture.result,
  commit: `/api/products/import/${jobFixture.id}/commit/`,
  job: jobFixture,
  usage: {
    provider: "test",
    model: "test",
    input_tokens: 120,
    output_tokens: 40,
    cost: "0.000560",
  },
};

export const state: {
  answer: unknown;
  status: number;
  /** JSON bodies as objects; a multipart body as `{ multipart: <raw text> }`. */
  bodies: Array<Record<string, unknown>>;
  commits: number;
  job: ImportJob;
} = { answer: extractFixture, status: 201, bodies: [], commits: 0, job: jobFixture };

export function resetMswData(): void {
  state.answer = extractFixture;
  state.status = 201;
  state.bodies = [];
  state.commits = 0;
  state.job = jobFixture;
}

export const handlers = [
  http.post(`${API_BASE}/ai/extract/`, async ({ request }) => {
    const type = request.headers.get("content-type") ?? "";
    state.bodies.push(
      type.includes("multipart")
        ? { multipart: await request.text() }
        : ((await request.json()) as Record<string, unknown>),
    );
    return HttpResponse.json(state.answer as Record<string, unknown>, { status: state.status });
  }),
  http.post(`${API_BASE}/products/import/:job/commit/`, () => {
    state.commits += 1;
    state.job = { ...jobFixture, status: "done" };
    return HttpResponse.json(state.job);
  }),
  http.get(`${API_BASE}/products/import/:job/`, () => HttpResponse.json(state.job)),
];
