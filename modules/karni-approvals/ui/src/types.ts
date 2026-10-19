/**
 * Shared types for @karni/approvals-ui — the shapes `/api/pending-changes/`
 * serves (karni_approvals.api.PendingChangeSerializer).
 */

export const PENDING_STATUSES = ["pending", "approved", "rejected", "expired", "failed"] as const;
export type PendingStatus = (typeof PENDING_STATUSES)[number];

export type PendingAction = "create" | "update" | "delete";

export interface Person {
  id: string | number;
  email?: string;
}

export interface Decision {
  id: string | number;
  checker: Person | null;
  verdict: "approve" | "reject";
  reason: string;
  created_at: string;
}

export interface PendingChange {
  id: string;
  /** `app_label.model` of the row the change is about. */
  model: string;
  /** Empty for a create. */
  object_id: string;
  action: PendingAction;
  summary: string;
  /** `{ field: [old, new] }` as karni.audit records a diff. */
  changes: Record<string, [unknown, unknown]>;
  maker: Person | null;
  status: PendingStatus;
  required: number;
  approvals: number;
  expires_at: string | null;
  escalated_at: string | null;
  resolved_at: string | null;
  resolved_by: Person | null;
  reason: string;
  decisions: Decision[];
  created_at: string;
  updated_at: string;
}

export interface PendingCount {
  pending: number;
}
