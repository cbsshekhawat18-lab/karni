"""Karni's agent guidance as structured data — the single source of truth.

Every statement the scaffold used to hand-write into ``AGENTS.md`` /
``CLAUDE.md`` / ``.cursorrules`` / slash-command files lives here as a
:class:`Rule` (conventions) or a :class:`Procedure` (step lists). The
``karni`` CLI renders them (``karni rules``), checks files against them
(``karni rules --check``), serves them over MCP (``karni mcp``) and generates
the thin per-tool adapter files from them (``karni rules sync``).

Import-light by contract: stdlib only, no Django, no settings — the CLI reads
this module without a project (guarded by ``tests/agent``).

Code scheme (stable; a code is never reused for a different rule):

* ``K0xx`` workflow — how an agent works in a Karni project
* ``K1xx`` backend — Python/Django conventions
* ``K2xx`` frontend — React/TypeScript conventions
* ``K3xx`` architecture — what to build at all, and where
* project codes (``P001``…) come from the project's ``karni.rules.py``

Severity: ``error`` = enforced, fails the build (``karni check`` or the
``@karni/ui`` ESLint preset; ``enforced_by`` names the underlying rule id);
``must`` = mandatory convention, not machine-checked; ``should`` = strong
default, deviate only with a stated reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["error", "must", "should"]

#: Render order of categories in ``karni rules``.
CATEGORIES: tuple[str, ...] = ("workflow", "architecture", "backend", "frontend")

SEVERITIES: tuple[str, ...] = ("error", "must", "should")


@dataclass(frozen=True)
class Rule:
    code: str
    category: str
    severity: Severity
    #: Terse one-liner for ``karni rules`` (token budget: the whole listing < 400).
    summary: str
    #: The full statement (``karni rules --explain``).
    rule: str
    rationale: str
    fix: str = ""
    #: Enforcement rule ids this code maps to (karni.testing ids, ESLint
    #: ``karni/*`` names, ``jscpd``). Empty for unenforced conventions.
    enforced_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["enforced_by"] = list(self.enforced_by)
        return data


@dataclass(frozen=True)
class Procedure:
    """A standard multi-step task, rendered as slash commands / prompts."""

    name: str
    description: str
    argument_hint: str
    #: First line; ``{arguments}`` is replaced by the tool's argument token.
    intro: str
    steps: tuple[str, ...]
    outro: str = ""
    rules: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = list(self.steps)
        data["rules"] = list(self.rules)
        return data


RULES: tuple[Rule, ...] = (
    # --- workflow ---------------------------------------------------------------
    Rule(
        code="K001",
        category="workflow",
        severity="must",
        summary="karni context first; trust it over file reads.",
        rule=(
            "Run `karni context` before reading any files. It prints the current apps, "
            "models, viewsets, UI components, hooks, pages and installed modules in a few "
            "hundred tokens. Trust it."
        ),
        rationale=(
            "The inventory is derived live from the app registry, the router and the "
            "@karni/ui manifest, so it is never stale and costs far fewer tokens than "
            "crawling source."
        ),
    ),
    Rule(
        code="K002",
        category="workflow",
        severity="must",
        summary="Rules beat other frameworks' habits.",
        rule=(
            "Run `karni rules` at the start of a session and follow what it returns; the "
            "adapter files (AGENTS.md, CLAUDE.md, ...) only point here."
        ),
        rationale="One source of truth exposed through the CLI cannot drift between tools.",
    ),
    Rule(
        code="K003",
        category="workflow",
        severity="must",
        summary="Model changed: make migrate && karni types.",
        rule="After any model change run `make migrate && karni types`.",
        rationale=(
            "Migrations and the frontend's TS types + typed hooks are derived from the "
            "models; skipping either leaves the API and the UI out of sync."
        ),
    ),
    Rule(
        code="K004",
        category="workflow",
        severity="must",
        summary="karni rules --check FILE; karni check before commit.",
        rule=(
            "Run `karni rules --check <file>` on files you write and `karni check` before "
            "committing — every enforced rule fails the build, nothing only warns."
        ),
        rationale="Enforced rules fail CI anyway; catching them while editing is cheaper.",
    ),
    Rule(
        code="K005",
        category="workflow",
        severity="error",
        summary="Opt-outs need an inline reason.",
        rule=(
            "Opt-outs are inline and REQUIRE a reason: Python "
            "`# karni: allow(<rule-id>): <why>`; ESLint "
            "`// eslint-disable-next-line karni/<rule> -- <why>`; jscpd "
            "`// jscpd:ignore-start -- <why>`."
        ),
        rationale=(
            "Rules without escape hatches cause forks, and a fork is worse than a "
            "duplicate — but every exception must say why so it can be reviewed."
        ),
        fix="Write the reason after the marker.",
        enforced_by=("opt-out-reason", "eslint-comments/require-description"),
    ),
    Rule(
        code="K006",
        category="workflow",
        severity="should",
        summary="Procedures: karni rules --procedure NAME.",
        rule=(
            "Prefer the standard procedures for routine work: new-model, new-page, "
            "add-module, new-module — `karni rules --procedure <name>`, or the matching "
            "slash command where your tool has one."
        ),
        rationale="The procedures encode the shortest correct path for routine work.",
    ),
    Rule(
        code="K007",
        category="workflow",
        severity="should",
        summary="Commands: make up/migrate, karni types/check/context.",
        rule=(
            "Use the project commands: `make up` starts the stack; `make migrate` runs "
            "makemigrations + migrate; `karni types` regenerates TS types + typed hooks "
            "from the API schema; `karni check` runs architecture and system checks; "
            "`karni context` prints the inventory."
        ),
        rationale="They run inside the right interpreter (project .venv or compose service).",
    ),
    # --- architecture -----------------------------------------------------------
    Rule(
        code="K301",
        category="architecture",
        severity="must",
        summary="Domain code only; extend Karni, never reinvent.",
        rule=(
            "Karni already implements everything generic; you write only domain code. "
            "Extending Karni is always cheaper than reinventing it."
        ),
        rationale="Generic code written per project is the boilerplate Karni exists to remove.",
    ),
    Rule(
        code="K302",
        category="architecture",
        severity="must",
        summary=(
            "Never write auth, users, admin, serializers, routers, settings, infra, tables, forms."
        ),
        rule=(
            "Never write auth flows, user models, admin registration, serializers, routers, "
            "settings, Docker/Compose config, Celery config, HTML tables, forms, or detail "
            "views. Karni provides all of these. If you think you need one, you need an "
            "override on an existing Karni base instead."
        ),
        rationale="Each of these ships in Karni with tested defaults and override points.",
        fix="Find the Karni base that provides it (`karni context` BASES) and override it.",
    ),
    Rule(
        code="K303",
        category="architecture",
        severity="must",
        summary="Extend via override props/methods; never fork.",
        rule=(
            "If an existing component or base class almost fits, extend it through its "
            "override props / hooks (`columns`, `fields`, `slots`, `AdminMeta`, `APIMeta`, "
            "overridable methods). Do not create a parallel variant."
        ),
        rationale="A forked variant stops receiving fixes and doubles the surface to maintain.",
    ),
    Rule(
        code="K304",
        category="architecture",
        severity="must",
        summary="No extra state/form/table/HTTP/CSS library.",
        rule=(
            "The stack is fixed. Do not introduce a state library, form library, table "
            "library, HTTP client or CSS framework beyond what Karni ships (TanStack "
            "Query/Table, react-hook-form, Zod, Tailwind, Radix via @karni/ui). Backend "
            "HTTP clients are allowed only in services modules (K105)."
        ),
        rationale="Every extra library is a second way to do something Karni already does.",
    ),
    Rule(
        code="K305",
        category="architecture",
        severity="must",
        summary="Per entity: models.py + viewsets.py only.",
        rule=(
            "Backend code per entity goes in `<app>/models.py` and `<app>/viewsets.py` — "
            "nothing else. No admin.py, serializers.py, forms.py; urls.py only for non-API "
            "endpoints such as webhooks (viewsets ride the auto-router)."
        ),
        rationale="Admin, serializers, filters, routes and schema are derived from those two.",
    ),
    Rule(
        code="K306",
        category="architecture",
        severity="must",
        summary="Pages live in frontend/src/pages/.",
        rule=(
            "Frontend pages live in `frontend/src/pages/`, one file per page, with the route "
            "registered alongside the existing pages."
        ),
        rationale="The page cap (K202) and the inventory (`karni context` PAGES) rely on it.",
    ),
    Rule(
        code="K307",
        category="architecture",
        severity="should",
        summary="Cross-project code belongs in a Karni module.",
        rule=(
            "Anything reusable across projects belongs in a Karni module (a `karni_<name>` "
            "package), not in this project — say so instead of building it."
        ),
        rationale="Code that would be written more than once belongs in Karni, never per project.",
    ),
    Rule(
        code="K308",
        category="architecture",
        severity="must",
        summary="Configure modules by documented settings only.",
        rule=(
            "Configure an installed module only through the settings it documents; never "
            "patch its internals."
        ),
        rationale="Patched internals break on the module's next release.",
    ),
    # --- backend ----------------------------------------------------------------
    Rule(
        code="K101",
        category="backend",
        severity="error",
        summary="Models inherit BaseModel or compose its mixins.",
        rule=(
            "Models inherit `karni.models.BaseModel` (= `UUIDModel` + `TimestampedModel` + "
            "`SoftDeleteModel` + `AuditedModel`), or compose those mixins directly when a "
            "model should not have all four (e.g. an append-only log: "
            "`UUIDModel, TimestampedModel`). Declare `APIMeta` / `AdminMeta` only for "
            "fields that must be hidden, read-only or write-only."
        ),
        rationale=(
            "The mixins supply uuid ids, timestamps, soft delete, audit stamping and the "
            "managers the derived API/admin rely on."
        ),
        fix="Inherit karni.models.BaseModel (or compose its mixins).",
        enforced_by=("model-base",),
    ),
    Rule(
        code="K108",
        category="backend",
        severity="must",
        summary="Off-request writes: use current_user(u) for audit stamps.",
        rule=(
            "`AuditedModel` stamps `created_by`/`updated_by` from the current request. "
            "Outside a request (Celery tasks, management commands) nothing is stamped "
            "unless you wrap the writes in `with current_user(user):` from "
            "`karni.middleware`. Never assign `created_by`/`updated_by` by hand."
        ),
        rationale=(
            "One stamping path keeps the audit trail trustworthy under WSGI, ASGI and workers."
        ),
        fix="from karni.middleware import current_user; with current_user(user): ...",
    ),
    Rule(
        code="K102",
        category="backend",
        severity="error",
        summary="Viewsets inherit BaseViewSet (model = X).",
        rule=(
            "Viewsets inherit `karni.api.BaseViewSet` — usually just `model = X` "
            "(+ `search_fields`); the auto-router registers it."
        ),
        rationale="BaseViewSet derives serializer, filters, pagination, permissions and schema.",
        fix="Inherit karni.api.BaseViewSet and set `model = X`.",
        enforced_by=("viewset-base",),
    ),
    Rule(
        code="K103",
        category="backend",
        severity="error",
        summary="No ModelAdmin; use AdminMeta.",
        rule=(
            "Do not register a plain `ModelAdmin`. Declare `AdminMeta` on the model (the "
            "admin is derived), or subclass `karni.admin.KarniModelAdmin`."
        ),
        rationale="The derived admin stays consistent with the model and the API.",
        fix="Delete the admin class and use AdminMeta, or subclass KarniModelAdmin.",
        enforced_by=("admin-convention",),
    ),
    Rule(
        code="K104",
        category="backend",
        severity="error",
        summary="Raw SQL only under */sql/*.",
        rule="No raw SQL (`.raw()`, `cursor.execute()`, `RawSQL`) outside `*/sql/*` or migrations.",
        rationale="Raw SQL bypasses managers (soft delete, owner scoping) and the ORM's safety.",
        fix="Use the ORM, or move the query into a `sql/` module.",
        enforced_by=("raw-sql",),
    ),
    Rule(
        code="K105",
        category="backend",
        severity="error",
        summary="HTTP clients only in */services/*.",
        rule=(
            "Import `requests` / `httpx` / `urllib.request` only in `*/services/*` or "
            "`*/providers/*` modules."
        ),
        rationale="External calls in one layer are mockable, retryable and auditable.",
        fix="Move the call into a services module and call that.",
        enforced_by=("http-client",),
    ),
    Rule(
        code="K106",
        category="backend",
        severity="error",
        summary="No Meta-only ModelSerializer.",
        rule="Never write a Meta-only `ModelSerializer`; `BaseViewSet(model=X)` generates it.",
        rationale="A redundant serializer silently diverges from the generated one.",
        fix="Delete it; customise via APIMeta or override get_serializer_class().",
        enforced_by=("redundant-serializer",),
    ),
    Rule(
        code="K107",
        category="backend",
        severity="error",
        summary="No duplicated code.",
        rule=(
            "No structurally duplicated code (8+ identical statements in two places); reuse "
            "the named Karni API or extract one implementation."
        ),
        rationale="Duplicates are where boilerplate creeps back in.",
        fix="Call the existing implementation instead of copying it.",
        enforced_by=("duplicate",),
    ),
    # --- frontend ---------------------------------------------------------------
    Rule(
        code="K201",
        category="frontend",
        severity="error",
        summary="Compose @karni/ui; no raw table/form/input.",
        rule=(
            "Screens compose `@karni/ui` components (`Page`, `ResourceTable`, "
            "`ResourceForm`, `ResourceDetail`, ...). Never hand-roll a table or form: no raw "
            "`<table>/<form>/<input>/<select>/<textarea>`."
        ),
        rationale="The components already handle data, validation, a11y and theming.",
        fix="Compose ResourceTable / ResourceForm / Input / Select from @karni/ui.",
        enforced_by=("karni/no-raw-elements",),
    ),
    Rule(
        code="K202",
        category="frontend",
        severity="error",
        summary="Pages: max 50 lines.",
        rule=(
            "Page files stay at 50 lines or fewer. Past that you are rebuilding something "
            "Karni ships — use the component's props."
        ),
        rationale="A long page is reimplementing a component.",
        fix="Use the components' props; move logic into hooks.",
        enforced_by=("karni/max-page-lines",),
    ),
    Rule(
        code="K203",
        category="frontend",
        severity="error",
        summary="Import the @karni/ui barrel only.",
        rule="Import only the public `@karni/ui` barrel, never `@karni/ui/dist/*` or `/src/*`.",
        rationale="Internals change without notice; the barrel is the versioned API.",
        fix='Import from "@karni/ui".',
        enforced_by=("karni/no-deep-imports",),
    ),
    Rule(
        code="K204",
        category="frontend",
        severity="error",
        summary="Data only via Karni hooks; no fetch/axios.",
        rule=(
            "Data access only via @karni/ui hooks (`useResourceList`, `useResourceItem`, "
            "`useResourceMutations`, the KarniClient) and the typed hooks generated by "
            "`karni types`. No fetch/axios/XMLHttpRequest/WebSocket outside `src/api/`."
        ),
        rationale="The hooks share caching, auth, errors and query-key invalidation.",
        fix="Use the generated typed hook or useKarniClient().",
        enforced_by=("karni/no-direct-http",),
    ),
    Rule(
        code="K205",
        category="frontend",
        severity="error",
        summary="No duplicated frontend code.",
        rule="No duplicated frontend code above the `frontend/.jscpd.json` threshold.",
        rationale="Duplicates are where boilerplate creeps back in.",
        fix="Extract one component or hook, or compose the existing @karni/ui one.",
        enforced_by=("jscpd",),
    ),
)


PROCEDURES: tuple[Procedure, ...] = (
    Procedure(
        name="new-model",
        description="Add a domain model the Karni way (model + viewset, nothing else)",
        argument_hint="<ModelName> [in <app>] [fields...]",
        intro="Add a new domain model: {arguments}",
        steps=(
            "Run `karni context` to see existing apps, models and viewsets.",
            "In the owning app's `models.py`, define the model inheriting "
            "`karni.models.BaseModel` (or compose its mixins: `UUIDModel`, "
            "`TimestampedModel`, `SoftDeleteModel`, `AuditedModel`). Declare "
            "`class APIMeta:` / `class AdminMeta:` only for fields that must be hidden, "
            "read-only or write-only. Do NOT write an admin, serializer or router.",
            "In the same app's `viewsets.py`: `class XViewSet(BaseViewSet): model = X` "
            "(+ `search_fields` if searchable). The auto-router registers it; admin, "
            "filters, schema are derived.",
            "`make migrate && karni types`",
            "Verify: `karni context` lists the model and viewset; GET /api/<plural>/ works.",
        ),
        outro=(
            "Total new code should be well under 20 lines. If it isn't, stop — you are "
            "reimplementing something Karni provides."
        ),
        rules=("K101", "K102", "K108", "K302", "K305", "K003"),
    ),
    Procedure(
        name="new-page",
        description="Add a frontend page composing @karni/ui (50 lines or fewer)",
        argument_hint="<page purpose> [resource]",
        intro="Add a page: {arguments}",
        steps=(
            "Run `karni context` for available components, hooks, resources and pages.",
            "Create one file in `frontend/src/pages/`. Compose @karni/ui — never hand-roll "
            "tables, forms or fetching: list screen "
            '`<Page title="..."><ResourceTable resource="..." /></Page>`; edit/create '
            '`<ResourceForm resource="..." id={...} />`; read view '
            '`<ResourceDetail resource="..." id={...} />`.',
            "Custom behaviour goes through props (`columns`, `fields`, `rowActions`, slots, "
            "custom cell/field renderers) — extend, never fork a variant.",
            "Register the route alongside the existing pages.",
            "Keep the file at 50 lines or fewer. Data access only via @karni/ui hooks "
            "(`useResourceList`, `useResourceItem`, `useResourceMutations`) and the typed "
            "hooks generated by `karni types`.",
            "`karni rules --check <the page file>` must report no violations.",
        ),
        rules=("K201", "K202", "K204", "K303", "K306"),
    ),
    Procedure(
        name="add-module",
        description="Install an optional Karni module and wire it into settings",
        argument_hint="<module> (e.g. payments)",
        intro="Install Karni module: {arguments}",
        steps=(
            "Run `karni add <module>` — it adds the `karni-<module>` dependency to "
            "pyproject.toml, wires `karni_<module>` into the INSTALLED_APPS block marked "
            "`# karni:apps` in config/settings.py, and (once installed) records the "
            "module's agent guidance.",
            "Rebuild/install: `docker compose build` (or `uv pip install -r pyproject.toml` "
            "in a host venv), then `make migrate`; run `karni add <module>` again if it "
            "asked you to.",
            "Run `karni context` — the module must appear under MODULES; `karni rules` now "
            "includes its guidance.",
            "Configure only settings the module documents; do not patch its internals.",
        ),
        rules=("K308",),
    ),
    Procedure(
        name="new-module",
        description="Create a new local Django app following Karni conventions",
        argument_hint="<app_name>",
        intro="Create a local app: {arguments}",
        steps=(
            "Run `karni context` first — confirm the domain isn't already covered.",
            "Create `<app>/` with only: `__init__.py`, `apps.py` (plain AppConfig), "
            "`models.py` (BaseModel subclasses), `viewsets.py` (BaseViewSet subclasses). "
            "No admin.py, serializers.py, urls.py, forms.py — Karni derives all of that.",
            "Add the app to the `# karni:apps` block in config/settings.py.",
            "`make migrate && karni types`, then `karni context` to verify.",
            "Anything reusable across projects belongs in a Karni module (karni_<name> "
            "package), not in this project — say so instead of building it.",
        ),
        rules=("K305", "K307"),
    ),
)


def rules_by_code() -> dict[str, Rule]:
    return {rule.code: rule for rule in RULES}


def procedures_by_name() -> dict[str, Procedure]:
    return {procedure.name: procedure for procedure in PROCEDURES}


#: Enforcement rule id -> K code, for tools that report the underlying id.
ENFORCEMENT_CODES: dict[str, str] = {
    rule_id: rule.code for rule in RULES for rule_id in rule.enforced_by
}
