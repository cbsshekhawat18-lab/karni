# @karni/impersonation-ui

React pieces for the [karni-impersonation](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-impersonation/README.md) module, composing
`@karni/ui`: the banner a SPA shows while a support user acts as someone
else, and the hooks to start and stop.

```sh
npm install @karni/impersonation-ui
```

```tsx
import { ImpersonationBanner, useStartImpersonation } from "@karni/impersonation-ui";

<AuthProvider>
  <App />
  <ImpersonationBanner onStopped={() => navigate("/")} />
</AuthProvider>;

const start = useStartImpersonation();
start.mutate({ user: "customer@example.com", reason: "ticket #7" });
```

- `<ImpersonationBanner>` reads `GET /api/impersonation-sessions/current/`
  and renders nothing outside a session; inside one it names both
  identities, the minutes left, and **Stop impersonating**, which posts
  `…/stop/`, adopts the impersonator's tokens (JWT mode — through
  `useAuth().adoptTokens`) or re-syncs `/me/` (session mode), and drops every
  cached resource query so the app re-reads as the right person.
- `useStartImpersonation()` does the same in the other direction after
  `POST …/start/` (the backend enforces the permission, the no-escalation
  rule and the reason; its refusal is the mutation's error).
- `useImpersonation()` is the query behind the banner.

Peer dependencies: `@karni/ui ^0.1`, React 18/19, `@tanstack/react-query` 5.
Tokens only; registers the `impersonation-banner` role on `@karni/ui`'s role
registry when it is present.
