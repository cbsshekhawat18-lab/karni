# @karni/approvals-ui

React components for the Karni approvals module: ApprovalsQueue and ApprovalsBadge.

[![npm](https://img.shields.io/npm/v/@karni/approvals-ui)](https://www.npmjs.com/package/@karni/approvals-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/modules/#modules-in-this-repository)

It composes `@karni/ui` for the [karni-approvals](https://pypi.org/project/karni-approvals/) module: the queue a checker decides from, and the badge that says how much is waiting.

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
  every rule (the maker cannot decide, the role, the scope), and its
  refusal (`APR002`, `APR003`, …) is shown on the item.
- `<ApprovalsBadge>` renders `GET /api/pending-changes/count/`. It shows
  nothing at zero unless `showZero` is set, and `poll` refetches.
- Hooks: `usePendingChanges`, `usePendingCount`, `useDecidePendingChange`
  (invalidates the resource's queries on success).

Peer dependencies: `@karni/ui` at this package's version (every Karni package is released at one version), React 18/19, `@tanstack/react-query` 5.
Styling uses `@karni/ui`'s tokens only. Both components register their
roles (`approvals-queue`, `approvals-badge`) on `@karni/ui`'s role registry
when it is present.

## Links

- The module in the docs: <https://cbsshekhawat18-lab.github.io/karni/modules/#modules-in-this-repository>
- The Python module: <https://pypi.org/project/karni-approvals/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/approvals-ui is released with every other Karni package, at one version.
