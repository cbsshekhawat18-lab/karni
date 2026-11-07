/**
 * A simulated karni_reports backend for the test suite.
 *
 * Default behavior: the report "product-sheet" of row 7 is not cached. The
 * POST answers 202 pending, the status says rendering once and then ready,
 * and the download answers a small PDF. Suites override with
 * `server.use(...)`; `resetMswData()` runs after every test.
 */
import { HttpResponse, http } from "msw";
import type { ReportState } from "../../src/types";

export const API_BASE = "http://localhost/api";
export const REPORT_BASE = `${API_BASE}/reports/product-sheet/7/`;
export const PDF_BYTES = "%PDF-1.4 test";

export function reportState(overrides: Partial<ReportState> = {}): ReportState {
  return {
    id: "r1",
    report: "product-sheet",
    object_id: "7",
    status: "pending",
    url: null,
    size: 0,
    data_version: "abc",
    error: "",
    requested_at: "2026-10-30T10:00:00Z",
    rendered_at: null,
    created_at: "2026-10-30T10:00:00Z",
    ...overrides,
  };
}

export const ready = reportState({
  status: "ready",
  url: "/api/reports/product-sheet/7/download/",
  size: 13,
  rendered_at: "2026-10-30T10:00:02Z",
});

/** What the fake backend received since the last reset. */
export const calls = { requests: 0, statuses: 0, downloads: 0 };

export function resetMswData(): void {
  calls.requests = 0;
  calls.statuses = 0;
  calls.downloads = 0;
}

export const handlers = [
  http.post(REPORT_BASE, () => {
    calls.requests += 1;
    return HttpResponse.json(reportState(), { status: 202 });
  }),
  http.get(`${REPORT_BASE}status/`, () => {
    calls.statuses += 1;
    return HttpResponse.json(calls.statuses < 2 ? reportState({ status: "rendering" }) : ready);
  }),
  http.get(`${REPORT_BASE}download/`, () => {
    calls.downloads += 1;
    return new HttpResponse(PDF_BYTES, {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="product-sheet-7.pdf"',
      },
    });
  }),
];
