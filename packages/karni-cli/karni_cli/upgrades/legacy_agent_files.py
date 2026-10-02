"""Karni's phase-8 scaffold agent files, frozen verbatim (karni-cli 0.1.0 template).

The upgrade codemod (:mod:`karni_cli.upgrades.agent_guidance`) diffs a
project's files against these to tell Karni's text from the project's own
additions. Never edit them: they are historical records, not guidance.
``PROJECT_NAME`` marks where the template substituted the project name.
"""

from __future__ import annotations

PROJECT_NAME = "<<PROJECT_NAME>>"

#: relative path -> verbatim content of the generated file
LEGACY_FILES: dict[str, str] = {
    "AGENTS.md": (
        "# <<PROJECT_NAME>> — agent guidance\n"
        "\n"
        "This project is built on Karni. Karni already implements everything generic;\n"
        "you write only domain code. Extending Karni is always cheaper than reinventing it.\n"
        "\n"
        "## First action, every session\n"
        "Run `karni context` before reading any files. It prints the current models,\n"
        "viewsets, UI components, hooks and installed modules in ~200 tokens. Trust it.\n"
        "\n"
        "## Never write\n"
        "Auth flows, user models, admin registration, serializers, routers, settings,\n"
        "Docker/Compose config, Celery config, HTML tables, forms, or detail views.\n"
        "Karni provides all of these. If you think you need one, you need an override\n"
        "on an existing Karni base instead.\n"
        "\n"
        "## Always\n"
        "- Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`).\n"
        "- Viewsets inherit `karni.api.BaseViewSet` — usually just `model = X`.\n"
        "- Screens compose `@karni/ui` components (`Page`, `ResourceTable`,\n"
        "  `ResourceForm`, `ResourceDetail`, ...). Never hand-roll a table or form.\n"
        "- Page files stay at 50 lines or fewer (enforced by `karni/max-page-lines`).\n"
        "  Past that you are rebuilding something Karni ships — use the component's props.\n"
        "- After any model change: `make migrate && karni types`.\n"
        "- Run `karni check` before committing — every rule fails the build. Opt-outs\n"
        "  are inline and REQUIRE a reason, e.g. `# karni: allow(raw-sql): <why>`.\n"
        "\n"
        "## Extend, don't fork\n"
        "If an existing component or base class almost fits, extend it through its\n"
        "override props / hooks (`columns`, `fields`, `slots`, `AdminMeta`, `APIMeta`,\n"
        "overridable methods). Do not create a parallel variant.\n"
        "\n"
        "## The stack is fixed\n"
        "Do not introduce a state library, form library, table library, HTTP client or\n"
        "CSS framework beyond what Karni ships (TanStack Query/Table, react-hook-form,\n"
        "Zod, Tailwind, Radix via @karni/ui).\n"
        "\n"
        "## Where code goes\n"
        "- Backend app: `<app>/models.py`, `<app>/viewsets.py` — nothing else per entity.\n"
        "- Frontend pages: `frontend/src/pages/`.\n"
        "- Project slash commands: `.claude/commands/` (/new-model, /new-page,\n"
        "  /add-module, /new-module) encode the standard procedures — prefer them.\n"
        "\n"
        "## Commands\n"
        "- `make up` — start the stack; `make migrate` — makemigrations + migrate\n"
        "- `karni types` — regenerate TS types + typed hooks from the API schema\n"
        "- `karni check` — architecture and system checks; `karni context` — inventory\n"
    ),
    "CLAUDE.md": ("@AGENTS.md\n"),
    ".cursorrules": (
        "Canonical agent rules live in AGENTS.md at the project root. Read AGENTS.md\n"
        "before any work and follow it exactly. Do not duplicate its content here —\n"
        "AGENTS.md is the single source of truth (CLAUDE.md and this file only point\n"
        "to it, so the three can never drift).\n"
    ),
    ".claude/commands/new-model.md": (
        "---\n"
        "description: Add a domain model the Karni way (model + viewset, nothing else)\n"
        "---\n"
        "Add a new domain model: $ARGUMENTS\n"
        "\n"
        "1. Run `karni context` to see existing models and viewsets.\n"
        "2. In the owning app's `models.py`, define the model inheriting\n"
        "   `karni.models.BaseModel` (`SoftDeleteModel` if it needs restore).\n"
        "   Declare `class APIMeta:` / `class AdminMeta:` only for fields that must be\n"
        "   hidden, read-only or write-only. Do NOT write an admin, serializer or router.\n"
        "3. In the same app's `viewsets.py`:\n"
        "   `class XViewSet(BaseViewSet): model = X` (+ `search_fields` if searchable).\n"
        "   The auto-router registers it; admin, filters, schema are derived.\n"
        "4. `make migrate && karni types`\n"
        "5. Verify: `karni context` lists the model and viewset; GET /api/<plural>/ works.\n"
        "\n"
        "Total new code should be well under 20 lines. If it isn't, stop — you are\n"
        "reimplementing something Karni provides.\n"
    ),
    ".claude/commands/new-page.md": (
        "---\n"
        "description: Add a frontend page composing @karni/ui (under 50 lines)\n"
        "---\n"
        "Add a page: $ARGUMENTS\n"
        "\n"
        "1. Run `karni context` for available components, hooks and resources.\n"
        "2. Create one file in `frontend/src/pages/`. Compose @karni/ui — never\n"
        "   hand-roll tables, forms or fetching:\n"
        '   - list screen: `<Page title="..."><ResourceTable resource="..." /></Page>`\n'
        '   - edit/create: `<ResourceForm resource="..." id={...} />`\n'
        '   - read view: `<ResourceDetail resource="..." id={...} />`\n'
        "3. Custom behaviour goes through props (`columns`, `fields`, `rowActions`,\n"
        "   slots, custom cell/field renderers) — extend, never fork a variant.\n"
        "4. Register the route alongside the existing pages.\n"
        "5. The file must stay under 50 lines. Data access only via @karni/ui hooks\n"
        "   (`useResourceList`, `useResourceItem`, `useResourceMutations`, generated\n"
        "   typed hooks from `karni types`).\n"
    ),
    ".claude/commands/add-module.md": (
        "---\n"
        "description: Install an optional Karni module and wire it into settings\n"
        "---\n"
        "Install Karni module: $ARGUMENTS\n"
        "\n"
        "1. Run `karni add <module>` — it adds the `karni-<module>` dependency to\n"
        "   pyproject.toml and wires `karni_<module>` into the INSTALLED_APPS block\n"
        "   marked `# karni:apps` in config/settings.py.\n"
        "2. Rebuild/install: `docker compose build` (or `uv pip install -r\n"
        "   pyproject.toml` in a host venv), then `make migrate`.\n"
        "3. Run `karni context` — the module must appear under MODULES.\n"
        "4. Configure only settings the module documents; do not patch its internals.\n"
    ),
    ".claude/commands/new-module.md": (
        "---\n"
        "description: Create a new local Django app following Karni conventions\n"
        "---\n"
        "Create a local app: $ARGUMENTS\n"
        "\n"
        "1. Run `karni context` first — confirm the domain isn't already covered.\n"
        "2. Create `<app>/` with only: `__init__.py`, `apps.py` (plain AppConfig),\n"
        "   `models.py` (BaseModel subclasses), `viewsets.py` (BaseViewSet subclasses).\n"
        "   No admin.py, serializers.py, urls.py, forms.py — Karni derives all of that.\n"
        "3. Add the app to the `# karni:apps` block in config/settings.py.\n"
        "4. `make migrate && karni types`, then `karni context` to verify.\n"
        "5. Anything reusable across projects belongs in a Karni module\n"
        "   (karni_<name> package), not in this project — say so instead of building it.\n"
    ),
}
