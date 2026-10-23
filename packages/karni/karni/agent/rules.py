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

#: Values ``Rule.when`` may take. ``history``: a history provider detects a
#: prompt-history store for the project (:mod:`karni.agent.history`).
CONDITIONS: tuple[str, ...] = ("history",)


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
    #: Emitted only when this condition holds for the project (one of
    #: ``CONDITIONS``); empty = always. Evaluated by :func:`karni.agent.dump`.
    when: str = ""

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
    # workflow
    Rule(
        code="K001",
        category="workflow",
        severity="must",
        summary="karni context first. Trust it.",
        rule=(
            "Run `karni context` before reading any files. It prints the current apps, "
            "models, viewsets, UI components, hooks, pages, public site routes and installed "
            "modules in a few hundred tokens. Trust it."
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
            "Run `karni rules` at the start of a session and follow what it returns. The adapter "
            "files (AGENTS.md, CLAUDE.md, ...) only point here."
        ),
        rationale="One source of truth exposed through the CLI cannot drift between tools.",
    ),
    Rule(
        code="K003",
        category="workflow",
        severity="must",
        summary="Model changed: make migrate, then karni types.",
        rule="After any model change run `make migrate && karni types`.",
        rationale=(
            "Migrations and the frontend's TS types + typed hooks are derived from the models. "
            "Skipping either leaves the API and the UI out of sync."
        ),
    ),
    Rule(
        code="K004",
        category="workflow",
        severity="must",
        summary="karni rules --check FILE, then karni check pre-commit.",
        rule=(
            "Run `karni rules --check <file>` on files you write and `karni check` before "
            "committing. Every enforced rule fails the build, and nothing only warns."
        ),
        rationale="Enforced rules fail CI anyway, so catching them while editing is cheaper.",
    ),
    Rule(
        code="K005",
        category="workflow",
        severity="error",
        summary="Opt-outs need an inline reason.",
        rule=(
            "Opt-outs are inline and REQUIRE a reason. Python: "
            "`# karni: allow(<rule-id>): <why>`. ESLint: "
            "`// eslint-disable-next-line karni/<rule> -- <why>`. jscpd: "
            "`// jscpd:ignore-start -- <why>`."
        ),
        rationale=(
            "Rules without escape hatches cause forks, and a fork is worse than a duplicate. "
            "Every exception must still say why, so it can be reviewed."
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
            "Prefer the standard procedures for routine work: new-model, new-page, add-module, "
            "new-module. Run one with `karni rules --procedure <name>`, or with the matching "
            "slash command where your tool has one."
        ),
        rationale="The procedures encode the shortest correct path for routine work.",
    ),
    Rule(
        code="K007",
        category="workflow",
        severity="should",
        summary="Commands: karni --help.",
        rule=(
            "Use the project commands (`karni --help` lists them all). `make up` starts the "
            "stack. `make migrate` runs makemigrations + migrate. `karni types` regenerates TS "
            "types + typed hooks from the API schema. `karni check` runs architecture and system "
            "checks. `karni context` prints the inventory. `karni make <type>` scaffolds. Runners "
            "like `karni test`, `karni shell`, `karni routes`, `karni worker`, "
            "`karni schedule list` wrap manage.py/celery/pytest."
        ),
        rationale="They run inside the right interpreter (project .venv or compose service).",
    ),
    Rule(
        code="K008",
        category="workflow",
        severity="must",
        summary="Before editing a file: karni context --with-history FILE.",
        rule=(
            "This project keeps a prompt-history store. Before editing a file that already "
            "has history, run `karni context --with-history <file>` and read its HISTORY "
            "section, so you do not redo a decision that was already made and reverted."
        ),
        rationale=(
            "The inventory shows what the code contains now. The history provider shows what was "
            "already asked, decided and abandoned for that file."
        ),
        when="history",
    ),
    Rule(
        code="K009",
        category="workflow",
        severity="must",
        summary="Scaffold with karni make.",
        rule=(
            "Create apps, models, viewsets, serializers, migrations, tasks, schedules, events, "
            "listeners, management commands, services, middleware, pages, components, modules, "
            "site apps and their views with `karni make <type>` (`karni make --list` lists the "
            "types, `--dry-run` previews, "
            "`--help` works per type). Never hand-create a file, class or route a generator "
            "makes. Run the generator, then edit what it wrote."
        ),
        rationale=(
            "Generators emit the conventions in one step (BaseModel, a mandatory access "
            "declaration, settings and route markers, ruff-clean imports) and are tested to pass "
            "every rule. Hand-written scaffolding drifts."
        ),
        fix="Delete the hand-written scaffold and run the matching `karni make` command.",
    ),
    # --- debugging: karni why (access decisions) ------------------------------
    Rule(
        code="K015",
        category="workflow",
        severity="must",
        summary="Row/field/action missing or refused: karni why first.",
        rule=(
            "When a row, field or action is unexpectedly missing or refused (a 403, a 404, an "
            "empty list, a field absent from a response), run `karni why <resource>/<id> --as "
            "<user> [--action ...]`, `karni why <resource>.<field> --as <user>`, `karni why-empty "
            "<resource> --as <user>` or `karni why 403 <request-id>` (MCP: `why`, `why_empty`) "
            "before reading viewsets, KARNI_ROLES or the access layer, and act on its verdict."
        ),
        rationale=(
            "Access bugs raise no error: the row is just absent. karni why computes the decision "
            "with the code that enforces it and prints the user's roles, the grants and where "
            "each comes from, the predicate that decided, the row's values, file:line and the "
            "fix. That is one call instead of reconstructing the rules from source."
        ),
        fix="Run the matching `karni why` command and apply the fix it prints.",
    ),
    # --- end debugging ----------------------------------------------------------
    # workflow: debugging (karni explain -, karni queries)
    Rule(
        code="K013",
        category="workflow",
        severity="must",
        summary="Traceback: karni explain - first.",
        rule=(
            "Paste a traceback, a test failure or a log line into `karni explain -` (stdin, or "
            "the MCP tool `explain_text`) before reading it by hand. It names the Karni failure "
            "class, the cause, where (the first project frame, file:line), the fix and the docs "
            "link, and says plainly when it does not recognise the failure."
        ),
        rationale=(
            "Rebuilding context from a traceback is the expensive part of debugging. The "
            "catalogue already knows Karni's failure classes (codes, query budgets, access "
            "outcomes, database, migrations, settings, CSRF/CORS) and their fixes."
        ),
    ),
    Rule(
        code="K014",
        category="workflow",
        severity="must",
        summary="N+1: karni queries URL --as USER first.",
        rule=(
            "Before hunting an N+1 in serializers, run `karni queries <endpoint> --as <user>` "
            "(MCP tool `queries`). It runs the endpoint in-process, groups the repeated queries "
            "by the serializer field and relation that caused them, says why the optimiser did "
            "not fetch them and prints the hint that fixes it."
        ),
        rationale=(
            "The optimiser derives select_related/prefetch_related itself and records what it "
            "cannot see (method fields, properties, to_representation), so the cause and the "
            "fix come from the same knowledge instead of guesswork."
        ),
    ),
    # architecture
    Rule(
        code="K301",
        category="architecture",
        severity="must",
        summary="Domain code only. Extend Karni.",
        rule=(
            "Karni already implements everything generic. You write only domain code. Extending "
            "Karni is always cheaper than reinventing it."
        ),
        rationale="Generic code written per project is the boilerplate Karni exists to remove.",
    ),
    Rule(
        code="K302",
        category="architecture",
        severity="must",
        summary=(
            "Never write auth, admin, serializers, routers, settings, infra, or app-screen "
            "tables and forms."
        ),
        rule=(
            "Never write auth flows, user models, admin registration, serializers, routers, "
            "settings, Docker/Compose config, Celery config, HTML tables, forms, or detail "
            "views. Karni provides all of these. If you think you need one, you need an "
            "override on an existing Karni base instead. The tables, forms and detail views "
            "meant here are app screens. A public server-rendered site (K309) is the one place "
            "for hand-written HTML pages, and its forms still post to a BaseViewSet."
        ),
        rationale=(
            "Each of these ships in Karni with tested defaults and override points. A public "
            "site is the client's own markup, so it has its own rule."
        ),
        fix="Find the Karni base that provides it (`karni context` BASES) and override it.",
    ),
    Rule(
        code="K303",
        category="architecture",
        severity="must",
        summary="Extend via props/methods, never fork.",
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
        summary="Per entity: models.py and viewsets.py.",
        rule=(
            "Backend code per entity goes in `<app>/models.py` and `<app>/viewsets.py`, nothing "
            "else. No admin.py, serializers.py or forms.py. urls.py is only for non-API endpoints "
            "such as webhooks and a public site's pages (K309), because viewsets ride the "
            "auto-router."
        ),
        rationale="Admin, serializers, filters, routes and schema are derived from those two.",
    ),
    Rule(
        code="K306",
        category="architecture",
        severity="must",
        summary="App pages: frontend/src/pages/. Public site pages: K309.",
        rule=(
            "App screens (the React frontend) live in `frontend/src/pages/`, one file per page, "
            "with the route registered alongside the existing pages. Public server-rendered "
            "pages do not go there (K309)."
        ),
        rationale="The page cap (K202) and the inventory (`karni context` PAGES) rely on it.",
    ),
    Rule(
        code="K307",
        category="architecture",
        severity="should",
        summary="Cross-project code: a Karni module.",
        rule=(
            "Anything reusable across projects belongs in a Karni module (a `karni_<name>` "
            "package), not in this project. Say so instead of building it."
        ),
        rationale="Code that would be written more than once belongs in Karni, never per project.",
    ),
    Rule(
        code="K308",
        category="architecture",
        severity="must",
        summary="Modules: configure via settings.",
        rule=(
            "Configure an installed module only through the settings it documents. Never patch "
            "its internals."
        ),
        rationale="Patched internals break on the module's next release.",
    ),
    Rule(
        code="K309",
        category="architecture",
        severity="must",
        summary="Public site: a site app with Django views and templates.",
        rule=(
            "A public, server-rendered website (SEO-indexed pages in the client's own HTML and "
            "CSS) is a site app, not React pages. `karni make site <app>` creates it: function "
            "views in `<app>/views.py`, `<app>/urls.py` with `app_name`, included at "
            '`path("", ...)` in config/urls.py (which replaces the welcome page), templates in '
            "`<app>/templates/<app>/` and the site's CSS and JS in `<app>/static/<app>/`. "
            "`karni make view <name> --app <app>` adds a page. Views read content through each "
            "model's default manager (`Model.objects`, so model scopes apply and soft-deleted "
            "rows stay hidden) and filter drafts themselves. A public form posts to a "
            "`BaseViewSet` declared `Access(read=..., write=..., create=Public())` and sends "
            "the CSRF token, never to a hand-written form view. The React rules (K201, K202, "
            "K206) apply to app screens only."
        ),
        rationale=(
            "A marketing site must be crawlable and faithful to the client's design, which the "
            "app-screen rules forbid for good reason. One Django app with plain views keeps the "
            "API, the admin and the access layer as the only write path."
        ),
        fix=(
            "Run `karni make site <app>`, then `karni make view <name> --app <app>` per page. "
            "Karni's docs page public-site covers SEO and public forms."
        ),
    ),
    # backend
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
        summary="Off-request writes: current_user(u).",
        rule=(
            "`AuditedModel` stamps `created_by`/`updated_by` from the current request. "
            "Outside a request (Celery tasks, management commands) nothing is stamped "
            "unless you wrap the writes in `with current_user(user):` from "
            "`karni.middleware`. Never assign `created_by`/`updated_by` by hand."
        ),
        rationale=(
            "One stamping path keeps the audit trail trustworthy under WSGI, ASGI and workers."
        ),
        fix=(
            "Import current_user from karni.middleware and wrap the writes in "
            "`with current_user(user): ...`."
        ),
    ),
    Rule(
        code="K102",
        category="backend",
        severity="error",
        summary="Viewsets inherit BaseViewSet.",
        rule=(
            "Viewsets inherit `karni.api.BaseViewSet`, usually just `model = X` plus its `access` "
            "declaration (K109) (+ `search_fields`). The auto-router registers it."
        ),
        rationale="BaseViewSet derives serializer, filters, pagination, permissions and schema.",
        fix="Inherit karni.api.BaseViewSet and set `model = X`.",
        enforced_by=("viewset-base",),
    ),
    Rule(
        code="K109",
        category="backend",
        severity="error",
        summary="Viewsets declare access.",
        rule=(
            "Every `BaseViewSet` declares `access`: `Granted()` (the default: the roles' grants "
            "for the model, row-scoped) or `Access(read=..., write=...)` built from "
            '`Owned("<fk to user>")`, `HasRole(...)`, `Authenticated()`, `Public()` and '
            "`Where(lambda request: Q(...))` with `|` / `&`. Reads are public only when you write "
            "`Public()`. No `access` denies every request. `Unscoped(reason=...)` is the explicit "
            "opt-out."
        ),
        rationale=(
            "One declaration compiles into both the request gate and the row filter, so neither "
            "can be forgotten. A forgotten permission class fails open silently."
        ),
        fix="Add `access = Granted()` (or `Access(read=..., write=...)` for a custom rule).",
        enforced_by=("viewset-access",),
    ),
    Rule(
        code="K110",
        category="backend",
        severity="error",
        summary="Row rules: in access.",
        rule=(
            "Express who sees which rows in `access` (`Where(...)` for custom logic, "
            "`@action(..., access=...)` for one action). An overridden `get_queryset` is still "
            "read-scoped, so never use it to widen. Overriding `filter_queryset_for_user` needs "
            "`# karni: allow(access-override): <why>`."
        ),
        rationale=(
            "The queryset is the authoritative layer: lists, details, actions, relation "
            "PKs and ?expand= all go through the read scope, so a bypass leaks everywhere."
        ),
        fix="Move the condition into access (Where(lambda request: Q(...))), or add the marker.",
        enforced_by=("access-override",),
    ),
    Rule(
        code="K111",
        category="backend",
        severity="error",
        summary="Paginate lists. No N+1.",
        rule=(
            "Lists stay bounded and flat. A list-returning `@action` returns "
            "`self.paginated_response(queryset)`, never `Serializer(qs, many=True).data`. "
            "`pagination_class = None` needs `pagination = Unpaginated(max_rows=N, reason=...)`. "
            "Query counts must not grow with rows: BaseViewSet derives "
            "select_related/prefetch_related from the serializer, so hint only what it cannot see "
            "(SerializerMethodField, properties) with `select_related = [...]` / "
            "`prefetch_related = [...]` on the viewset. Raise a budget only with "
            "`query_budget = Budget(list=N, reason=...)`."
        ),
        rationale=(
            "An unpaginated list or an N+1 passes with test data and falls over with real data. "
            "The scaling check (2 vs 12 rows) and per-action query budgets catch both in CI."
        ),
        fix="Return self.paginated_response(qs) and hint opaque fields with prefetch_related.",
        enforced_by=("unpaginated-action", "query-scaling"),
    ),
    Rule(
        code="K113",
        category="backend",
        severity="error",
        summary="Audited models: no update()/bulk_update().",
        rule=(
            "A model with `class Karni: audit = True` keeps field-level change history through "
            "save() and delete(). `QuerySet.update()` and `bulk_update()` bypass it and leave no "
            "entry. Save the instances instead, or opt out with "
            "`# karni: allow(audited-bulk-write): <reason>`."
        ),
        rationale=(
            "A silent gap in the history is exactly the bug someone discovers during an audit. "
            "The rule names every bulk write on an audited model at build time."
        ),
        fix="Loop and save(), or add the allow marker with the reason.",
        enforced_by=("audited-bulk-write",),
    ),
    Rule(
        code="K114",
        category="backend",
        severity="must",
        summary="Money: MoneyField, never float.",
        rule=(
            "Declare what a value is with `karni.fields` so the database enforces it: money is "
            '`MoneyField(currency="EUR")` or `currency_field=...` (never FloatField: '
            "`karni.E960` fails boot), counts that must never go negative are "
            "`QuantityField`, rates `PercentField`, ISO codes `CountryField`/`CurrencyField`, "
            "phone numbers `PhoneField`, emails `EmailField(unique=True)` (case-insensitive). "
            "Uniqueness on soft-deletable models: `unique=True` on a Karni field, or "
            "`LiveUniqueConstraint(fields=[...])` in `Meta.constraints`, so a deleted row frees "
            "its value. Pick `on_delete` deliberately (`karni.W965` flags CASCADE on financial "
            "or audited models). `karni schema <app>` shows every column, constraint and index "
            "and why it exists."
        ),
        rationale=(
            "Float money, free-text codes and case-sensitive unique emails pass every test and "
            "fail in production. A database constraint is the one layer raw SQL, bulk updates and "
            "other services cannot skip."
        ),
        fix=(
            "karni make model Product price:money:EUR stock:quantity country:country "
            "email:email:unique (field types: karni make model --help)."
        ),
    ),
    # lifecycle and limited resources (karni.fields, karni.capacity, karni.constraints)
    Rule(
        code="K115",
        category="backend",
        severity="must",
        summary="Status column: StateField + transitions.",
        rule=(
            "A lifecycle column (status, state, stage) is "
            "`karni.fields.StateField(states=[...], transitions={...})`, never a free or choices "
            '`CharField`. Move it with `row.transition("status", "confirmed")` (or assign and '
            "`save()`), never with `QuerySet.update()`. The column CHECKs the declared states. An "
            "illegal move is E980 (a 400), a concurrent one E981 (a 409)."
        ),
        rationale=(
            "A free status column takes any value in any order from any code path. Tests pass and "
            "production rows end up refunded without ever being paid."
        ),
        fix=(
            "status = StateField(states=[...], transitions={...}), or generate it: karni make "
            "model ... 'status:state:draft>confirmed|draft>cancelled'."
        ),
    ),
    Rule(
        code="K116",
        category="backend",
        severity="must",
        summary="Stock/slots: reserve(), no_overlap. No check-then-write.",
        rule=(
            "Anything with a limited quantity (seats, stock, licences) is a `CapacityField` "
            "consumed only with `karni.capacity.reserve(row, n)` / `release()` inside "
            "`transaction.atomic()`. Anything that must not overlap in time (rooms, slots, "
            "appointments) declares "
            '`class Karni: no_overlap = NoOverlap("<resource>", "<range>", ignore={...})`. Never '
            "count, compare and then write in Python."
        ),
        rationale=(
            "A read-then-write check never fails in tests and double-books in production: two "
            "requests pass it together. The database refuses the oversell or the overlap "
            "(CHECK, EXCLUDE) and Karni names it (E985 / E984, a 409)."
        ),
        fix=(
            "Inside with transaction.atomic(), call reserve(tier, n), then create the booking. "
            "Slots: no_overlap = NoOverlap('room', 'during', ignore={'status': ['cancelled']})."
        ),
    ),
    Rule(
        code="K103",
        category="backend",
        severity="error",
        summary="No ModelAdmin. Use AdminMeta.",
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
        rule="Never write a Meta-only `ModelSerializer`. `BaseViewSet(model=X)` generates it.",
        rationale="A redundant serializer silently diverges from the generated one.",
        fix="Delete it. Customise via APIMeta or override get_serializer_class().",
        enforced_by=("redundant-serializer",),
    ),
    Rule(
        code="K107",
        category="backend",
        severity="error",
        summary="No duplicated code.",
        rule=(
            "No structurally duplicated code (8+ identical statements in two places). Reuse the "
            "named Karni API or extract one implementation."
        ),
        rationale="Duplicates are where boilerplate creeps back in.",
        fix="Call the existing implementation instead of copying it.",
        enforced_by=("duplicate",),
    ),
    # frontend
    Rule(
        code="K201",
        category="frontend",
        severity="error",
        summary="Compose @karni/ui. No raw table/form/input.",
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
            "Page files stay at 50 lines or fewer. Past that you are rebuilding something Karni "
            "ships, so use the component's props."
        ),
        rationale="A long page is reimplementing a component.",
        fix="Use the components' props and move logic into hooks.",
        enforced_by=("karni/max-page-lines",),
    ),
    Rule(
        code="K203",
        category="frontend",
        severity="error",
        summary="Import only the @karni/ui barrel.",
        rule="Import only the public `@karni/ui` barrel, never `@karni/ui/dist/*` or `/src/*`.",
        rationale="Internals change without notice. The barrel is the versioned API.",
        fix='Import from "@karni/ui".',
        enforced_by=("karni/no-deep-imports",),
    ),
    Rule(
        code="K204",
        category="frontend",
        severity="error",
        summary="Data only via Karni hooks. No fetch/axios.",
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
    # workflow: debugging with the development capture (karni trace / replay /
    # explain --failure; docs/debugging/trace-and-replay.md)
    Rule(
        code="K030",
        category="workflow",
        severity="should",
        summary="A failure: karni explain --failure first.",
        rule=(
            "When a request or task fails in development, run `karni explain --failure <id>` "
            "(or `--failure last`) before reading a traceback by hand: it names the failing "
            "frame with its locals, the user and their roles, the SQL and the next steps."
        ),
        rationale=(
            "The snapshot was taken when it failed, with secrets redacted. Reconstructing the "
            "same context from a traceback and the code costs far more."
        ),
    ),
    Rule(
        code="K031",
        category="workflow",
        severity="should",
        summary="Follow a request: karni trace ID.",
        rule=(
            "To see what a request set in motion (Celery tasks and their retries, email, "
            "webhooks, change-log entries) run `karni trace <request-id>` (its X-Request-ID "
            "response header, or `last`) instead of correlating log timestamps."
        ),
        rationale=(
            "The request's tasks, retries, email and audit entries all carry its id, so the trace "
            "is exact. Timestamps from several processes are not."
        ),
    ),
    Rule(
        code="K032",
        category="workflow",
        severity="should",
        summary="Confirm a fix: karni replay ID --as USER.",
        rule=(
            "After changing access, roles or fixing a bug a request hit, confirm it with "
            "`karni replay <request-id> [--as <email|username|pk>]`. It re-runs the captured "
            'request against the current code and prints what changed ("was 403, now 200"). '
            "Writes are rolled back unless you pass `--commit`."
        ),
        rationale=(
            "Replaying the real request as the real user tests the case that failed, not "
            "the one you think failed."
        ),
    ),
    Rule(
        code="K206",
        category="frontend",
        severity="error",
        summary="Style with token classes. No literal values.",
        rule=(
            "Style with the @karni/ui preset's classes (`bg-primary`, `p-4`, `rounded-md`, "
            "`z-popover`), which read `--karni-*` tokens. No arbitrary literals (`w-[13px]`, "
            "`bg-[#fff]`), palette colours (`bg-slate-500`) or literal inline styles. It fails "
            "the build where the project enables `karni/no-style-literals`."
        ),
        rationale="One stylesheet (or `karni ui detect`) then rethemes every screen.",
        fix="Use a preset class, or add the token to the project's karni-theme.css.",
        enforced_by=("karni/no-style-literals",),
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
            "`karni make model <Name> <field:type ...> --with viewset --access <who> "
            "[--search f1,f2] [--app <app>]` writes the model on `karni.models.BaseModel` and "
            "its viewset (`-a` also adds list/detail/form pages). Field types: "
            "`karni make model --help`. `--access`: authenticated (default), public-read, "
            "owned:<fk to user>, staff, role:<name>. Edit the generated `access` for anything "
            "richer (`Owned(...) | HasRole(...)`, `Where(...)`). Do NOT write an admin, "
            "serializer or router. The auto-router registers it, and the admin, filters and "
            "schema are derived.",
            "Add `class APIMeta:` / `class AdminMeta:` only for fields that must be hidden, "
            "read-only or write-only.",
            "`karni make migration && karni migrate && karni types`",
            "Verify: `karni context` lists the model and viewset, and GET /api/<plural>/ works "
            "for a caller `access` admits and is refused (401/403) or empty for one it does not.",
        ),
        outro=(
            "Total new code should be well under 20 lines. If it isn't, stop: you are "
            "reimplementing something Karni provides."
        ),
        rules=(
            "K009",
            "K101",
            "K102",
            "K109",
            "K114",
            "K108",
            "K115",
            "K116",
            "K302",
            "K305",
            "K003",
        ),
    ),
    Procedure(
        name="new-page",
        description="Add a frontend page composing @karni/ui (50 lines or fewer)",
        argument_hint="<page purpose> [resource]",
        intro="Add a page: {arguments}",
        steps=(
            "Run `karni context` for available components, hooks, resources and pages.",
            "`karni make page <name> --resource <resource> --kind list|detail|form` writes "
            "`frontend/src/pages/<name>.tsx` composing @karni/ui and does the rest a person "
            "would do by hand: register the route alongside the existing pages "
            "(frontend/src/routes.tsx). Without `--resource` it is a bare `<Page>`. Never "
            "hand-roll tables, forms or fetching. A page of the public server-rendered site is "
            "not an app screen: `karni make view <name> --app <site app>` (K309).",
            "Custom behaviour goes through props (`columns`, `fields`, `rowActions`, slots, "
            "custom cell/field renderers). Extend, never fork a variant.",
            "Keep the file at 50 lines or fewer. Data access only via @karni/ui hooks "
            "(`useResourceList`, `useResourceItem`, `useResourceMutations`) and the typed "
            "hooks generated by `karni types`.",
            "`karni rules --check <the page file>` must report no violations.",
        ),
        rules=("K009", "K201", "K202", "K204", "K303", "K306", "K309"),
    ),
    Procedure(
        name="add-module",
        description="Install an optional Karni module and wire it into settings",
        argument_hint="<module> (e.g. payments)",
        intro="Install Karni module: {arguments}",
        steps=(
            "Run `karni add <module>`. It adds the `karni-<module>` dependency to "
            "pyproject.toml, wires `karni_<module>` into the INSTALLED_APPS block marked "
            "`# karni:apps` in config/settings.py, and (once installed) records the "
            "module's agent guidance.",
            "Rebuild/install: `docker compose build` (or `uv pip install -r pyproject.toml` "
            "in a host venv), then `make migrate`. Run `karni add <module>` again if it "
            "asked you to.",
            "Run `karni context`. The module must appear under MODULES, and `karni rules` now "
            "includes its guidance.",
            "Configure only the settings the module documents. Do not patch its internals.",
            "To create a new reusable module instead: `karni make module <name>` "
            "(modules/karni-<name>/, docs/modules.md).",
        ),
        rules=("K009", "K308"),
    ),
    Procedure(
        name="new-module",
        description="Create a new local Django app following Karni conventions",
        argument_hint="<app_name>",
        intro="Create a local app: {arguments}",
        steps=(
            "Run `karni context` first to confirm the domain isn't already covered.",
            "`karni make app <app_name>` writes `__init__.py`, `apps.py`, `models.py`, "
            "`viewsets.py`, `migrations/`, `tests/` and adds the app to the `# karni:apps` "
            "block in config/settings.py. No admin.py, serializers.py, urls.py, forms.py: "
            "Karni derives all of that.",
            "Add models with `karni make model <Name> <field:type ...> --app <app_name> "
            "--with viewset --access <who>` (procedure new-model).",
            "`karni make migration && karni migrate && karni types`, then `karni context` "
            "to verify.",
            "Anything reusable across projects belongs in a Karni module: "
            "`karni make module <name>`, not in this project. Say so instead of building it.",
        ),
        rules=("K009", "K305", "K307"),
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
