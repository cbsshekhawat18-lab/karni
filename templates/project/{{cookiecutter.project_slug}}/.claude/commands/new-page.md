---
description: Add a frontend page composing @karni/ui (under 50 lines)
---
Add a page: $ARGUMENTS

1. Run `karni context` for available components, hooks and resources.
2. Create one file in `frontend/src/pages/`. Compose @karni/ui — never
   hand-roll tables, forms or fetching:
   - list screen: `<Page title="..."><ResourceTable resource="..." /></Page>`
   - edit/create: `<ResourceForm resource="..." id={...} />`
   - read view: `<ResourceDetail resource="..." id={...} />`
3. Custom behaviour goes through props (`columns`, `fields`, `rowActions`,
   slots, custom cell/field renderers) — extend, never fork a variant.
4. Register the route alongside the existing pages.
5. The file must stay under 50 lines. Data access only via @karni/ui hooks
   (`useResourceList`, `useResourceItem`, `useResourceMutations`, generated
   typed hooks from `karni types`).
