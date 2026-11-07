# @karni/impersonation-ui

React components for the Karni impersonation module: ImpersonationBanner and its hook.

[![npm](https://img.shields.io/npm/v/@karni/impersonation-ui)](https://www.npmjs.com/package/@karni/impersonation-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/modules/#modules-in-this-repository)

It composes `@karni/ui` for the [karni-impersonation](https://pypi.org/project/karni-impersonation/) module: the banner a single-page app shows while a support user acts as someone else, and the hooks to start and stop.

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
  and renders nothing outside a session. Inside one it names both
  identities, the minutes left, and **Stop impersonating**. That button posts
  `…/stop/`, adopts the impersonator's tokens (JWT mode, through
  `useAuth().adoptTokens`) or re-syncs `/me/` (session mode), and drops every
  cached resource query so the app re-reads as the right person.
- `useStartImpersonation()` does the same in the other direction after
  `POST …/start/` (the backend enforces the permission, the no-escalation
  rule and the reason, and its refusal is the mutation's error).
- `useImpersonation()` is the query behind the banner.

Peer dependencies: `@karni/ui` at this package's version (every Karni package is released at one version), React 18/19, `@tanstack/react-query` 5.
It uses tokens only, and registers the `impersonation-banner` role on `@karni/ui`'s role
registry when it is present.

## Links

- The module in the docs: <https://cbsshekhawat18-lab.github.io/karni/modules/#modules-in-this-repository>
- The Python module: <https://pypi.org/project/karni-impersonation/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/impersonation-ui is released with every other Karni package, at one version.
