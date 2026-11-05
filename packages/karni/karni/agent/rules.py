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
            "modules in a few hundred tokens. Trust it. On a large project read one area at a "
            "time: `karni context --summary`, then `karni context --app <label>` or "
            "`--model <name>` (`--max-tokens N` caps any of them)."
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
            "committing. Every enforced rule fails the build, and nothing only warns. It ends with "
            "suggestions (`SUG`): read each and apply its fix."
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
            "new-module, site-from-design. Run one with `karni rules --procedure <name>`, or "
            "with the matching slash command where your tool has one."
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
            "views, nor a search over several models (declare `class Karni: search` on each "
            "model: `GET /api/search/` and `<GlobalSearch>` serve it). Karni provides all of "
            "these. Never write a table of per-user permissions either: access given to one "
            "user is a per-user grant (`features: user_grants`, `karni.accounts.grants`), which "
            "Granted() already reads. If you think you need one, you need an override on an "
            "existing Karni base instead. The tables, forms and detail views meant here are app "
            "screens. A public server-rendered site (K309) is the one place for hand-written "
            "HTML pages, and its forms still post to a BaseViewSet."
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
            "pages do not go there (K309). A menu that differs per user is data, not code: "
            "`KARNI_NAVIGATION` (or `navigation:` in karni.yaml) with `<Layout "
            'navSource="server">`, never a menu a component filters by role.'
        ),
        rationale="The page cap (K202) and the inventory (`karni context` PAGES) rely on it.",
    ),
    Rule(
        code="K307",
        category="architecture",
        severity="should",
        summary="Cross-project code: a Karni module (karni modules list).",
        rule=(
            "Anything reusable across projects belongs in a Karni module (a `karni_<name>` "
            "package), not in this project. Say so instead of building it. Read the catalog "
            "first: the CATALOG lines of `karni context`, `karni modules list` and `karni "
            "modules show <name>` list every module and built-in feature (payments, approvals, "
            "login as a user, a public site, two-factor sign-in, sign-in with a code or with "
            "Google, Microsoft or Apple, terms acceptance, per-user grants, response caching), "
            "whether the project has it, its options and the questions to ask. Add a module "
            "with `karni add <name>` (or `modules:` in karni.yaml), turn a feature on with its "
            "setting (or `features:`), and take a module out with `karni remove <name>`, which "
            "never drops its tables. A mobile client needs a URL that does not move: set "
            "`api_version:` under `app:` in karni.yaml (`KARNI_API_VERSION`) for `/api/v1/`, "
            "deprecation headers and a client per version, and never write `/v1/` routes by hand."
        ),
        rationale=(
            "Code that would be written more than once belongs in Karni, never per project. "
            "Each catalog entry is tested, and rebuilding one costs more tokens than adding it."
        ),
        fix="Run `karni modules show <name>`, answer its questions, then `karni add <name>`.",
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
            "A designer's static pages go in with `karni import design <dir> --app <app> "
            "--editable`, which keeps the markup as written, never by copying them by hand. "
            "`karni make view <name> --app <app>` adds a page. Text and images a client may "
            "change are `{% editable %}` and `{% editable_image %}` blocks, navigation is "
            '`{% get_menu "<name>" as items %}` looped in the design\'s markup, and the '
            "site's name, logo and contact details are `site`: never hard-coded, and never "
            "a model or template tag of the project's own. The site's runtime (these tags, "
            "`{% ifactive %}`, `{% csp_hash %}`, the error pages, redirects) is the karni-site "
            "module, never project code. Views read content through each "
            "model's default manager (`Model.objects`, so model scopes apply and soft-deleted "
            "rows stay hidden) and filter drafts themselves. A public form (a contact form, a "
            "booking request, a sign-up) is `karni make form <name> <field:type> ... "
            '[--notify SETTING]` and `{% karni_form "<name>" %}` in the page: it saves '
            "through a `BaseViewSet` with `create=Public()`, works without JavaScript, carries "
            "the CSRF token and a honeypot, and its script, rate limit and email come from "
            "Karni. Never write a form view, a throttle or a form script for it. The site's "
            "page test, "
            "`<app>/tests/test_pages.py`, passes every page's URL to `assert_pages`: give a "
            "page whose path has a capture a real URL there. The React rules (K201, K202, "
            "K206) apply to app screens only."
        ),
        rationale=(
            "A marketing site must be crawlable and faithful to the client's design, which the "
            "app-screen rules forbid for good reason. One Django app with plain views keeps the "
            "API, the admin and the access layer as the only write path."
        ),
        fix=(
            "Run `karni make site <app>`, then `karni import design <dir> --app <app> "
            "--editable` for a designer's pages or `karni make view <name> --app <app>` per "
            "page, and `karni make form` for each form. Karni's docs page public-site covers "
            "editable content, SEO and public forms."
        ),
    ),
    Rule(
        code="K310",
        category="architecture",
        severity="must",
        summary="Before karni build: ask only karni plan --questions.",
        rule=(
            "When the app is described in karni.yaml, run `karni plan --questions` before "
            "`karni build` and ask the user only the questions it prints, in its order, with "
            "their options and defaults. Write each answer with `karni spec answer <id> "
            "<value>` (or in karni.yaml), and run it again until none is open. Never ask about "
            "anything karni.yaml already settles, nor about the stack, names, labels, colours "
            "or page titles: those are yours to choose."
        ),
        rationale=(
            "Karni chooses the questions with fixed rules over the spec and the module "
            "manifests (owners, access, the sign-up role, the kind, each module's and feature's "
            "asks), so every agent asks the same few, and the user is never asked what the "
            "spec or Karni's defaults already decide."
        ),
        fix=(
            "Run `karni plan --questions`, ask the user those questions only, then `karni spec "
            "answer <id> <value>` for each answer."
        ),
    ),
    Rule(
        code="K311",
        category="architecture",
        severity="must",
        summary="New app: /new-app. Never hand-write what karni.yaml expresses.",
        rule=(
            "To build an app from a request, follow the new-app procedure (`/new-app <the app "
            "in one line>`, or `karni rules --procedure new-app`): a recipe or the blank start, "
            "karni.yaml, `karni plan --questions`, `karni plan`, `karni build`. Never hand-write "
            "what karni.yaml can express (apps, entities, fields, owners, access, roles, "
            "modules, features, pages, seed counts): change karni.yaml and run `karni build` "
            "again. Write only the domain logic that is left, in the project's own files."
        ),
        rationale=(
            "karni build turns the spec into models, viewsets, migrations, seeds, tests, types "
            "and settings without a language model, so the agent writes a short YAML file "
            "instead of thousands of lines, and a later change to the spec updates the app "
            "without touching the code written by hand."
        ),
        fix=(
            "Move the hand-written entity, field, access, role or setting into karni.yaml, then "
            "run `karni build`."
        ),
    ),
    Rule(
        code="K312",
        category="architecture",
        severity="error",
        summary="Trees: TreeModel.",
        rule=(
            "A hierarchy (categories, regions, organisation units, a menu) is a tree model: "
            "`class Region(TreeModel, BaseModel)`, or `OrderedTreeModel` when siblings have an "
            "order, or `tree: true` / `tree: ordered` in karni.yaml. Never declare a `parent` "
            "foreign key to the model itself, never write recursive SQL or a loop over "
            "`.parent`, and never write a tree endpoint or a tree component. "
            "`Model.objects.descendants()`, `ancestors()` and `subtree_ids()` walk it, the "
            "API serves tree/, children/, ancestors/ and move/, and @karni/ui shows TreeView "
            "and TreeSelect. Tag a model to a tree with `class Karni: taxonomies = "
            '{"region": "geo.Region"}` (`taxonomies:` in karni.yaml), never a hand-written '
            "many-to-many with its own subtree filter or counts: the list filters "
            "`?region=` and `?region_descendants=`, facets/ and the tree:region scope come "
            "with it."
        ),
        rationale=(
            "Hand-written trees loop on cyclic data, cost one query per level and repeat the "
            "same endpoints and widgets in every project. TreeModel's walks are one cycle-safe "
            "query each."
        ),
        fix="Inherit TreeModel first and drop the parent field, or opt out with the reason.",
        enforced_by=("hand-written-tree",),
    ),
    Rule(
        code="K314",
        category="architecture",
        severity="must",
        summary="GROUP BY: Karni.aggregate.",
        rule=(
            "Grouped counts, sums, averages, top N with Other, and figures per year, quarter or "
            "month for a chart or a report are `class Karni: aggregate = {...}` on the model "
            "(`group_by`, `values`, `metrics`, `expressions`) and `GET <resource>/aggregate/` "
            "with `useAggregate` and `<DataChart aggregate={...} />`. A number stored as text is "
            "`TextNumber`. A chart people edit in the admin is a saved chart (`karni add "
            "charts`, `<SavedChart />`). Never write a view, an `@action` or a hook of your own "
            "that groups rows."
        ),
        rationale=(
            "The aggregate action runs under the list's filters and access, in one query (two "
            "with Other), and refuses what the model does not declare. A hand-written GROUP BY "
            "view repeats the filters and the access check and is where hidden rows leak into "
            "totals."
        ),
        fix=(
            "Declare the groups and values in `class Karni: aggregate`, then call `GET "
            "<resource>/aggregate/?group_by=...&metric=...&value=...`. Karni's docs page "
            "aggregations lists every parameter."
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
            "fields that must be hidden, read-only or write-only. "
            "`BigIntBaseModel` (experimental) is the same with an integer `id`, chosen per "
            "model in its class line; `karni context` shows each model's key type."
        ),
        rationale=(
            "The mixins supply the primary key (a UUID, or an integer with "
            "`BigIntBaseModel`), timestamps, soft delete, audit stamping and the "
            "managers the derived API/admin rely on. The exception is a table or view another "
            "system owns: a plain `models.Model` with `class Meta: managed = False` and `class "
            "Karni: external = True` (experimental, `karni make model <Name> --external "
            "--table <table>`), which Karni only reads unless `writable = True`."
        ),
        fix="Inherit karni.models.BaseModel or BigIntBaseModel (or compose its mixins).",
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
            "`# karni: allow(access-override): <why>`. Rows under the nodes of a tree a user "
            "was granted are the `tree:<path>` scope of a grant, never a hand-written subtree "
            "filter."
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
            "and why it exists. Long text a page shows formatted is `MarkdownField` "
            "(`name:markdown`). A model with many fields declares `class Karni: field_groups` "
            "(form and detail sections or tabs) and `column_sets` (table presets) instead of "
            "hand-built screens."
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
            "`<table>/<form>/<input>/<select>/<textarea>/<details>`. Dashboards and reports "
            "compose `DashboardGrid`, `ChartCard`, `DataTable` (computed rows), "
            "`ComparisonTable`, `Accordion` and `MarkdownView`."
        ),
        rationale="The components already handle data, validation, a11y and theming.",
        fix=(
            "Compose ResourceTable / DataTable / ComparisonTable / Accordion / ResourceForm / "
            "Input / Select from @karni/ui."
        ),
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
            "`karni make model --help`. `--access`: granted (default), public-read (anyone "
            "reads, staff write), public-create (a public form that anyone may send and staff "
            "read, rate-limited by Karni; `karni make form` writes a whole public form with its "
            "tests, email and page tag), owned:<fk to user>, staff, role:<name>, authenticated. "
            "Edit the generated `access` for anything "
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
            "Run `karni modules show <module>`: what it provides, what it needs and the "
            "questions to settle first, each with the setting its answer goes to.",
            "A PDF of one row (an invoice, a product sheet) is the `reports` module: declare a "
            "Report in `<app>/reports.py` (model, template, get_context), never a hand-written "
            "PDF view.",
            "A file only the row's readers may download (a contract scan, an ID photo) is the "
            "`storage` module: `ProtectedFileField` or `ProtectedImageField` (karni.yaml: "
            "`file:protected`), never a hand-written download view, presigned URL or boto3 "
            "call.",
            "Run `karni add <module>`. It adds the `karni-<module>` dependency to "
            "pyproject.toml, wires `karni_<module>` into the INSTALLED_APPS block marked "
            "`# karni:apps` in config/settings.py (with any middleware its manifest wires), "
            "and (once installed) records the module's agent guidance. It prints the URL "
            "include to add, if any.",
            "Rebuild/install: `docker compose build` (or `uv pip install -r pyproject.toml` "
            "in a host venv), then `make migrate`. Run `karni add <module>` again if it "
            "asked you to.",
            "Run `karni context`. The module must appear under MODULES, and `karni rules` now "
            "includes its guidance.",
            "Configure only the settings the module documents. Do not patch its internals.",
            "For `ai` (rows read from text, a web page or a PDF by a language model): the "
            "provider goes in karni.yaml (`modules: ai: {provider: ...}`), the API key and the "
            "model name in .env only (`ANTHROPIC_*` or `OPENAI_*`), and `karni check` fails "
            "until they are set. Use the `test` provider in tests and CI.",
            "To take it out again: `karni remove <module>` (it never drops the tables).",
            "To create a new reusable module instead: `karni make module <name>` "
            "(modules/karni-<name>/, docs/modules.md).",
        ),
        rules=("K009", "K307", "K308"),
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
    Procedure(
        name="site-from-design",
        description="Build the public site from a designer's pages, with models and real content",
        argument_hint="<design folder> [site app]",
        intro="Build the public site from the design: {arguments}",
        steps=(
            "Run `karni context` to see the kind, the apps, the models and whether a site app "
            "exists.",
            "`karni design analyze <design folder> --app <site app> --map "
            "content/design-map.json` lists the content that repeats (cards, detail pages, "
            "galleries, lists of links), the models and relations it proposes as `karni make "
            "model` commands, and the decisions the markup cannot settle, and writes a draft "
            "content map. Read it first: rename a model or field in its command and in the map "
            "together, and delete from both what should stay in a template.",
            "`karni import design <design folder> --app <site app> --editable --map "
            "content/design-map.json` turns the pages into the site app: `base.html` with the "
            "shared header and footer, a template, view and route per page, the files under "
            "`static/<site app>/`, `{% ifactive %}` on the menu. Every text, image, menu and "
            "contact detail the client sees becomes editable in the admin, except what the map "
            "reads into rows: the loops render that from the rows, never from blocks. The "
            "report names each `<form>`. Then `karni migrate` and `karni test`: the page test "
            "covers every page. Change which structures the map holds later? Import again "
            "before you edit the templates.",
            "Answer every decision in the map. A hand-picked list or flag: keep the value, "
            "remove its `decide` and add the field the decision names to that model's command. "
            "One a query derives (every project of this service, the newest three): delete the "
            "value from the map and query it in the view.",
            "Run the `karni make model` commands in the order printed (models others point at "
            "come first), then `karni make migration && karni migrate`. Staff edit the rows in "
            "the admin as it is: write no viewset, serializer or admin class for them.",
            "`karni design extract <design folder> --map content/design-map.json -o "
            "content/site.json` writes the pages' real content and copies the images it names "
            "to `content/files/`. Fix what it reports (a missing image, two pages that disagree "
            "on a value, a required field without one) in the map or the models, then extract "
            "again.",
            "`karni load content/site.json --dry-run` shows what changes per model, row by row. "
            "Then `karni load content/site.json`, and once more: the second run must say "
            "Nothing changed. Commit `content/`. Never fill these tables with `karni seed` (it "
            "refuses tables that hold real rows) or with content you type in.",
            "Turn the repeated markup into loops. The view reads `Model.objects` (filter what "
            "is not published, `select_related`/`prefetch_related` what the template loops "
            "over). The template keeps one copy of the item's markup inside `{% for %}` with "
            "`{{ row.field }}` where the map reads a value, `{% image row.image width=<its "
            "width in the card> alt=row.title %}` for an image (with `eager=forloop.first` in "
            "a list at the top of the page, such as a hero slider: the first picture loads "
            "first, not lazily) "
            "and `{{ row.heading|highlight }}` for highlighted words (`==words==`, the "
            "site's one convention: set `KARNI_SITE_HIGHLIGHT` to the markup the analysis "
            "names, unless `karni import design --editable` already did. `karni explain "
            "<SETTING>` prints any setting's format and default). A model's detail "
            "pages become one view and template with a `<slug:slug>` capture, keeping each "
            "page's URL (the slug is the page's file name).",
            "For those detail pages: `karni make view <model> --app <site app> --path "
            '"/<folder>/<slug:slug>/"` writes the view, its template and its route, and turns '
            "every `{% ifactive %}` naming the old pages' views into the folder's path "
            '(`"/<folder>/*"`). Build the '
            "template from one detail page's template (its blocks stay, their keys start with the "
            "model's name), read the row with `get_object_or_404(Model.objects, slug=slug)`, "
            "delete the old pages' views, routes and templates, and point every link at "
            "`{% url '<site app>:<model>' row.slug %}`. Give the model `get_absolute_url()` "
            "returning that URL. `{% karni_seo %}` finds the page's row by itself: `object` (or "
            "`seo`) in the context when it is a row, else the row in the context whose "
            "`get_absolute_url()` is the page's path. The row gives the page its title, "
            "description and share image, and wins over the template's own, so the detail "
            "template writes no `{% block title %}` or `{% block description %}`. `class Karni: "
            'seo = {"title": "name", "description": "intro"}` names the fields when they are '
            "not `title`, `description` and `image` (`karni explain karni_seo`). `karni check` "
            "(SITE002) and `karni check --seo` (SITE007, a menu item still pointing at an old "
            "page) name what is left.",
            "For each `<form>` the import named: `karni make form <name> <field:type> ...` with "
            "the design's fields (`--notify <SETTING>` for the email that tells staff) writes "
            "the model, its viewset, the tests and the email, and prints the `{% karni_form %}` "
            "tag that keeps the form's classes, labels and button, with `editable=` so the "
            "client edits its texts, and says which design field fills which model field. Put "
            "the tag where the `<form>` was, then `karni make migration && karni migrate`. "
            "Never write a form view, a form template or a throttle.",
            "`{% karni_seo %}` in `base.html` writes each page's title, description, canonical "
            "link, share tags and JSON-LD (a detail page's from its row, as above), "
            "`{% image %}` serves a card's picture at the card's size, and karni-site "
            "answers `/sitemap.xml` and `/robots.txt`: write none of them by hand. Give a model "
            'whose rows are not all public `class Karni: sitemap = {"filter": {...}}`, then run '
            "`karni check --seo` and fix each SITE010 to SITE018 it reports.",
            "`karni test`: give each detail page a real URL in the page test's `PAGES`. The "
            'test loads the content first (`load_content("content/site.json")` from '
            "`karni.testing`, which reads the path from the project root, in an autouse "
            "fixture: the page test the import wrote has it), so every page renders real rows. "
            "Then `karni check`. Nobody can sign in to the admin yet: `karni createsuperuser` "
            "makes the first account, and the client's own is a user the admin gives the staff "
            "role (or the editor role, to change only the content).",
        ),
        outro=(
            "Nothing is retyped and nothing is invented: every value comes from the design "
            "through extract and load, and a new version of the design is extract and load again."
        ),
        rules=("K009", "K309", "K003", "K301"),
    ),
    Procedure(
        name="new-app",
        description="Build an app from a one-line request: karni.yaml, then karni build",
        argument_hint="<the app in one line>",
        intro="Build this app: {arguments}",
        steps=(
            '`karni recipes list --match "<the request>"` ranks the recipes by the words they '
            "share with the request. Start karni.yaml from the closest one that fits (`karni "
            "recipes show <name>` prints its spec and what people usually change) or, when none "
            "does, from the blank start it prints. Write in it what the request asks for: apps, "
            "entities and fields, roles, modules (`karni modules list`), features, pages. `karni "
            "spec validate` checks it.",
            "`karni plan --questions` lists the questions for the user, most impact first. Ask "
            "the user those and only those, with their options and defaults, in one message. "
            "Names, labels and the rest are yours to choose.",
            "Write each answer with `karni spec answer <id> <value>` (a question the user leaves "
            "to you takes its default). Edit karni.yaml by hand only for what no question "
            "covers. Run `karni plan --questions` again until none is open.",
            "`karni plan` shows what `karni build` will change. Check that it is what the "
            "request asks for, and ask the user before any risky (!) change.",
            "`karni build` makes the project match karni.yaml: modules, models, viewsets, "
            "migrations, seeds, types, tests and `karni check`. It stops at the first failure "
            "with its code and what to do next. A Karni-owned file edited by hand stops it "
            "(C273): ask the user which of the three ways on to take.",
            "Write only the domain logic that is left, where the project owns the code: methods "
            "on the subclasses in `<app>/models.py`, custom actions in `<app>/viewsets.py`, "
            "demo values in `<app>/seeds.py`, your own pages and tests. Never edit "
            "`<app>/karni/` or the `karni:spec` blocks: `karni build` rewrites them.",
            "Done when `karni check` and `karni test` pass.",
        ),
        outro=(
            "Never hand-write what karni.yaml can express: change karni.yaml and run `karni "
            "build` again. The MCP tools recipes, questions, answer, plan and build do the same "
            "as these commands."
        ),
        rules=("K311", "K310", "K305", "K301"),
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
