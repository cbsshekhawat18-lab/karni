/**
 * Simulated karni_approvals backend for the test suite.
 *
 * `GET /api/pending-changes/` lists `pendingFixtures`, `count/` answers their
 * number, `{id}/approve/` and `{id}/reject/` record the call and answer the
 * fixture as decided. Suites override per-test with `server.use(...)`;
 * `resetMswData()` runs after every test.
 */
import { HttpResponse, http, type PathParams } from "msw";
import type { PendingChange } from "../../src/types";

export const API_BASE = "http://localhost/api";

export const pendingFixtures: PendingChange[] = [
  {
    id: "pc-1",
    model: "shop.invoice",
    object_id: "inv-1",
    action: "update",
    summary: "Invoice INV-1",
    changes: { amount: ["10.00", "20.00"] },
    maker: { id: "u-1", email: "maker@example.com" },
    status: "pending",
    required: 1,
    approvals: 0,
    expires_at: null,
    escalated_at: null,
    resolved_at: null,
    resolved_by: null,
    reason: "",
    decisions: [],
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
  },
  {
    id: "pc-2",
    model: "shop.contract",
    object_id: "",
    action: "create",
    summary: "new contract: Lease",
    changes: { title: [null, "Lease"], value: [null, "1000"] },
    maker: { id: "u-2", email: "other@example.com" },
    status: "pending",
    required: 2,
    approvals: 1,
    expires_at: "2026-10-20T10:00:00Z",
    escalated_at: null,
    resolved_at: null,
    resolved_by: null,
    reason: "",
    decisions: [
      {
        id: "d-1",
        checker: { id: "u-3", email: "first@example.com" },
        verdict: "approve",
        reason: "fine",
        created_at: "2026-10-19T11:00:00Z",
      },
    ],
    created_at: "2026-10-19T10:30:00Z",
    updated_at: "2026-10-19T11:00:00Z",
  },
];

/** `{ id, verdict, body }` of every decision POST received since the last reset. */
export const decisionCalls: Array<{ id: string; verdict: string; body: unknown }> = [];

export function resetMswData(): void {
  decisionCalls.length = 0;
}

function decide(verdict: "approve" | "reject") {
  return async ({ params, request }: { params: PathParams; request: Request }) => {
    const id = String(params["id"]);
    const body: unknown = await request.json();
    decisionCalls.push({ id, verdict, body });
    const found = pendingFixtures.find((item) => item.id === id);
    if (found === undefined) return HttpResponse.json({ detail: "Not found." }, { status: 404 });
    return HttpResponse.json({
      ...found,
      status: verdict === "approve" ? "approved" : "rejected",
      approvals: verdict === "approve" ? found.required : found.approvals,
    });
  };
}

export const handlers = [
  http.get(`${API_BASE}/pending-changes/count/`, () =>
    HttpResponse.json({ pending: pendingFixtures.length }),
  ),
  http.get(`${API_BASE}/pending-changes/`, () =>
    HttpResponse.json({
      count: pendingFixtures.length,
      next: null,
      previous: null,
      results: pendingFixtures,
    }),
  ),
  http.post(`${API_BASE}/pending-changes/:id/approve/`, decide("approve")),
  http.post(`${API_BASE}/pending-changes/:id/reject/`, decide("reject")),
];
