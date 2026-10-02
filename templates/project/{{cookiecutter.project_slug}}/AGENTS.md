# {{ cookiecutter.project_name }} — agent guidance

This project is built on Karni. Karni already implements everything generic;
you write only domain code. Extending Karni is always cheaper than reinventing it.

## First action, every session
Run `karni context` before reading any files. It prints the current models,
viewsets, UI components, hooks and installed modules in ~200 tokens. Trust it.

## Never write
Auth flows, user models, admin registration, serializers, routers, settings,
Docker/Compose config, Celery config, HTML tables, forms, or detail views.
Karni provides all of these. If you think you need one, you need an override
on an existing Karni base instead.

## Always
- Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`).
- Viewsets inherit `karni.api.BaseViewSet` — usually just `model = X`.
- Screens compose `@karni/ui` components (`Page`, `ResourceTable`,
  `ResourceForm`, `ResourceDetail`, ...). Never hand-roll a table or form.
- Page files stay at 50 lines or fewer (enforced by `karni/max-page-lines`).
  Past that you are rebuilding something Karni ships — use the component's props.
- After any model change: `make migrate && karni types`.
- Run `karni check` before committing — every rule fails the build. Opt-outs
  are inline and REQUIRE a reason, e.g. `# karni: allow(raw-sql): <why>`.

## Extend, don't fork
If an existing component or base class almost fits, extend it through its
override props / hooks (`columns`, `fields`, `slots`, `AdminMeta`, `APIMeta`,
overridable methods). Do not create a parallel variant.

## The stack is fixed
Do not introduce a state library, form library, table library, HTTP client or
CSS framework beyond what Karni ships (TanStack Query/Table, react-hook-form,
Zod, Tailwind, Radix via @karni/ui).

## Where code goes
- Backend app: `<app>/models.py`, `<app>/viewsets.py` — nothing else per entity.
- Frontend pages: `frontend/src/pages/`.
- Project slash commands: `.claude/commands/` (/new-model, /new-page,
  /add-module, /new-module) encode the standard procedures — prefer them.

## Commands
- `make up` — start the stack; `make migrate` — makemigrations + migrate
- `karni types` — regenerate TS types + typed hooks from the API schema
- `karni check` — architecture and system checks; `karni context` — inventory
