# @karni/approvals-ui

React components for the [karni-approvals](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-approvals/README.md) module, composing
`@karni/ui`: the queue a checker decides from, and the badge that says how
much is waiting.

```sh
npm install @karni/approvals-ui
```

```tsx
import { ApprovalsBadge, ApprovalsQueue } from "@karni/approvals-ui";

<nav>
  Approvals <ApprovalsBadge poll={30_000} />
</nav>

<Page title="Approvals">
  <ApprovalsQueue onDecided={() => toast("Recorded")} />
</Page>
```

- `<ApprovalsQueue>` lists `GET /api/pending-changes/` (pending, in the
  user's scope), shows each change's diff, maker, progress and decisions,
  and posts `approve/` or `reject/` with a reason. The backend enforces
  every rule — the maker cannot decide, the role, the scope — and its
  refusal (`APR002`, `APR003`, …) is shown on the item.
- `<ApprovalsBadge>` renders `GET /api/pending-changes/count/`; nothing at
  zero unless `showZero`; `poll` refetches.
- Hooks: `usePendingChanges`, `usePendingCount`, `useDecidePendingChange`
  (invalidates the resource's queries on success).

Peer dependencies: `@karni/ui ^0.1`, React 18/19, `@tanstack/react-query` 5.
Styling uses `@karni/ui`'s tokens only. Both components register their
roles (`approvals-queue`, `approvals-badge`) on `@karni/ui`'s role registry
when it is present.
