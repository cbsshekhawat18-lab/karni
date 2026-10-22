# karni-approvals

Second-person (maker-checker) approval for high-value changes in a
[Karni](https://github.com/cbsshekhawat18-lab/karni) project. A model opts
in. From then on, a guarded change by anyone (through the API, the admin or
plain code) becomes a **pending change holding the diff instead of a
write**. A checker holding the approve permission applies or rejects it,
with a reason. The maker can never be the checker, in code.

## Install

```sh
pip install karni-approvals
karni add approvals
karni migrate
```

`karni add approvals` adds the dependency, wires `karni_approvals` into the
`# karni:apps` block and records this module's agent guidance. No URL
include is needed: the API rides the auto-router. Keep the Celery worker
running, because notifications and the hourly timeout sweep are tasks.

## Opt a model in

```python
from datetime import timedelta
from karni.models import BaseModel

class Invoice(BaseModel):
    ...
    class Karni:
        requires_approval = ["amount", "status"]   # or True: any change, create and delete too
        approvals_required = 2                      # default KARNI_APPROVALS_REQUIRED (1)
        approver_roles = ["finance"]                # default KARNI_APPROVALS_APPROVER_ROLES ([])
        approval_timeout = timedelta(hours=48)      # or hours as a number; default the setting (never)
        approval_on_timeout = "escalate"            # or "expire" (the default)
        approval_escalation_roles = ["cfo"]         # default KARNI_APPROVALS_ESCALATION_ROLES
```

The model must be a `karni.models.BaseModel` (every `save()` and `delete()`
sends `karni.signals.pre_write`, and that is the hook). `karni check` fails the
build for a guarded model that is not, for a malformed policy, and for
approver roles `KARNI_ROLES` does not declare (`APR007`).

## What happens

- **A guarded write is held.** When a signed-in user changes a guarded
  field (a list) or anything at all (`True`), a `PendingChange` records the
  whole change as `{field: [old, new]}` and the write is stopped before any
  SQL: the API answers **202** with the pending change, the admin shows
  "sent for approval" and returns to the list, and plain code gets
  `karni.exceptions.KarniWriteDeferred` (code `APR001`). The row is not
  touched, and the change is itself history (`karni.audit`).
- **Writes pass through** with no current user (migrations, seeds,
  management commands), inside the module's own apply, and inside
  `karni_approvals.interception.bypass(reason="...")` for trusted code.
  Bulk SQL (`QuerySet.update()`) is never seen. `karni check`'s
  `audited-bulk-write` rule catches it on audited models.
- **Deciding** is `karni_approvals.services.decide(pending, checker, "approve" | "reject", reason)`,
  behind the API (`POST /api/pending-changes/{id}/approve/` and `reject/`)
  and the admin queue. Every rule lives there, so it holds wherever a
  decision comes from:
  - The maker can never be the checker (`APR002`), superuser or not.
  - A checker needs the `karni_approvals.pendingchange:approve` (or
    `:reject`) grant and, when the model declares `approver_roles`, one of
    those roles (`APR003`).
  - A checker sees and decides only pending changes whose row lies inside
    their own scope, which for a branch checker is their branch (`APR003`).
    A create has no row yet and is visible to whoever may view every row of
    that model.
  - One decision per person (`APR004`), and a decided change is final (`APR005`).
  - The change is applied as the last approver once `approvals_required`
    approvals are in (the row's own history then names the checker). It is
    refused as stale when any recorded old value no longer matches
    (`APR006`, status `failed`).
- **Timeouts.** A change past `approval_timeout` is swept hourly. `expire`
  marks it expired, and `escalate` emails the escalation roles and extends it
  by the same timeout.
- **Notifications.** On proposal the checkers are emailed from a Celery task.
  `KARNI_APPROVALS_NOTIFY` is a dotted path called with the pending change.
  `""` switches it off, and you can replace it to post elsewhere.
- **Audit.** `PendingChange` and `Decision` are audited models: every
  proposal, approval and rejection is a `karni.audit` entry with its actor.

## Where it shows

| Surface | What |
| --- | --- |
| Admin → Karni approvals → Pending changes | the queue in the checker's scope, each change's diff and decisions, **Approve selected** / **Reject selected** with a reason |
| `GET /api/pending-changes/` | the queue (filters: `status`, `action`, `content_type`, `maker`), scoped, and makers with an `own` grant see their own |
| `POST /api/pending-changes/{id}/approve/`, `…/reject/` | `{"reason": "..."}` → the updated pending change, or 403 `APR002`/`APR003` and 400 for the rest |
| `GET /api/pending-changes/count/` | `{"pending": n}` the requester may decide (the badge) |
| `@karni/approvals-ui` | `<ApprovalsBadge/>`, `<ApprovalsQueue/>`, `usePendingCount`, `usePendingChanges`, `useDecidePendingChange` |

## Settings

Every setting arrives through the module's settings fragment
(`karni_approvals.conf.DEFAULTS`) and is overridable in the project's
`settings.py` or by its environment variable. Each has a per-model override
in `class Karni`.

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `KARNI_APPROVALS_REQUIRED` | `KARNI_APPROVALS_REQUIRED` | `1` | approvals a change needs |
| `KARNI_APPROVALS_APPROVER_ROLES` | `KARNI_APPROVALS_APPROVER_ROLES` | `[]` | roles that may approve, on top of the grant (`[]` = any holder) |
| `KARNI_APPROVALS_TIMEOUT_HOURS` | `KARNI_APPROVALS_TIMEOUT_HOURS` | `0` | hours before a change times out (`0` = never) |
| `KARNI_APPROVALS_ON_TIMEOUT` | `KARNI_APPROVALS_ON_TIMEOUT` | `expire` | `expire` or `escalate` |
| `KARNI_APPROVALS_ESCALATION_ROLES` | `KARNI_APPROVALS_ESCALATION_ROLES` | `[]` | roles emailed on escalation |
| `KARNI_APPROVALS_NOTIFY` | `KARNI_APPROVALS_NOTIFY` | `karni_approvals.notify.email_checkers` | the notifier (`""` = off) |
| `KARNI_APPROVALS_FROM_EMAIL` | `KARNI_APPROVALS_FROM_EMAIL` | `""` | sender (`""` uses `DEFAULT_FROM_EMAIL`) |

## Escape hatches

- `requires_approval` per model, and every policy knob per model
  (`class Karni`) or project-wide (the settings above).
- `karni_approvals.interception.bypass(reason=...)` for trusted code. No
  current user (`karni.middleware.current_user(None)`) has the same effect.
- `KARNI_APPROVALS_NOTIFY` replaces the notifier, and `notify.checkers_for`
  is the reusable half.
- `services.propose`, `decide`, `apply`, `visible_to`, `sweep` are plain
  functions: call them from your own views, commands or tasks.
- The API viewset and the admin class are ordinary Karni classes: subclass
  `PendingChangeViewSet` (set `auto_register = False` on it) or register
  your own admin for `PendingChange` (explicit registrations win).
- This module ships an explicit `admin.py` (the queue). `Decision` is not
  registered on its own, because it is an inline of the queue.

## Limits

Many-to-many changes are not part of a diff (they are written after
`save()` and never pass through `pre_write`). Hold them behind a guarded
field or a service of your own. A change is held whole: an update touching
a guarded and an unguarded field waits as one.
