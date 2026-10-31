/**
 * Shapes of the karni_ai API (`POST /api/ai/extract/`). Experimental.
 *
 * The extraction answers the import preview of the rows a language model read
 * from a source. Nothing is saved until the import's own commit
 * (`POST /api/<resource>/import/<id>/commit/`).
 */
import type { ImportJob, ImportResult } from "@karni/ui";

/** Experimental. Where the rows were read from. */
export type ExtractSourceKind = "text" | "url" | "pdf";

/** Experimental. What to read: exactly one of the three. */
export type ExtractInput = { text: string } | { url: string } | { file: File };

/**
 * Experimental. One thing wrong with one proposed row. `row` is the row's position in `rows`, from 1.
 * `source` is `schema` (the answer did not fit the field) or `preview` (the import refused it).
 */
export interface ExtractProblem {
  row: number;
  field: string;
  message: string;
  source: "schema" | "preview";
}

/** Experimental. The tokens and cost of the provider call (`cost` null: no price). */
export interface ExtractUsage {
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost: string | null;
}

/** Experimental. The answer of `POST /api/ai/extract/` (201). */
export interface ExtractResult {
  /** The import job's id: commit it to save the rows. */
  id: string;
  resource: string;
  source: { kind: ExtractSourceKind; label: string };
  status: ImportJob["status"];
  /** The proposed rows, field to value, as the preview read them. */
  rows: Array<Record<string, unknown>>;
  problems: ExtractProblem[];
  /** The preview's counts: what the commit will do. */
  result: ImportResult | null;
  /** The import's own commit path, relative to the site. */
  commit: string;
  /** The import job, as `GET /api/<resource>/import/<id>/` answers it. */
  job: ImportJob;
  usage: ExtractUsage;
}

/** Experimental. The body of a refused extraction: an AI code (AI008, AI010...) and why. */
export interface ExtractRefusal {
  code: string;
  detail: string;
}
