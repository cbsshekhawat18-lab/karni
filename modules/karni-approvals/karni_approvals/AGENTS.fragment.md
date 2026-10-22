## Approvals (karni-approvals)
- A model opts in with `class Karni: requires_approval = ["amount", "status"]`
  (or `True` for any change, create and delete included). A guarded change by
  a signed-in user becomes a PendingChange instead of a write: the API answers
  202, the admin says so, and code gets `KarniWriteDeferred`. Never catch it to
  write anyway. Trusted scripts use `karni_approvals.interception.bypass(reason=...)`.
- Decisions only through `karni_approvals.services.decide(pending, checker, verdict, reason)`
  (the API's `/api/pending-changes/{id}/approve/` + `reject/`, the admin queue):
  the maker can never be the checker, checkers need the
  `karni_approvals.pendingchange:approve` grant (+ `approver_roles`), and see
  only rows in their scope. Never write PendingChange/Decision rows by hand.
- Per model: `approvals_required`, `approver_roles`, `approval_timeout`,
  `approval_on_timeout` ("expire"|"escalate"). Project defaults are the
  `KARNI_APPROVALS_*` settings. Notifications and the hourly sweep run in Celery.
- No URL include needed: the API rides the auto-router, and `count/` is the badge.
