"""Karni's error code registry: every code an error, check or test failure carries.

An AI agent (or a person) that reads a Karni error should be able to fix it
without a documentation lookup, so every message states what is wrong, where,
why Karni objects, and the exact fix. The code (``E104``) is the stable
handle: it never changes meaning and is never reused. ``karni explain E104``
prints the entry offline, and ``docs/errors.md`` is generated from this
registry, so the codes and their documentation cannot drift apart.

This module is stdlib only. karni-cli bundles a copy (``karni_cli/_errorcodes``)
and loads it by path, so ``karni explain`` works without Django or a project.

Code ranges
-----------
``E0xx``/``W0xx`` models, managers, scopes · ``E1xx``/``W1xx`` API (access,
viewsets, serializers, pagination, budgets, caching, expand) · ``E2xx``
accounts · ``E3xx`` admin · ``E4xx`` events, listeners, schedules, Celery ·
``E5xx`` settings, optional dependencies, deploy checks and production
(``karni.deploy``) · ``E6xx`` testing and seeding ·
``E7xx`` agent tooling (``karni check``, ``karni.rules.py``, changelog) ·
``E8xx`` import and export · ``E90x``–``E94x``/``W92x`` debugging (``karni
why``, request ids, the development capture, ``karni trace``, ``karni replay``,
``karni queries``) · ``E96x``/``E97x`` typed fields and database guarantees
(``karni.fields``) · ``E98x``/``W98x`` lifecycle and limited resources
(``StateField``, capacity, ``no_overlap``) · ``E27x``/``W54x`` external
tables, SQL views and a second database (``karni.db``) · ``E34x``/``W55x``
tree models (``karni.tree``) · ``E49x``/``W62x`` the tree scope
(``karni.accounts.tree_scope``) · ``E53x``/``W63x`` navigation from data
(``karni.navigation``).
``E`` codes are errors, ``W`` codes warnings. A system check's id is
``karni.<code>`` (silence a warning with ``SILENCED_SYSTEM_CHECKS``).

Retired codes are never reused: ``E108`` (Can() was reserved before the
roles-as-data tier shipped in 0.2; a bad ``Can()`` argument is ``E209``).

Modules register their own codes under their own prefix (karni-payments uses
``PAY``) through the ``karni.errorcodes`` entry-point group, whose value is a
tuple of :class:`ErrorCode`. The CLI's codes (``C``) live in karni-cli.

Override / escape hatch: :func:`registry` takes extra entries, and
:data:`DOCS_BASE_URL` / :data:`ERRORS_PAGE` are the only places a docs link
is built from.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "CODES",
    "DOCS_BASE_URL",
    "ERRORS_PAGE",
    "KINDS",
    "ErrorCode",
    "KarniError",
    "docs_url",
    "get",
    "problems",
    "registry",
]


def _docs_base_url() -> str:
    """``karni.links.DOCS_BASE_URL``, also when this module is loaded by path.

    karni-cli bundles this package without ``karni`` installed and loads it
    under a private name, so the import may fail; the build hook puts a copy
    of ``links.py`` next to this file, and the monorepo has it one level up.
    """
    try:
        from karni.links import DOCS_BASE_URL as base
    except ImportError:
        import importlib.util
        from pathlib import Path

        here = Path(__file__).resolve()
        for candidate in (here.parent / "links.py", here.parents[1] / "links.py"):
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location("_karni_links", candidate)
                if spec is not None and spec.loader is not None:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return str(module.DOCS_BASE_URL)
        raise
    return base


#: Base URL of Karni's documentation — ``karni.links.DOCS_BASE_URL``, the one place it is set.
DOCS_BASE_URL: Final[str] = _docs_base_url()
#: The generated page every code links to, relative to :data:`DOCS_BASE_URL`
#: (``docs/errors.md`` in the repository, served as a directory on the site).
ERRORS_PAGE: Final[str] = "errors/"

#: ``exception``: raised for code to fix · ``check``: a Django system check
#: error (boot fails) · ``warning``: a system check warning · ``api``: a 400
#: from the API naming the bad parameter · ``test``: a karni.testing failure.
KINDS: Final[tuple[str, ...]] = ("exception", "check", "warning", "api", "test")

_CODE = re.compile(r"^(?:[EW]\d{3}|[A-Z]{2,5}\d{3})$")


def docs_url(code: str) -> str:
    """The documentation link for ``code`` (``…/errors/#e104``)."""
    return f"{DOCS_BASE_URL}{ERRORS_PAGE}#{code.lower()}"


@dataclass(frozen=True)
class ErrorCode:
    """One registry entry: what the code means and how to fix it, in general terms.

    The raised message is the specific form (it names your class, field or
    setting); this entry is what ``karni explain`` and ``docs/errors.md`` show.
    """

    code: str
    title: str
    kind: str
    why: str
    fix: str
    #: Where it comes from: the class, function, check or command.
    source: str

    @property
    def url(self) -> str:
        return docs_url(self.code)

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "kind": self.kind,
            "why": self.why,
            "fix": self.fix,
            "source": self.source,
            "url": self.url,
        }


class KarniError(Exception):
    """Base of every error Karni raises for a developer to fix.

    ``str(error)`` is ``"<code>: <message> See <docs url>"``; ``.message`` is
    the bare message and ``.code`` the registry code. Subclasses that also
    inherit a builtin or Django exception (``karni.exceptions``) keep existing
    ``except ValueError`` / ``except ImproperlyConfigured`` clauses working.

    Override / escape hatch: a subclass may set a class-level ``code`` used
    when the raise site passes none.
    """

    code: str = ""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        self.message = message
        super().__init__(message)

    @property
    def docs_url(self) -> str:
        return docs_url(self.code) if self.code else ""

    def __str__(self) -> str:
        if not self.code:
            return self.message
        # A multi-line report (assert_crud, settings validation) keeps the link apart.
        sep = "\n" if "\n" in self.message else " "
        return f"{self.code}: {self.message}{sep}See {self.docs_url}"

    def __reduce__(self) -> tuple[Any, ...]:
        # Celery and multiprocessing pickle exceptions; subclasses' __init__
        # signatures differ, so rebuild without calling it.
        return (_rebuild, (type(self), self.message, self.__dict__.copy()))


def _rebuild(cls: type[KarniError], message: str, state: dict[str, Any]) -> KarniError:
    error = cls.__new__(cls)
    Exception.__init__(error, message)
    error.__dict__.update(state)
    return error


def _e(code: str, title: str, kind: str, source: str, why: str, fix: str) -> ErrorCode:
    return ErrorCode(code=code, title=title, kind=kind, why=why, fix=fix, source=source)


CODES: Final[tuple[ErrorCode, ...]] = (
    # E0xx models, managers, scopes
    _e(
        "E001",
        "A soft-delete model's default manager shows deleted rows",
        "check",
        "karni.checks.check_soft_delete_managers",
        "The model inherits SoftDeleteModel, but its default manager does not run Karni's "
        "scope pipeline, usually because another mixin listed first supplied a plain "
        "`objects`. Deleted rows then appear in every query, relation and API response, "
        "and the model misses every future scope such as `tenant`.",
        "Inherit karni.models.BaseModel, or list SoftDeleteModel first among the Karni "
        "mixins, or declare `objects = SoftDeleteManager()` (any manager built on "
        "karni.managers.ScopedManagerMixin) with `class Meta(SoftDeleteModel.Meta)`.",
    ),
    _e(
        "E002",
        "A scope or the KARNI_SCOPES setting is invalid",
        "check",
        "karni.scopes registry; karni.checks.check_scopes",
        "Every query of a scoped model runs the registered scopes in order. A scope that "
        "fails to load, has a bad name or order, or a KARNI_SCOPES list that names unknown "
        "or duplicate scopes would silently change which rows every query returns.",
        "Fix the scope class or the KARNI_SCOPES entry the message names. A Scope subclass needs "
        "an identifier `name` and an int `order`. KARNI_SCOPES is a list of registered names in "
        "pipeline order (or unset to run all of them).",
    ),
    _e(
        "E003",
        "objects.without() names no scope, or an unknown one",
        "exception",
        "karni.scopes; Model.objects.without()",
        "without() lifts a scope by name for one query. An unknown name would lift nothing "
        "while the code reads as if it did.",
        'Pass a registered scope name, e.g. Model.objects.without("soft_delete", '
        'reason="..."). The message lists the registered scopes.',
    ),
    _e(
        "E004",
        "objects.without() needs a reason",
        "exception",
        "karni.scopes; Model.objects.without()",
        "Lifting a scope shows rows the scope exists to hide (deleted rows, another "
        "tenant's rows). The reason is logged so every such query can be audited.",
        'Pass reason="<why this query must see rows the scope hides>", e.g. '
        'Model.objects.without("soft_delete", reason="admin: deleted filter").',
    ),
    _e(
        "E005",
        "without() was called on a queryset",
        "exception",
        "karni.managers.ScopedQuerySet.without",
        "Scopes are applied when the manager builds the queryset, so a queryset has already "
        "filtered by every scope. Lifting one there cannot bring rows back.",
        'Start from the manager: Model.objects.without("<scope>", reason="...").filter(...).',
    ),
    _e(
        "E006",
        "A scope's context is not bound",
        "exception",
        "karni.scopes.ScopeContextMissing (raised by a scope, e.g. tenant)",
        "A scope that needs context (the current tenant) has none, typically in a Celery "
        "task, management command or test. Karni fails closed instead of returning every "
        "tenant's rows.",
        "Bind the context before querying, as the message says (e.g. wrap the task body in "
        "the module's context manager), or lift the scope deliberately with "
        'Model.objects.without("<scope>", reason="...").',
    ),
    _e(
        "W001",
        "A registered scope is switched off by KARNI_SCOPES",
        "warning",
        "karni.checks.check_scopes",
        "KARNI_SCOPES lists the scopes that run. A registered scope it leaves out filters "
        "nothing, which is usually an accident after installing a module.",
        "Add the scope's name to KARNI_SCOPES (or unset KARNI_SCOPES to run every scope). "
        "If switching it off is deliberate, add 'karni.W001' to SILENCED_SYSTEM_CHECKS.",
    ),
    _e(
        "E007",
        "Karni.audit or Karni.sensitive is malformed",
        "exception",
        "karni.audit.capture",
        "A model opts into change history with True or a list of its field names, and names its "
        "sensitive fields the same way. A name the model does not have would silently audit or "
        "redact nothing.",
        "Write `class Karni: audit = True` (or a list of field names) and "
        "`sensitive = [...]` with field names of the model.",
    ),
    # E1xx API: access
    _e(
        "E101",
        "A viewset declares no access",
        "check",
        "karni.checks.check_viewsets; karni.api.access.KarniAccessPermission",
        "Access is mandatory (ADR 0001 Q2.1): without a declaration Karni cannot know which "
        "rows a user may see or change, so the viewset denies every request.",
        "Declare `access = Granted()` on the viewset (the roles' grants for its model, "
        "row-scoped), or a custom `Access(read=..., write=...)` (e.g. "
        "Access(read=Authenticated(), write=Owned('owner'))), or opt out explicitly with "
        "`access = Unscoped(reason='...')`.",
    ),
    _e(
        "E102",
        "access is not an Access(...) or Unscoped(...) declaration",
        "exception",
        "karni.api.access.validate_access",
        "The access declaration compiles into both the request gate and the row filter. Anything "
        "else would leave one of them undefined.",
        "Write `access = Access(read=..., write=..., create=...)` with predicates, or "
        "`access = Unscoped(reason='...')`. A bare predicate goes inside Access(read=...).",
    ),
    _e(
        "E103",
        "A predicate was expected but something else was given",
        "exception",
        "karni.api.access: Access(...), Owned(bypass=...), @action(access=...)",
        "Access slots, Owned(bypass=...) and @action(access=...) take predicate instances so "
        "they can be evaluated per request and per row.",
        "Pass a predicate instance: Owned('field'), HasRole('staff'), Authenticated(), "
        "Public(), Where(fn), combined with | and &. Write HasRole('staff'), not HasRole.",
    ),
    _e(
        "E104",
        "Owned() does not name a path to the user",
        "exception",
        "karni.api.access.Owned; karni.api.access.validate_access",
        "Owned('path') filters rows to those whose path leads to request.user, and stamps the "
        "owner on create. A path that does not end at the user model would match nothing or the "
        "wrong rows.",
        "Name the owner relation as a string, following relations with __ and ending at "
        "the user model: Owned('organizer') or Owned('event__organizer').",
    ),
    _e(
        "E105",
        "HasRole() names no roles",
        "exception",
        "karni.api.access.HasRole",
        "Roles are Django group names. A HasRole without names would grant nobody.",
        "Pass one or more group names: HasRole('staff') or HasRole('organizer', 'staff').",
    ),
    _e(
        "E106",
        "A Where() function is invalid",
        "exception",
        "karni.api.access.Where",
        "Where(fn) calls fn(request) for the request gate and as the row filter. The function "
        "must be callable and return a Q (rows) or a bool (everything or nothing).",
        "Pass a function of the request returning a Q or a bool, e.g. "
        "Where(lambda request: Q(published=True)).",
    ),
    _e(
        "E107",
        "Unscoped() needs a reason",
        "exception",
        "karni.api.access.Unscoped",
        "Opting a viewset out of access control is sometimes right (a public catalogue), but it "
        "must be deliberate and reviewable. The reason is published in karni context and the "
        "schema.",
        "Write `access = Unscoped(reason='public catalogue')` with a non-empty reason.",
    ),
    _e(
        "E109",
        "Access predicates were combined with and / or / not",
        "exception",
        "karni.api.access.Predicate.__bool__",
        "Python's `and`/`or`/`not` evaluate truthiness, so one side of the expression would "
        "be silently dropped.",
        "Combine predicates with | and &: Owned('user') | HasRole('staff').",
    ),
    # E1xx API: viewsets, pagination, budgets, caching
    _e(
        "E110",
        "A viewset has neither model nor queryset",
        "exception",
        "karni.api.viewsets.BaseViewSet",
        "Karni generates the queryset, serializer, filters and expansion from the model.",
        "Set `model = YourModel` on the viewset (or `queryset = ...`), or override "
        "get_queryset() and get_serializer_class().",
    ),
    _e(
        "E111",
        "Pagination was switched off without Unpaginated(...)",
        "exception",
        "karni.pagination.check_pagination_class; BaseViewSet",
        "An unpaginated list grows with the table until it times out (ADR 0001 Q3.5), so "
        "every list must be bounded.",
        "Keep the default paginator, or declare `pagination = Unpaginated(max_rows=N, "
        "reason='...')` to return a bounded plain list.",
    ),
    _e(
        "E112",
        "pagination_class is not a Karni paginator",
        "exception",
        "karni.pagination.check_pagination_class",
        "Karni's paginators enforce KARNI_MAX_PAGE_SIZE. Another paginator would let a client "
        "request unbounded pages.",
        "Subclass karni.pagination.KarniPageNumberPagination or KarniCursorPagination.",
    ),
    _e(
        "E113",
        "Unpaginated(...) is invalid",
        "exception",
        "karni.pagination.Unpaginated; BaseViewSet.pagination",
        "Unpaginated lists still need a hard row limit and a reviewable reason.",
        "Write `pagination = Unpaginated(max_rows=500, reason='CSV export')` with a "
        "positive max_rows and a non-empty reason. To change the paginator, set "
        "pagination_class instead.",
    ),
    _e(
        "E114",
        "Both pagination and pagination_class are declared",
        "exception",
        "karni.api.viewsets.BaseViewSet",
        "The two declarations contradict each other.",
        "Keep one: pagination = Unpaginated(...) for a plain bounded list, or "
        "pagination_class for another Karni paginator.",
    ),
    _e(
        "E115",
        "A query Budget(...) is invalid",
        "exception",
        "karni.performance.Budget; BaseViewSet.query_budget",
        "A query budget caps SQL statements per request to catch N+1 regressions. Raising it must "
        "be a measured, explained decision.",
        "Write `query_budget = Budget(list=25, reason='...')`: name at least one action, use "
        "positive integers (None stops checking an action) and give a non-empty reason.",
    ),
    _e(
        "E116",
        "query_budget names unknown actions",
        "exception",
        "karni.api.viewsets.BaseViewSet",
        "A budget for an action the viewset does not have would never apply.",
        "Use the viewset's action names (list, retrieve, create, update, partial_update, "
        "destroy, or an @action's name), or default= for every other action.",
    ),
    _e(
        "E117",
        "A request ran more SQL queries than its budget",
        "exception",
        "karni.api.viewsets.BaseViewSet; karni.testing.query_budget",
        "Repeated statements are almost always an N+1: a relation loaded once per row. "
        "Budgets turn that into a failing test instead of a slow production page.",
        "Read the repeated statements in the message and load that relation up front "
        "(select_related / prefetch_related, or let the optimizer see it through the "
        "serializer). If the work is real, raise the limit: query_budget = Budget(list=N, "
        "reason='...').",
    ),
    _e(
        "E118",
        "KARNI_QUERY_BUDGET_MODE is invalid",
        "exception",
        "karni.performance.budget_mode; karni.testing.pytest_plugin",
        "The mode decides whether an exceeded budget is ignored, logged or raised.",
        "Set KARNI_QUERY_BUDGET_MODE (or the pytest ini option karni_query_budget_mode) to "
        "'off', 'warn' or 'raise'.",
    ),
    _e(
        "E119",
        "Cache(...) or Uncached(...) is invalid",
        "exception",
        "karni.api.caching; BaseViewSet.cache",
        "Response caching must have a positive lifetime, and opting a viewset out must be "
        "explained.",
        "Write `cache = Cache(ttl=300)` with a positive integer, or `cache = "
        "Uncached(reason='balances change on every request')`.",
    ),
    _e(
        "E120",
        "Query hints are invalid",
        "exception",
        "karni.api.optimizer.validate_hints",
        "select_related / prefetch_related / select hints are merged into the optimizer's plan, "
        "so they must be lookups it can apply.",
        'Give a list of lookup strings (e.g. select_related = ["venue"]) or Prefetch '
        "objects for prefetch_related.",
    ),
    _e(
        "E121",
        "optimize must be True or False",
        "exception",
        "karni.api.viewsets.BaseViewSet",
        "optimize switches the automatic query optimizer for the viewset.",
        "Set optimize = True (default) or optimize = False.",
    ),
    # E1xx API: serializers and expand
    _e(
        "E122",
        "APIMeta declares both fields and exclude",
        "exception",
        "karni.api.serializers (generated serializers)",
        "The generated serializer can take an allow-list or a deny-list, not both.",
        "Keep APIMeta.fields or APIMeta.exclude on the model.",
    ),
    _e(
        "E123",
        "APIMeta names fields the serializer does not have",
        "exception",
        "karni.api.serializers (generated serializers)",
        "read_only_fields, write_only_fields and expand entries must name fields that the "
        "generated serializer exposes, or they would silently do nothing.",
        "Fix the spelling, or add the field to APIMeta.fields (or remove it from exclude).",
    ),
    _e(
        "E124",
        "A field is both read-only and write-only",
        "exception",
        "karni.api.serializers (generated serializers)",
        "A field cannot be both returned-only and accepted-only.",
        "Remove the field from APIMeta.read_only_fields or APIMeta.write_only_fields.",
    ),
    _e(
        "E125",
        "An expandable field is not a relation",
        "exception",
        "karni.api.serializers.expanded_field",
        "?expand= replaces a foreign key's id with the related object, so only relations can be "
        "expanded.",
        "Name a ForeignKey, OneToOneField or ManyToManyField (or a reverse relation) of the model.",
    ),
    _e(
        "E126",
        "The ?expand= parameter names an unknown or invalid path",
        "api",
        "karni.api.expansion",
        "Expansion is validated against the model so a typo returns a 400 instead of a "
        "silently unexpanded response.",
        "Use the keys the error lists (comma-separated, nested with dots: "
        "?expand=venue,tiers.event). Each segment must be a relation.",
    ),
    _e(
        "E127",
        "The ?expand= path is too deep",
        "api",
        "karni.api.expansion",
        "Each level of expansion multiplies the work per row, so KARNI_API_MAX_EXPAND_DEPTH caps "
        "the depth.",
        "Request fewer levels, or raise KARNI_API_MAX_EXPAND_DEPTH in settings if the "
        "client really needs them.",
    ),
    _e(
        "E128",
        "KARNI_API_ROUTER cannot be imported",
        "check",
        "karni.checks.check_viewsets",
        "The router factory builds every API route. Without it the API serves nothing.",
        "Point KARNI_API_ROUTER at an importable zero-argument factory returning a router "
        "(default 'karni.api.routers.get_default_router').",
    ),
    _e(
        "E129",
        "List or retrieve queries grow with the number of rows (N+1)",
        "test",
        "karni.testing.performance (pytest --pyargs karni.testing.performance)",
        "The scaling check runs list and retrieve with few and many rows. More rows must not mean "
        "more queries, or the page slows down as the table grows.",
        "Let the optimiser see the relation through the serializer, or add "
        "select_related / prefetch_related hints (or APIMeta.select/prefetch) for a "
        "SerializerMethodField or property. Opt out only with "
        "`# karni: allow(query-scaling): <reason>` above the viewset class.",
    ),
    _e(
        "E130",
        "An opt-out marker has no reason",
        "test",
        "karni.testing (# karni: allow(<rule>) markers)",
        "Opting out of a check must be deliberate and reviewable. The reason is what gets "
        "reviewed.",
        "Write the reason after the colon: `# karni: allow(<rule>): <why>`.",
    ),
    _e(
        "E131",
        "search_fields names a write-only field",
        "check",
        "karni.checks.check_viewsets",
        "A field in APIMeta.write_only never appears in a response, but ?search= over it answers "
        "whether a row contains a value. That makes search a membership oracle on a hidden column.",
        "Remove the field from search_fields, or take it out of APIMeta.write_only if it "
        "may be read.",
    ),
    # E1xx API: throttling
    _e(
        "E132",
        "Throttle(...) is invalid",
        "exception",
        "karni.api.throttling.Throttle; BaseViewSet.throttle",
        "A viewset's throttle declaration names actions of that viewset and gives each a DRF "
        "rate, '<number>/<period>' with the period s, sec, second, m, min, minute, h, hour, d "
        "or day.",
        "Write `throttle = Throttle(create='10/hour')`, naming only actions the viewset has "
        "(the standard ones, or a custom @action by its method name).",
    ),
    # E1xx API: the staff app's dashboard
    _e(
        "E133",
        "Karni.dashboard is malformed or names a field the model does not have",
        "check",
        "karni.dashboard.dashboard_spec; karni.checks.check_dashboards",
        "The dashboard declaration is published in the OpenAPI schema and @karni/ui's "
        "<Dashboard> counts rows with the list endpoint's filters. A field name with a typo, "
        "a value the field does not have or a count without filters would show a wrong number, "
        "so the declaration is refused at boot.",
        "Write dashboard = True, or a dict with the keys label, order, total, new_days, by, "
        "values, counts, recent, columns and date_field, naming fields of the model: e.g. "
        "dashboard = {'by': 'status', 'counts': {'Due today': {'due_on': 'today'}}, "
        "'recent': 5}.",
    ),
    _e(
        "W101",
        "A hand-written serializer duplicates the one Karni generates",
        "warning",
        "karni.checks.check_viewsets",
        "Karni generates the serializer from the model (APIMeta tunes it). A copy that "
        "declares nothing of its own drifts from the model and from the schema the "
        "frontend is generated from.",
        "Delete the serializer and its serializer_class line, and tune the generated one "
        "with APIMeta on the model. Keep serializer_class only for a serializer with custom "
        "fields or validation.",
    ),
    _e(
        "W102",
        "Any self-registered user may change and delete every row of a resource",
        "warning",
        "karni.checks.check_open_writes",
        "The viewset's `write` predicate is Authenticated() or Public(), not narrowed with & "
        "by HasRole, Granted, Owned or Can, while KARNI_ACCOUNTS_REGISTRATION is True. "
        "Anyone who opens an account through register/ can then update and delete every "
        "row the viewset routes. A test that acts as any signed-in user passes and confirms "
        "it. Karni 0.4.0's `--access public-read` preset generated this declaration.",
        'Tighten write: HasRole("staff") (what `--access public-read` now writes), '
        'Granted() (the roles\' grants) or Owned("<field>"). create=Authenticated() with '
        "an Owned() write is the user-generated-content pattern and is not flagged. If "
        "nobody may self-register, set KARNI_ACCOUNTS_REGISTRATION = False. If every "
        "signed-in user is trusted, add 'karni.W102' to SILENCED_SYSTEM_CHECKS.",
    ),
    # E2xx accounts
    _e(
        "E201",
        "KARNI_ACCOUNTS_EMAIL_BACKEND is not an accounts email backend",
        "exception",
        "karni.accounts.emails.get_backend",
        "Account emails (verification, password reset) are sent through this backend.",
        "Point the setting at a subclass of karni.accounts.emails.AccountsEmailBackend, "
        "e.g. 'karni.accounts.emails.DjangoEmailBackend'.",
    ),
    _e(
        "E202",
        "No KARNI_ACCOUNTS_LINKS entry for a token purpose",
        "exception",
        "karni.accounts.emails",
        "Emails link to your frontend, so Karni needs the URL template for each purpose "
        "(verify_email, reset_password, ...).",
        "Add the purpose to KARNI_ACCOUNTS_LINKS, e.g. "
        "{'reset_password': '{frontend}/reset-password?token={token}'}.",
    ),
    _e(
        "E203",
        "create_user() or create_superuser() was called with invalid arguments",
        "exception",
        "karni.accounts.managers.UserManager",
        "Karni users log in by email, and a superuser must be staff and superuser.",
        "Pass email= (and password=). For create_superuser(), leave is_staff and "
        "is_superuser unset or True.",
    ),
    _e(
        "E204",
        "Unknown one-time token purpose",
        "exception",
        "karni.accounts.tokens",
        "One-time tokens are issued per purpose so a reset token cannot verify an email.",
        "Use one of the purposes the message lists.",
    ),
    _e(
        "E205",
        "KARNI_ROLES is malformed",
        "exception",
        "karni.accounts.roles.declared_roles",
        "The role declaration is the single source of what each role may do. A malformed entry "
        "cannot be reconciled into the role tables.",
        "Write KARNI_ROLES = {'<slug>': {'name': ..., 'description': ..., 'system': bool, "
        "'grants': {'app_label.model:action': '<scope>'}}}. A pattern may use '*' for the model "
        "or the action (or '*' alone). A scope is 'all', 'own', 'related:<key>', "
        "'custom:<name>' or 'tree:<path>'.",
    ),
    _e(
        "E206",
        "A grant in KARNI_ROLES cannot be resolved",
        "exception",
        "karni.accounts.roles.sync_roles",
        "A pattern that matches no permission, an 'own' scope on a model with no owner field, a "
        "'related' scope on a model without that scope path, or a 'custom' scope nobody "
        "registered would silently grant nothing. Karni refuses it instead.",
        "Fix the key (permissions look like 'events.event:view', and extra actions come from "
        "`class Karni: actions`), declare `owner_field` / `scope_paths` in the model's "
        "`class Karni`, or register the custom scope with karni.accounts.roles.register_scope.",
    ),
    _e(
        "E207",
        "user.can() was given an action without a model",
        "exception",
        "karni.accounts.roles.user_can",
        "A permission is a (model, action) pair, so a bare action name cannot be looked up.",
        "Pass the full key, user.can('shop.order:approve'), or name the model: "
        "user.can('approve', obj=order) or user.can('approve', model=Order).",
    ),
    _e(
        "E208",
        "The request lacks the permission @requires names",
        "api",
        "karni.accounts.roles.requires",
        "A view or service guarded with @requires('app.model:action') was called by a user "
        "whose roles hold no grant for it (a 403).",
        "Grant the permission to one of the user's roles in KARNI_ROLES and run "
        "`karni sync-roles`, or assign the user a role that has it.",
    ),
    _e(
        "E209",
        "Can() was given a bad permission, or one for another model",
        "exception",
        "karni.api.access.Can",
        "Can() names permissions as 'app_label.model:action', and its row filter is built "
        "against that model, so a viewset's declaration can only use its own model's "
        "permissions.",
        "Write Can('events.event:approve'). On EventViewSet it must be an events.event "
        "permission. To gate on another model's permission, use HasRole(...).",
    ),
    _e(
        "E212",
        "Karni.field_roles is malformed, names a missing field or an undeclared role",
        "check",
        "karni.meta.field_roles; karni.checks.check_field_roles",
        "Field-level visibility is declared once on the model as field -> roles. A typo in a "
        "field name hides nothing, and a role nobody holds hides the field from everyone, so both "
        "are refused at boot.",
        "Write field_roles = {'phone': {'read': ['staff', 'support'], 'write': ['staff']}} "
        "(or 'phone': ['staff'] for read and write) with field names of the model and role "
        "slugs declared in KARNI_ROLES.",
    ),
    _e(
        "E210",
        "scope_exempt = True without a reason",
        "exception",
        "karni.api.access.validate_access",
        "A viewset or admin that shows every row its gate admits is the one place row scoping is "
        "off. Without a reason it looks like an oversight, and karni check lists every exemption "
        "by its reason.",
        "Add scope_exempt_reason = '...' next to scope_exempt = True (e.g. 'public "
        "catalogue'), or remove the exemption and let Granted() / the roles' grants scope "
        "the rows.",
    ),
    _e(
        "E211",
        "Granted() has no permission for this action or viewset",
        "exception",
        "karni.api.access.Granted",
        "Granted() resolves to the viewset's model and the current action. An unsafe custom "
        "@action the model never declared has no permission to check, and a viewset without a "
        "model has nothing to resolve against. Evaluating it outside a viewset is the same error.",
        "Add the action to `class Karni: actions = [...]` on the model and grant "
        "'app.model:<action>' in KARNI_ROLES, give the action its own @action(access=...), "
        "set `model = ...` on the viewset, or evaluate through action_predicate(view, "
        "access).",
    ),
    _e(
        "E213",
        "The permission matrix refused a change",
        "api",
        "karni.accounts.matrix.apply_changes",
        "A guard rail stopped the request and nothing was written: a system role's declared "
        "grant is locked, the operator does not hold the permission (or holds it at a "
        "narrower scope than the one granted), the change would remove the operator's own "
        "last permission to change permissions, or the role, permission or scope is unknown.",
        "Change KARNI_ROLES for a system role's grants, ask someone who holds the permission at "
        "that scope, keep one of your roles able to change permissions, or check the role slug, "
        "the 'app.model:action' key and the scope value against GET permissions/matrix/.",
    ),
    _e(
        "E214",
        "A role's scope names a path the model does not have",
        "check",
        "karni.checks.check_role_scope_paths",
        "A grant's scope becomes a database filter on every request: `own` follows "
        "Karni.owner_field, `related:<key>` follows Karni.scope_paths[key], and a `custom:<name>` "
        "scope builds its own. A path the model does not have would answer 500 to every user "
        "holding the grant. This typically happens after a new model joins a wildcard grant "
        "written for its siblings.",
        "Give the model the path the scope expects (`class Karni: owner_field = "
        "'workspace__members'`, or the scope path), teach the custom scope the new model, "
        "or narrow the grant's pattern so it does not cover the model.",
    ),
    # E215-E227 sign-in with an ID token (karni.accounts.social_token, experimental)
    _e(
        "E215",
        "The ID token is not valid",
        "api",
        "karni.accounts.social_token.verify_id_token (POST <auth>/social/<provider>/)",
        "Karni verifies an ID token offline: a JWT signed with one of the provider's published "
        "keys, with the algorithm the provider uses, carrying exp, iat, iss, aud and sub. A token "
        "that is malformed, signed with another key or algorithm, missing one of those claims, or "
        "issued in the future (iat or nbf past the leeway) proves nothing, so the answer is a 401.",
        "Send the ID token itself (not the access token, and not the authorization code) exactly "
        "as the provider's SDK returned it, and get a fresh one. A token issued in the future "
        "means the server's clock is off: fix the clock, or raise KARNI_SOCIAL_TOKEN_LEEWAY.",
    ),
    _e(
        "E216",
        "The ID token was issued for another application",
        "api",
        "karni.accounts.social_token.verify_id_token",
        "A token's aud claim names the client id it was issued to. Accepting a token issued to "
        "another application would let any app that signs its users in with the same provider "
        "sign them in here too, so aud must be one of the configured client ids (401).",
        "Add the client id the app uses to KARNI_SOCIAL_TOKEN_PROVIDERS[<provider>]['client_ids']: "
        "the web client id, and each iOS and Android client id (for Apple, the service id and "
        "the bundle id).",
    ),
    _e(
        "E217",
        "The ID token comes from another issuer or tenant",
        "api",
        "karni.accounts.social_token.verify_id_token",
        "Each provider has its own issuer: accounts.google.com, "
        "https://appleid.apple.com, or for Microsoft "
        "https://login.microsoftonline.com/<tenant id>/v2.0 with the token's own tid. A "
        "Microsoft token from a tenant the 'tenants' setting does not allow is refused the same "
        "way (401).",
        "Check that the token comes from the provider of the URL it was posted to. For "
        "Microsoft, request a v2.0 token and list its tenant (or 'common', 'organizations' or "
        "'consumers') in KARNI_SOCIAL_TOKEN_PROVIDERS['microsoft']['tenants'].",
    ),
    _e(
        "E218",
        "The ID token has expired",
        "api",
        "karni.accounts.social_token.verify_id_token",
        "ID tokens live minutes to an hour. Karni accepts one up to its exp claim plus "
        "KARNI_SOCIAL_TOKEN_LEEWAY seconds (401 after that).",
        "Get a fresh token from the provider's SDK right before posting it. Do not store ID "
        "tokens for later.",
    ),
    _e(
        "E219",
        "The ID token's signing key is unknown",
        "api",
        "karni.accounts.social_token.signing_key",
        "Karni looks the token's kid up in the provider's key set (JWKS), cached for "
        "KARNI_SOCIAL_TOKEN_JWKS_TTL seconds. An unknown kid fetches the key set again, at most "
        "once a minute per provider, so a rotated key works within a minute. A kid that is still "
        "missing answers 401. A key set that cannot be fetched answers 503.",
        "Send a token the provider issued recently. A 503 means the server cannot reach the "
        "provider's JWKS URL: check its outbound network, or the fetcher named in "
        "KARNI_SOCIAL_TOKEN_JWKS_FETCHER.",
    ),
    _e(
        "E220",
        "The ID token's nonce does not match",
        "api",
        "karni.accounts.social_token.verify_id_token",
        "A nonce binds the token to one sign-in attempt, so a stolen token cannot be replayed. "
        "When the request sends a nonce, the token's nonce claim must equal it, or its SHA-256 "
        "hex digest (Apple's convention: the app passes the hash to Apple and the raw value to "
        "Karni). A provider with 'require_nonce' refuses a request without one (401).",
        "Post the nonce the app generated for this sign-in, the raw value. Generate a new one "
        "for every attempt.",
    ),
    _e(
        "E221",
        "The ID token carries no email address",
        "api",
        "karni.accounts.social_token.sign_in",
        "A token whose identity is not linked yet is matched to an account by its email. Without "
        "an email claim (for Microsoft, email or an email-shaped preferred_username) there is "
        "nothing to match or create (400).",
        "Request the email scope. Apple sends the email only on the first sign-in of a user, so "
        "that first answer must reach Karni.",
    ),
    _e(
        "E222",
        "The provider did not verify the email address",
        "api",
        "karni.accounts.social_token.sign_in",
        "Karni creates an account from a token, or links a token to the account with the same "
        "email, only when the provider says it verified the address. Otherwise anyone could put "
        "someone else's address in a token and take over their account. Microsoft tokens count "
        "as verified only with the xms_edov claim true or a tenant listed in 'trusted_tenants' "
        "(400). An identity already linked signs in without this check.",
        "For Microsoft, add the xms_edov optional claim to the app registration, or list your "
        "organisation's tenant id in KARNI_SOCIAL_TOKEN_PROVIDERS['microsoft']['trusted_tenants']. "
        "Otherwise the user signs in with a password, or with a provider that verified the "
        "address.",
    ),
    _e(
        "E223",
        "Sign-up with an ID token is closed",
        "api",
        "karni.accounts.social_token.sign_in",
        "KARNI_SOCIAL_TOKEN_SIGNUP is 'existing' (the default while KARNI_ACCOUNTS_REGISTRATION "
        "is False): only an identity already linked, or an account with the token's email, may "
        "sign in. Nobody else gets an account (400).",
        "Create the account first (in the admin, or let staff invite the user), then sign in "
        "with the token. To let anyone in, set KARNI_SOCIAL_TOKEN_SIGNUP = 'open', or "
        "'approval' to create accounts an administrator activates.",
    ),
    _e(
        "E224",
        "The account awaits an administrator's approval",
        "api",
        "karni.accounts.social_token.sign_in; karni.accounts.otp.verify_code",
        "With KARNI_SOCIAL_TOKEN_SIGNUP = 'approval', a token without an account creates an "
        "inactive one. The answer is a 202 with this code and no credentials, again on each "
        "sign-in until an administrator activates the account. With KARNI_EMAIL_OTP_SIGNUP = "
        "'approval', the code that creates the account answers the same 202. A later code for "
        "the inactive account answers E226.",
        "An administrator ticks 'Active' on the user's page in the admin. The next sign-in then "
        "succeeds.",
    ),
    _e(
        "E225",
        "This sign-in provider is not configured",
        "api",
        "karni.accounts.api.views.SocialTokenLoginView",
        "Each provider named in KARNI_SOCIAL_TOKEN_PROVIDERS gets its own social/<provider>/ "
        "route. A provider the setting does not name answers 404.",
        "Add the provider with its client ids to KARNI_SOCIAL_TOKEN_PROVIDERS, or post to the "
        "route of a configured one.",
    ),
    _e(
        "E226",
        "The account is inactive",
        "api",
        "karni.accounts.social_token.sign_in; karni.accounts.otp.verify_code",
        "An inactive user never signs in, by password, by token or by a code sent by email "
        "(401). Sign-in by code says so only after a right code, so the answer tells nothing to "
        "someone who does not read that mailbox.",
        "An administrator activates the account in the admin, if it should sign in.",
    ),
    _e(
        "E227",
        "An account with this email exists and is not linked",
        "api",
        "karni.accounts.social_token.sign_in",
        "KARNI_SOCIAL_TOKEN_LINK_VERIFIED is False, so a token is never linked to an existing "
        "account that has a password, even when the provider verified the email (400).",
        "Sign in with the password. Linking a provider from a signed-in session is not built "
        "yet. To link on a verified email, set KARNI_SOCIAL_TOKEN_LINK_VERIFIED = True (the "
        "default).",
    ),
    # E235-E236 sign-in with a code sent by email (karni.accounts.otp, experimental)
    _e(
        "E235",
        "The sign-in code is wrong or has expired",
        "api",
        "karni.accounts.otp.verify_code (POST <auth>/otp/verify/)",
        "One answer covers every failure of a code, so it tells nobody whether an address has an "
        "account: a wrong code, one past KARNI_EMAIL_OTP_TTL, one already used, one replaced by a "
        "newer code, one locked after KARNI_EMAIL_OTP_MAX_ATTEMPTS wrong guesses, an address no "
        "code was sent to, and an address that may not sign up (KARNI_EMAIL_OTP_SIGNUP = "
        "'existing'). The precise reason is only in the accounts.otp.refused log event (401).",
        "Ask for a new code with POST otp/send/ and type the newest one. Only the latest code of "
        "an address works. Check the reason in the log when one user keeps failing.",
    ),
    _e(
        "E236",
        "Sign-in with a code is turned off",
        "api",
        "karni.accounts.api.views.OtpSendView; karni.accounts.api.views.OtpVerifyView",
        "otp/send/ and otp/verify/ are mounted only while KARNI_EMAIL_OTP is True. A URLconf "
        "built while it was True answers 404 with this code once the setting is False.",
        "Set KARNI_EMAIL_OTP = True (or KARNI_EMAIL_OTP=True in the environment) to offer "
        "sign-in with a code, or sign in with login/.",
    ),
    # E245-E249 terms acceptance (karni.accounts.terms, experimental)
    _e(
        "E245",
        "The signed-in user has not accepted the current terms",
        "api",
        "karni.accounts.terms.TermsGateMiddleware",
        "KARNI_TERMS requires every signed-in user to accept its current version before using "
        "the API. The gate answers 403 with this code, the version and the terms url to a "
        "signed-in user who has not accepted that version, on every request under "
        "KARNI_TERMS['paths'] (default ['/api/']) outside the auth mount and "
        "KARNI_TERMS['exempt']. Staff and superusers are gated like everyone. A new version "
        "makes everyone accept again.",
        "Show the terms at the url in the answer, then POST <auth mount>/terms/accept/ with "
        '{"version": "<the version in the answer>"}. @karni/ui\'s TermsGate does both. To keep '
        "a path open before acceptance, add its prefix to KARNI_TERMS['exempt'].",
    ),
    _e(
        "E246",
        "The accepted terms version is not the current one",
        "api",
        "karni.accounts.terms.accept (POST <auth>/terms/accept/)",
        "terms/accept/ records acceptance of KARNI_TERMS['version'] only. A client that sends "
        "another version showed the user other terms (an old copy, or the version changed after "
        "the page loaded), so nothing is recorded (400). The answer carries the current version "
        "and url.",
        "Show the terms at the url in the answer and send the version in the answer. GET "
        "terms/ returns the current version too.",
    ),
    _e(
        "E247",
        "A terms acceptance is a permanent record",
        "exception",
        "karni.accounts.models.TermsAcceptance",
        "Each TermsAcceptance row records that a user accepted a version of the terms, when, "
        "from which IP and with which client. The table is append-only: saving an existing row, "
        "deleting one (soft or hard) and update() or delete() on a queryset of them would "
        "rewrite that record, so each one raises.",
        "Record a new acceptance with karni.accounts.terms.accept(), or POST terms/accept/. To "
        "make everyone accept again, change KARNI_TERMS['version']. A user's rows go only with "
        "the user: user.hard_delete() deletes them.",
    ),
    _e(
        "E248",
        "The terms gate is not in MIDDLEWARE, or runs before authentication",
        "check",
        "karni.checks.check_terms_middleware",
        "KARNI_TERMS requires acceptance, but karni.accounts.terms.TermsGateMiddleware (or a "
        "subclass) is missing from MIDDLEWARE, so nothing is gated, or it comes before "
        "django.contrib.auth's AuthenticationMiddleware, so it cannot see the session user. "
        "karni_settings() lists it, so this happens when MIDDLEWARE is replaced after the call.",
        "Add 'karni.accounts.terms.TermsGateMiddleware' to MIDDLEWARE after "
        "'django.contrib.auth.middleware.AuthenticationMiddleware', or extend MIDDLEWARE "
        "instead of replacing it.",
    ),
    _e(
        "E249",
        "Terms acceptance is turned off",
        "api",
        "karni.accounts.api.views.TermsView; karni.accounts.api.views.TermsAcceptView",
        "terms/ and terms/accept/ are mounted only while KARNI_TERMS is set. A URLconf built "
        "while it was set answers 404 with this code once it is unset.",
        'Set KARNI_TERMS = {"version": "<version>", "url": "<where the terms are>"} to ask '
        "users to accept terms, or remove the client's call.",
    ),
    # E270-E279 / W540-W549 external tables, SQL views and a second database
    # (karni.db, experimental)
    _e(
        "E270",
        "An external model is managed by Django",
        "check",
        "karni.db.checks.check_database_options",
        "`class Karni: external = True` says another system owns the table or view, so Karni "
        "must never create, change or drop it. Django still migrates a model unless "
        "`Meta.managed = False`, so `migrate` would try to create or alter that table. The two "
        "declarations go together.",
        "Add `managed = False` to the model's `class Meta`, or remove `external = True` if "
        "Django should own the table.",
    ),
    _e(
        "E271",
        "Karni.database names a database that is not in DATABASES",
        "check",
        "karni.db.checks.check_database_options",
        "`class Karni: database = '<alias>'` sends the model's reads, writes and migrations to "
        "that alias of the DATABASES setting. An alias Django does not know fails on the first "
        "query.",
        "Add the alias to DATABASES (for example DATABASES['warehouse'] = "
        "env.db_url('WAREHOUSE_DATABASE_URL')), or fix the name in `class Karni`.",
    ),
    _e(
        "E272",
        "The table or view of an external model does not exist",
        "check",
        "karni.db.checks.check_external_tables (karni check)",
        "An external model reads a table or view another system owns, and Karni never creates "
        "it. `karni check` connected to the model's database and found no table or view with "
        "the model's Meta.db_table, so every query on the model would fail.",
        "Create the table or view in that database (a SQL view the project owns can come from "
        "a RunSQL migration), or fix Meta.db_table. A PostgreSQL table in another schema is "
        "written db_table = 'schema\".\"table'. Where the table cannot exist (a CI database), "
        "add 'karni.E272' to SILENCED_SYSTEM_CHECKS in that environment's settings.",
    ),
    _e(
        "E273",
        "An external model has a column its table or view lacks",
        "check",
        "karni.db.checks.check_external_tables (karni check)",
        "Every concrete field of an external model is a column Karni selects. A field whose "
        "column (its name, or db_column) is missing from the table or view makes every query "
        "on the model fail.",
        "Fix the field's name or db_column to match the column, remove the field, or "
        "regenerate the model from the table with `karni make model <Name> --external "
        "--table <table>` and keep what you need.",
    ),
    _e(
        "E274",
        "An external model's field type does not match its column",
        "check",
        "karni.db.checks.check_external_tables (karni check)",
        "The database reports a column type that cannot hold the field's values, for example "
        "a DateTimeField over a text column or an IntegerField over a date. Karni compares "
        "broad kinds only (numbers, text, dates, times, booleans, UUIDs, JSON, binary), and "
        "skips columns whose type the database does not report, so a reported mismatch is a "
        "real one.",
        "Change the field to the column's type (`karni make model <Name> --external --table "
        "<table> --dry-run` shows the type Django infers), or cast the column in the view.",
    ),
    _e(
        "E275",
        "class Karni: external, writable or database has a value of the wrong type",
        "check",
        "karni.db.checks.check_database_options",
        "`external` and `writable` are True or False, and `database` is the name of a "
        "DATABASES alias. Another value would be read in a way the code does not say.",
        "Write external = True, writable = True or database = '<alias>' (a non-empty string).",
    ),
    _e(
        "E276",
        "A relation joins models on different databases",
        "check",
        "karni.db.checks.check_database_options",
        "A foreign key, one-to-one or many-to-many field needs both tables in one database: "
        "Django joins them in SQL, and Karni's router refuses to relate rows across "
        "databases. A model on another database that inherits BaseModel has this problem "
        "too, because AuditedModel's created_by and updated_by point at the user table.",
        "Keep related models on the same database (the same Karni.database), or store the "
        "other row's key in a plain field. For a model Karni manages on another database, "
        "compose UUIDModel, TimestampedModel and SoftDeleteModel instead of BaseModel.",
    ),
    _e(
        "W540",
        "The database of an external model cannot be reached",
        "warning",
        "karni.db.checks.check_external_tables (karni check)",
        "`karni check` compares each external model with its table or view when the model's "
        "database answers. This one did not, so nothing was compared for it. That is not an "
        "error: the database may be outside this machine's reach (CI, a laptop).",
        "Check the alias in DATABASES (host, port, credentials, network) and run `karni "
        "check` again where the database is reachable. Add 'karni.W540' to "
        "SILENCED_SYSTEM_CHECKS where it never is.",
    ),
    _e(
        "W541",
        "Karni.writable on a model that is not external",
        "warning",
        "karni.db.checks.check_database_options",
        "`writable = True` only lifts the read-only default of an external model. Every other "
        "model is writable already, so the declaration does nothing.",
        "Remove `writable = True`, or add `external = True` (with Meta.managed = False) if "
        "another system owns the table.",
    ),
    _e(
        "W542",
        "Karni.database is declared but Karni's database router is not installed",
        "warning",
        "karni.db.checks.check_database_router",
        "A model declares `class Karni: database`, but DATABASE_ROUTERS does not list "
        "karni.db.DatabaseRouter (or a subclass), so Django sends the model to the default "
        "database. karni_settings() lists the router, so this happens when DATABASE_ROUTERS is "
        "replaced after the call.",
        "Add 'karni.db.DatabaseRouter' to DATABASE_ROUTERS, after your own routers (the first "
        "router with an answer wins). If your own router routes these models, add "
        "'karni.W542' to SILENCED_SYSTEM_CHECKS.",
    ),
    # E3xx admin
    _e(
        "E301",
        "KARNI_ADMIN_BASE is not a ModelAdmin class",
        "exception",
        "karni.admin.base",
        "Every auto-registered admin is built on this base class.",
        "Point KARNI_ADMIN_BASE at an importable django.contrib.admin.ModelAdmin subclass "
        "(default 'unfold.admin.ModelAdmin').",
    ),
    _e(
        "E302",
        "AdminMeta.inline_on is invalid",
        "exception",
        "karni.admin.inlines",
        "inline_on names the foreign key under whose parent the model is shown inline.",
        "Name a ForeignKey field of the model: class AdminMeta: inline_on = 'event'.",
    ),
    _e(
        "E303",
        "KARNI_ADMIN_LOGO is not a logo declaration",
        "exception",
        "karni.conf.admin_logo.unfold_logo_entries",
        "The admin logo is wired into UNFOLD from this one setting, so it must name static "
        "files unfold can serve.",
        "Set KARNI_ADMIN_LOGO = 'karni' for Karni's mark, or {'light': '<static path>', 'dark': "
        "..., 'icon': ...} with at least 'light'. Leave it unset for a text header.",
    ),
    # E304-E305 manage.py karni_makemigrations (karni build, experimental)
    _e(
        "E304",
        "karni_makemigrations --renames is not a rename list",
        "exception",
        "karni.management.commands.karni_makemigrations",
        'karni build passes the renames of the plan as JSON: {"models": [[app, old, new]], '
        '"fields": [[app, model, old, new]]}. Anything else cannot be written as a migration.',
        "Pass a JSON object with models and fields lists, or run karni build, which writes it.",
    ),
    _e(
        "E305",
        "An app has more than one latest migration, so the renames have no place",
        "exception",
        "karni.management.commands.karni_makemigrations.write_renames",
        "A rename migration follows the app's latest migration. Two migrations that both claim "
        "to be latest (two branches) leave no single one to follow.",
        "Run manage.py makemigrations --merge for the app, then karni build again.",
    ),
    # E31x the module catalog
    _e(
        "E310",
        "A module's manifest does not match the module",
        "test",
        "karni.testing.assert_module_manifest",
        "karni.module.toml is what karni modules, karni add, karni remove and the app spec "
        "read about a module. assert_module_manifest checks it parses, that the karni.modules "
        "entry point names the package, that its settings are the DEFAULTS fragment's, and "
        "that its models are the app's. Each listed line is one mismatch.",
        "Fix the manifest or the module as the line says: list every KARNI_<NAME>_* setting of "
        "conf.DEFAULTS under [provides.settings] with its type, list the app's models under "
        'provides.models, and add [project.entry-points."karni.modules"] <name> = '
        '"karni_<name>" to pyproject.toml, then reinstall the module. docs/modules.md lists '
        "every key.",
    ),
    # E340-E359 / W550-W559 tree models (karni.models.TreeModel, karni.tree, experimental)
    _e(
        "E340",
        "A tree node's new parent is the node itself or a node below it",
        "exception",
        "karni.models.TreeModel.check_parent (save, clean, move_to); the API answers 400",
        "A parent below the node would make the branch its own ancestor: a cycle. Every walk "
        "stays safe on such data, but the nodes on the cycle drop out of the tree, so Karni "
        "refuses the write before any SQL.",
        "Choose a parent outside the node's branch (or None for a root). To swap two nodes, "
        "move the lower one out of the branch first. In the API, POST <id>/move/ with another "
        "parent.",
    ),
    _e(
        "E341",
        "A tree node with live children cannot be deleted alone",
        "exception",
        "karni.models.TreeModel.delete; the API answers 409",
        "A soft-deleted node hides its whole branch. Deleting a node that still has live "
        "children would hide them too, without anyone deciding that, so delete() refuses and "
        "the answer counts the children.",
        "Move the children to another parent first, or delete the whole branch on purpose: "
        "node.delete_branch(), or DELETE <id>/?branch=true in the API (write access to every "
        "node of the branch).",
    ),
    _e(
        "E342",
        "A tree endpoint got a parameter it cannot use",
        "api",
        "karni.api.tree (tree/, move/, ?parent=, ?descendants_of=, ?branch=)",
        "The tree endpoints take keys of the model (?root=, ?parent=, ?descendants_of=, the "
        "parent of move/), a whole number of levels (?depth=, from 1 to the viewset's "
        "tree_max_depth) and true or false (?branch=). A key must name a node the requester "
        "may read.",
        "Send a key of the model (or null for ?parent= and move/'s parent), a depth within the "
        "limit the message names, and branch=true or branch=false.",
    ),
    _e(
        "E343",
        "A tree method got an argument it cannot use",
        "exception",
        "karni.managers.TreeQuerySet (walk, descendants, ancestors, subtree_ids); "
        "karni.models.TreeModel.move_to",
        "A walk starts from rows of the model, their keys or a queryset of the model. A row of "
        "another model, an unsaved row or a malformed key names no node. move_to() takes a "
        "position only on an OrderedTreeModel, as a whole number from 0.",
        "Pass saved rows of the model or their keys. Drop the position on a TreeModel, or "
        "inherit OrderedTreeModel to order siblings.",
    ),
    _e(
        "E344",
        "A tree model's default manager has no tree walks",
        "check",
        "karni.checks.check_tree_models",
        "TreeModel's manager (karni.managers.TreeManager) carries roots(), children(), "
        "ancestors(), descendants() and subtree_ids(), and the tree endpoints use them. A base "
        "listed before TreeModel (class Region(BaseModel, TreeModel)) supplies its own "
        "`objects` first, so the walks are missing.",
        "List TreeModel first: class Region(TreeModel, BaseModel). A custom manager must be "
        "built on karni.managers.TreeQuerySet, the way TreeManager is.",
    ),
    _e(
        "E345",
        "A tree model's parent is not a foreign key to the model itself",
        "check",
        "karni.checks.check_tree_models",
        "Every walk joins a node to its parent through the `parent` column, so `parent` must "
        "stay a nullable ForeignKey to the same model.",
        "Remove the redeclared `parent` field, or declare it as models.ForeignKey('self', "
        "null=True, blank=True, on_delete=models.PROTECT, related_name='children').",
    ),
    # E360-E379 per-user grants (karni.accounts.grants, experimental)
    _e(
        "E360",
        "A user grant's permission pattern matches no permission",
        "exception",
        "karni.accounts.grants.check",
        "A user grant names its permission as a KARNI_ROLES grant does: 'app_label.model:action', "
        "with '*' for either part, or '*' alone. A pattern that is malformed or matches no "
        "permission of the project would grant nothing, so it is refused when the grant is "
        "written (the API, the admin, karni.accounts.grants.grant or full_clean()).",
        "Write the key as karni context or GET permissions/matrix/ lists it (e.g. "
        "'shop.order:view'), and declare a model's extra actions in `class Karni: actions = "
        "[...]` before granting them.",
    ),
    _e(
        "E361",
        "A user grant's scope does not fit the permissions it covers",
        "exception",
        "karni.accounts.grants.check",
        "The scope is one a role grant takes: 'all', 'own', 'related:<key>', 'custom:<name>' "
        "or 'tree:<path>'. 'own' needs the model's owner field, 'related:<key>' its "
        "Karni.scope_paths[key], 'custom:<name>' a scope registered with register_scope() and "
        "'tree:<path>' a path from the model to a tree model. "
        "An explicit key whose model lacks it is refused, and a wildcard pattern must keep at "
        "least one model that has it.",
        "Pick a scope from the model's options in GET permissions/matrix/, declare the owner "
        "field or scope path in `class Karni`, or register the custom scope at startup.",
    ),
    _e(
        "E362",
        "A user grant's targets are invalid",
        "exception",
        "karni.accounts.grants.check",
        "targets lists the row ids a scope that points at rows reaches: a 'related:<key>' grant "
        "with targets reaches the rows whose Karni.scope_paths[key] is one of them, and a "
        "'tree:<path>' grant the rows under those nodes of the tree. Targets are "
        "a list of ids (text, integers or UUIDs), only for such a scope, and each must be a value "
        "the scope path's field takes.",
        "Pass a list of ids of the related model, e.g. targets=[3, 7] for an integer key, drop "
        "targets for an 'all', 'own' or 'custom:' grant, or grant 'related:<key>' instead.",
    ),
    _e(
        "E363",
        "The operator may not give this user grant",
        "api",
        "karni.accounts.grants.refusals",
        "Nobody grants what they do not hold, as in the permission matrix: the operator must "
        "hold every permission the pattern reaches, at scope 'all' or at the same scope, and for "
        "a grant with targets their own targets under that scope must include each one. "
        "Nothing was written. Superusers and code that passes operator=None are not checked.",
        "Ask someone who holds the permission at that scope (or 'all') to give the grant, "
        "narrow the pattern, the scope or the targets to what you hold, or grant it from code "
        "with operator=None.",
    ),
    _e(
        "E364",
        "Per-user grants are turned off",
        "api",
        "karni.accounts.api.grants",
        "permissions/grants/ and its routes are mounted only while KARNI_USER_GRANTS is True. "
        "A URLconf built while it was True answers 404 with this code once it is False. While "
        "it is False, user grants are not read and grant nothing.",
        "Set KARNI_USER_GRANTS = True (or features: user_grants: true in karni.yaml, then karni "
        "build) to use per-user grants.",
    ),
    _e(
        "E365",
        "karni.accounts.grants.change() was given a field it does not set",
        "exception",
        "karni.accounts.grants.change",
        "change() sets a grant's permission, scope, targets, expires_at and reason. The user a "
        "grant belongs to, granted_by and the timestamps are not changed this way: a grant for "
        "another user is a new grant, and granted_by follows the operator.",
        "Pass only permission, scope, targets, expires_at or reason. To move access to another "
        "user, revoke() this grant and grant() a new one.",
    ),
    # E490-E499 / W620-W629 the tree scope (karni.accounts.tree_scope, experimental)
    _e(
        "E490",
        "A tree:<path> scope does not end at a tree model",
        "check",
        "karni.accounts.tree_scope.resolve_path; karni.checks.check_tree_scopes (KARNI_ROLES); "
        "tree_scope() in a Where",
        "tree:<path> reaches the rows whose <path> is a node the user holds or a node below it, "
        "so each step of the path must be a relation of the model before it (a foreign key, a "
        "one-to-one, a many-to-many or a reverse relation) and the last one must point at a "
        "model on karni.models.TreeModel. A path that does not resolve could only ever reach no "
        "row, so Karni refuses it at startup, in KARNI_ROLES and wherever tree_scope() names it.",
        "Name the row's relation to the tree model, through relations when needed: "
        "tree:region, tree:product__categories. Make the target a tree model (class "
        "Region(TreeModel, BaseModel)), or grant another scope.",
    ),
    _e(
        "E491",
        "The access/ endpoint of a tree resource got a parameter it cannot use",
        "api",
        "karni.api.tree (GET <resource>/access/?permission=)",
        "?permission= keeps the grants of the permissions it matches, written as a KARNI_ROLES "
        "pattern: 'app_label.model:action' with '*' for either part, or '*' alone. Anything "
        "else would match no grant and answer an empty forest without saying why.",
        "Send a permission key such as ?permission=shop.order:view (or a pattern such as "
        "shop.order:*), or leave the parameter out to count every tree grant.",
    ),
    _e(
        "W620",
        "A role grant of a tree scope gives its members no node",
        "warning",
        "karni.checks.check_tree_scopes (karni check)",
        "A role grant of tree:<path> reaches the rows under the node the user holds in the "
        "attribute named after the path's last step (tree:region and tree:store__region read "
        "user.region), as related:<key> compares user.<key>. The user model has no such "
        "attribute, so the role gives each member no node and no row. A tree grant never "
        "falls back to every row.",
        "Give the user model the attribute (a field or a property holding a node of the tree, "
        "e.g. region), or give each user their nodes with user grants of the same scope "
        "(features: user_grants, then karni.accounts.grants.grant(..., targets=[...])). "
        "Silence it with SILENCED_SYSTEM_CHECKS = ['karni.W620'] when user grants give the "
        "nodes on purpose.",
    ),
    # E4xx events, listeners, schedules, Celery
    _e(
        "E401",
        "A queued listener is not a module-level function",
        "exception",
        "karni.events.queued",
        "A queued listener runs on a Celery worker, which finds it by its dotted name. Nested "
        "functions and lambdas have none.",
        "Define the listener at the top level of <app>/listeners.py, or queue an existing "
        "task with queued('app.tasks.task_name').",
    ),
    _e(
        "E402",
        "A listener registration is invalid",
        "exception",
        "karni.events",
        "Listeners connect to model events (on_created(Model), ...) and must be callables.",
        "Decorate a function, and pass a model class or an 'app_label.ModelName' string: "
        "@on_created(Event) or @on_created('events.Event').",
    ),
    _e(
        "E403",
        "A Celery task cannot be found",
        "exception",
        "karni.celery.resolve_task",
        "Tasks are found by dotted name, and Celery autodiscovers only @shared_task functions in "
        "installed apps' tasks.py.",
        "Check the dotted name, and that the function is decorated with @shared_task in "
        "an installed app's tasks.py.",
    ),
    _e(
        "E404",
        "A schedule declaration is invalid",
        "exception",
        "karni.schedule (every, cron)",
        "Schedules are stored by django-celery-beat: the task must be a task or its dotted "
        "name, and name/args/kwargs/options must be plain JSON-serializable values.",
        "Pass a @shared_task or 'app.tasks.task_name', a non-empty name, args as a list, "
        "kwargs and options as dicts of plain values (ids, not objects).",
    ),
    _e(
        "E405",
        "A schedule's interval or cron expression is invalid",
        "exception",
        "karni.schedule (every, cron)",
        "Intervals are whole positive seconds, and cron expressions have five fields.",
        "Use every('15m') / every(minutes=15) (s, m, h, d units), or cron('0 3 * * *') "
        "('minute hour day-of-month month day-of-week').",
    ),
    _e(
        "E406",
        "Two schedules share a name",
        "check",
        "karni.schedule; karni.checks.check_schedules",
        "Schedule names become django-celery-beat PeriodicTask names, so they must be "
        "unique across the project.",
        "Pass a distinct name=... to one of the two declarations the message names.",
    ),
    _e(
        "E407",
        "No schedule has that name",
        "exception",
        "karni.schedule.run_now; karni schedule run",
        "Schedules are looked up by name.",
        "List them with `karni schedule list` and use one of the names shown.",
    ),
    _e(
        "E408",
        "A scheduled task failed when run by hand",
        "exception",
        "karni_schedules management command; karni schedule run",
        "`karni schedule run` executes the task in-process so failures show immediately.",
        "Read the task's own error in the message and fix the task. Then re-run it with "
        "`karni schedule run <name>`.",
    ),
    # E5xx settings and optional dependencies
    _e(
        "E501",
        "An optional dependency is not installed",
        "exception",
        "karni.conf.sentry, karni.storage, karni.accounts.twofa, karni.api.search.postgres, "
        "karni.testing.assert_crud",
        "Optional features (Sentry, S3 storage, thumbnails, 2FA, PostgreSQL search, image "
        "uploads in assert_crud) need extra packages that a minimal install leaves out.",
        "Install the extra the message names, e.g. pip install 'karni[sentry]', "
        "'karni[s3]', 'karni[images]', 'karni[2fa]' or 'psycopg[binary]'.",
    ),
    _e(
        "E502",
        "Unknown settings profile",
        "exception",
        "karni.conf.karni_settings",
        "karni_settings() picks dev or prod defaults from DJANGO_ENV.",
        "Set DJANGO_ENV to one of the profiles the message lists, or pass env_name= to "
        "karni_settings().",
    ),
    _e(
        "E503",
        "A module's settings fragment is invalid",
        "exception",
        "karni.conf (karni.settings entry points)",
        "Installed modules contribute default settings. A fragment may only add new top-level "
        "names, so installing a module never changes a setting you rely on.",
        "Fix or upgrade the module the message names. Module authors: export a dict of new "
        "names only.",
    ),
    _e(
        "E504",
        "Karni settings failed validation",
        "exception",
        "karni.conf.validation.validate_settings (at startup)",
        "Settings are validated once at boot so a bad value fails the deploy, not the "
        "first request that reads it.",
        "Fix every setting the message lists. KARNI_VALIDATE = False skips validation "
        "(not recommended).",
    ),
    _e(
        "E505",
        "The welcome page is reachable with DEBUG off",
        "check",
        "karni.checks.check_welcome_route",
        "The welcome page (karni.welcome) introspects the project at request time (models, "
        "modules, status checks, the agent context) for first boot in development. Served in "
        "production, it would describe the deployment to anyone who opens the site.",
        "Mount it only through `*karni.welcome.welcome_urls()` at the end of urlpatterns "
        "(it returns no route when DEBUG is False) and remove any hand-written "
        "path('', WelcomeView.as_view()).",
    ),
    _e(
        "W501",
        "The throttle cache is private to each process",
        "warning",
        "karni.checks.check_throttle_cache",
        "DRF keeps rate-limit counters in CACHES['default']. With DEBUG off, a locmem or "
        "dummy backend gives every worker its own counters, so the login, registration and "
        "password-reset limits are multiplied by the worker count.",
        "Point CACHES['default'] at a backend every worker shares (Redis, which Karni uses by "
        "default, or the database cache), or silence karni.W501 for a single-process deployment.",
    ),
    _e(
        "E506",
        "A setting names a dotted path that cannot be imported",
        "exception",
        "karni.imports.import_setting (KARNI_SEARCH_PROVIDER, KARNI_API_ROUTER, "
        "KARNI_ADMIN_SITE, KARNI_THUMBNAILER, ...)",
        "Settings that name a class or function by dotted path are resolved when first used. A "
        "typo or a package missing from the environment would otherwise surface as a bare "
        "ModuleNotFoundError far from the setting.",
        "Fix the path the message names ('package.module.Object') or install the package "
        "that provides it.",
    ),
    _e(
        "E507",
        "KARNI_CACHE names an unknown cache backend",
        "exception",
        "karni.conf (KARNI_CACHE)",
        "The default cache (throttle counters, response cache, locks) is Redis at REDIS_URL. "
        "`locmem` is the in-process alternative for a host run without Redis.",
        "Set KARNI_CACHE to `redis` (the default) or `locmem`. For anything else, define CACHES "
        "yourself in settings.py.",
    ),
    # W51x and W520 deploy checks (manage.py check --deploy, karni check --deploy)
    _e(
        "E508",
        "A setting is assigned where it cannot take effect",
        "check",
        "karni.checks.check_call_time_settings",
        "karni_settings() reads a few settings during the call to compute others: "
        "KARNI_AUTH_MODE, KARNI_2FA, KARNI_SOCIAL_AUTH and KARNI_SOCIAL_PROVIDERS decide "
        "INSTALLED_APPS and MIDDLEWARE, KARNI_FRONTEND_URL feeds CSRF_TRUSTED_ORIGINS, "
        "KARNI_AUTH_THROTTLE_RATES the throttle rates, KARNI_JSON_LOGS builds LOGGING, "
        "KARNI_CACHE builds CACHES and KARNI_STORAGE builds STORAGES. Assigned after the "
        "call, such a setting changes none of them, and the project would run with the "
        "settings computed from the old value. A KARNI_ADMIN_LOGO with no SITE_LOGO entry "
        "in UNFOLD (UNFOLD replaced after the call) shows no logo either.",
        "Move the assignment above the `karni_settings(globals())` line, pass it as a "
        "keyword (`karni_settings(globals(), KARNI_AUTH_MODE='session')`) or set its "
        "environment variable in .env. For the logo, change UNFOLD in place instead of "
        "replacing it.",
    ),
    _e(
        "E509",
        "Sign-in with an ID token needs the cryptography package",
        "exception",
        "karni.conf.validation (at startup), karni.accounts.social_token",
        "Google, Microsoft and Apple sign their ID tokens with RS256 (an EC key uses ES256). "
        "PyJWT verifies those only with the cryptography package, which a plain install of "
        "Karni leaves out.",
        "Run pip install 'karni[social-token]', or empty KARNI_SOCIAL_TOKEN_PROVIDERS.",
    ),
    _e(
        "W510",
        "DEBUG is on in a deployment",
        "warning",
        "karni.security.checks.check_debug (deploy)",
        "With DEBUG on, an error page shows the settings, the source code around the error "
        "and the request to whoever triggers it. Django also keeps every query in memory, "
        "and the content security policy only reports instead of blocking.",
        "Run production with DJANGO_ENV=prod, which turns DEBUG off, or set DEBUG=False in "
        "the environment.",
    ),
    _e(
        "W511",
        "SECRET_KEY is weak or a development key",
        "warning",
        "karni.security.checks.check_secret_key (deploy)",
        "SECRET_KEY signs sessions, password-reset and verification tokens and every signed "
        "value. The scaffold's `karni-insecure-dev-key` is public, and a short or plain key "
        "can be guessed. Either way anyone could forge them.",
        "Set SECRET_KEY in the production environment to a random value of at least 50 "
        'characters, for example the output of `python -c "from django.core.management.utils '
        'import get_random_secret_key; print(get_random_secret_key())"`. Never commit it.',
    ),
    _e(
        "W512",
        "ALLOWED_HOSTS is empty or allows every host",
        "warning",
        "karni.security.checks.check_allowed_hosts (deploy)",
        "Django builds absolute links, including password-reset and verification links, from "
        "the request's Host header. With '*' an attacker picks the host those links point at. "
        "An empty list answers no host at all once DEBUG is off.",
        "Set ALLOWED_HOSTS in the environment to the site's host names, comma-separated, e.g. "
        "ALLOWED_HOSTS=example.com,www.example.com.",
    ),
    _e(
        "W513",
        "CSRF_TRUSTED_ORIGINS is missing, a wildcard or plain http",
        "warning",
        "karni.security.checks.check_csrf_trusted_origins (deploy)",
        "Django accepts a form or a session-mode API call only from a trusted origin. Behind "
        "a proxy, and for a frontend on another host, that origin must be listed. A wildcard "
        "or an http:// origin trusts more than the site, and session mode adds "
        "KARNI_FRONTEND_URL, whose default is http://localhost:5173.",
        "Set CSRF_TRUSTED_ORIGINS in the environment to the site's https origins, "
        "comma-separated, e.g. CSRF_TRUSTED_ORIGINS=https://example.com. In session mode also "
        "set KARNI_FRONTEND_URL to the frontend's https URL.",
    ),
    _e(
        "W514",
        "HSTS is off",
        "warning",
        "karni.security.checks.check_hsts (deploy)",
        "Without Strict-Transport-Security a browser may still try plain http, for example "
        "from a typed address or an old link, and a network attacker can read or change that "
        "traffic before the redirect to https.",
        "Run production with DJANGO_ENV=prod, which sets SECURE_HSTS_SECONDS to one year with "
        "subdomains and preload. To try a new domain first, set SECURE_HSTS_SECONDS=3600 in the "
        "environment and raise it once https works.",
    ),
    _e(
        "W515",
        "The session or CSRF cookie is not marked secure",
        "warning",
        "karni.security.checks.check_secure_cookies (deploy)",
        "A cookie without the Secure flag is also sent over plain http, where anyone on the "
        "network can read it and take over the session.",
        "Run production with DJANGO_ENV=prod, which sets SESSION_COOKIE_SECURE and "
        "CSRF_COOKIE_SECURE to True. If you define them in settings.py, set both to True.",
    ),
    _e(
        "W516",
        "The admin is at /admin/",
        "warning",
        "karni.security.checks.check_admin_path (deploy)",
        "Scanners try /admin/ on every site, so a login form there receives password guesses "
        "all day. Another path keeps it off their lists. It is not a substitute for strong "
        "passwords, it only removes the noise.",
        "Set KARNI_ADMIN_PATH in the environment to a path nobody guesses, with a trailing "
        "slash, e.g. KARNI_ADMIN_PATH=staff-7f3a9c/. The scaffold's urls.py mounts the admin "
        "at that setting.",
    ),
    _e(
        "W517",
        "CORS allows every origin",
        "warning",
        "karni.security.checks.check_cors (deploy)",
        "CORS decides which other sites may call the API from a visitor's browser. Allowing "
        "every origin lets any site read what the visitor can read, and with "
        "CORS_ALLOW_CREDENTIALS (on in session mode) it does so with the visitor's cookies. "
        "The development profile allows every origin, so a deployment that runs with "
        "DJANGO_ENV=dev does too.",
        "Run production with DJANGO_ENV=prod and list the frontend's origins in "
        "CORS_ALLOWED_ORIGINS, e.g. CORS_ALLOWED_ORIGINS=https://app.example.com. Remove "
        "CORS_ALLOW_ALL_ORIGINS and any regex that matches every origin.",
    ),
    _e(
        "W518",
        "No enforced Content-Security-Policy",
        "warning",
        "karni.security.checks.check_csp_present (deploy)",
        "The Content-Security-Policy tells the browser which scripts may run, so an injected "
        "script does not. Karni's SecurityHeadersMiddleware sends it, but not when it is "
        "missing from MIDDLEWARE or KARNI_CSP is None, and it only reports while DEBUG or "
        "KARNI_CSP_REPORT_ONLY is on.",
        "Keep karni.security.SecurityHeadersMiddleware in MIDDLEWARE (karni_settings() adds it), "
        "leave KARNI_CSP a dict, and run with DEBUG off and KARNI_CSP_REPORT_ONLY unset. If a "
        "proxy sends the policy instead, add 'karni.W518' to SILENCED_SYSTEM_CHECKS.",
    ),
    _e(
        "W519",
        "The Content-Security-Policy lets any script run",
        "warning",
        "karni.security.checks.check_csp_scripts (deploy)",
        "A script-src with *, http:, https:, data:, 'unsafe-eval' or 'unsafe-inline' (without a "
        "nonce or hash) lets an injected script run, which defeats the policy. The admin and "
        "the API docs pages get the extra sources they need on their own pages only.",
        "Remove those sources from KARNI_CSP['script-src']. Allow a script host by its origin, "
        "e.g. https://js.example.com, and an inline script by its hash with "
        "karni.security.script_hash() on the one view that needs it (@csp_extend).",
    ),
    _e(
        "W520",
        "Production email is not set up",
        "warning",
        "karni.security.checks.check_email (deploy)",
        "Password resets, account emails and the notifications of a site's forms go out by "
        "email. The console, locmem, dummy and file backends deliver nothing, and a sender at "
        "localhost (Django's default, webmaster@localhost) is refused by mail servers, so "
        "every email is lost without an error.",
        "Set EMAIL_URL to the mail server (smtp+tls://user:password@smtp.example.com:587, "
        "smtps:// for SSL) and DEFAULT_FROM_EMAIL to an address of the site's domain "
        '("Example Site <noreply@example.com>") in the production environment (.env.prod). '
        ".env.prod.example lists them. A project that sends no email adds 'karni.W520' to "
        "SILENCED_SYSTEM_CHECKS.",
    ),
    # W53x integer primary keys (karni.models.BigIntBaseModel, experimental)
    _e(
        "W530",
        "Anyone may read a resource whose ids can be guessed",
        "warning",
        "karni.checks.check_public_integer_keys",
        "The model has an integer primary key (BigIntBaseModel or an AutoField), its detail "
        "route looks rows up by that key, and its read access admits anonymous callers. "
        "Integer ids are sequential, so a visitor learns how many rows there are and can walk "
        "the detail URLs one id after the other, including rows no list links to.",
        "Give the model a UUID key (inherit BaseModel) or look rows up by a slug "
        '(lookup_field = "slug" on the viewset). When the ids may be public, write '
        "`# karni: allow(public-integer-key): <reason>` above the viewset class, or add "
        "'karni.W530' to SILENCED_SYSTEM_CHECKS for the whole project.",
    ),
    # E52x running in production (karni.deploy)
    _e(
        "E520",
        "The deploy checks failed when the container started",
        "exception",
        "karni.deploy.entrypoint (the production image's ENTRYPOINT)",
        "The production image runs `karni check --deploy` before its command, so a "
        "container with DEBUG on, the scaffold's SECRET_KEY, open hosts or another unsafe "
        "value never serves a request. Each finding printed before the E520 line has its own "
        "code (karni.W510 to karni.W520, a Django security warning, or a karni check hook).",
        "Set the production values in the environment the container gets (.env.prod for "
        "docker-compose.prod.yml) and start it again: `karni explain W511` and the others "
        "say what each value must be. In an emergency KARNI_SKIP_DEPLOY_CHECK=1 starts it "
        "without the checks, logged on every start. Remove it once the values are fixed.",
    ),
    _e(
        "E521",
        "A backup failed",
        "exception",
        "karni.deploy.backup (the backup service, karni-backup)",
        "A backup that fails quietly is found missing on the day it is needed, so the backup "
        "service reports the failure in its log, and its health check turns unhealthy until "
        "a backup succeeds.",
        "Read the line after E521: it names the step (pg_dump, pg_restore, psql, the media "
        "archive, S3) and its error. Check DATABASE_URL, that the client tools match the "
        "database's major version (the backup image's POSTGRES_VERSION), the free space in "
        "KARNI_BACKUP_DIR and, with KARNI_BACKUP_S3_BUCKET, the AWS_* credentials. Then run "
        "`docker compose -f docker-compose.prod.yml exec backup karni-backup run`.",
    ),
    # E530-E549 / W630-W639 navigation from data (karni.navigation, experimental)
    _e(
        "E530",
        "KARNI_NAVIGATION is not valid",
        "exception",
        "karni.navigation.settings_problems (startup validation), karni.navigation.models.NavItem",
        "KARNI_NAVIGATION is a list of items and groups, 'db' or None. An item is a dict with "
        "a label and a route (an app path that starts with /), and may have an icon name, an "
        "integer order and what it requires. A group is a dict with a label and children, and "
        "no route. A menu Karni cannot read would answer every request with an error.",
        "Fix the entry the message names, e.g. {'label': 'Products', 'route': '/products', "
        "'icon': 'box', 'requires': 'catalog.product:view'}, or {'label': 'Catalog', "
        "'children': [...]} for a group.",
    ),
    _e(
        "E531",
        "KARNI_NAVIGATION = 'db' without the karni.navigation app",
        "exception",
        "karni.navigation.settings_problems (startup validation)",
        "The database menu lives in the NavItem table, which comes with the karni.navigation "
        "app. Karni does not install the app for every project, so a project that keeps its "
        "menu in the settings gains no table.",
        "Add 'karni.navigation' to INSTALLED_APPS and run migrate, or set KARNI_NAVIGATION to a "
        "list of items.",
    ),
    _e(
        "E532",
        "A navigation entry's requirement is not valid",
        "exception",
        "karni.navigation.requirement_problem (startup validation, NavItem.requires)",
        "An entry requires 'public' (everyone), 'authenticated' (every signed-in user) or a "
        "permission pattern written as in KARNI_ROLES grants, so role grants and per-user "
        "grants open it the way they open the API.",
        "Write 'public', 'authenticated', or a pattern such as 'catalog.product:view', "
        "'catalog.*:view' or '*'.",
    ),
    _e(
        "E533",
        "A navigation item links to a route no page serves",
        "check",
        "karni.navigation.checks.check_navigation (karni check)",
        "karni check compares each item's route with the pages of the frontend: the path: "
        "entries of the KARNI_NAVIGATION_PAGES files (frontend/src/routes.tsx, where karni "
        "make page and karni build register each page). A menu entry that leads to no page "
        "is a dead link for every user who sees it.",
        "Fix the route (the message names the closest one), add the page with karni make page, "
        "or remove the item. Add 'karni.E533' to SILENCED_SYSTEM_CHECKS if the page is "
        "registered somewhere karni check does not read, or list that file in "
        "KARNI_NAVIGATION_PAGES.",
    ),
    _e(
        "E534",
        "A navigation entry requires a permission the project does not have",
        "check",
        "karni.navigation.checks.check_navigation (karni check)",
        "A permission pattern opens an entry for users who hold a grant for a permission it "
        "names. A pattern that names no permission of the project (a typo, a model that was "
        "renamed) opens it for nobody but a superuser.",
        "Name an existing permission as karni context or GET permissions/matrix/ lists it "
        "(app_label.model:action, lowercase), or write 'authenticated' or 'public'.",
    ),
    _e(
        "E535",
        "Navigation is turned off",
        "api",
        "karni.navigation.api.NavigationView",
        "GET /api/navigation/ is mounted only while KARNI_NAVIGATION is set. A URLconf built "
        "while it was set answers 404 with this code once it is unset.",
        "Set KARNI_NAVIGATION to a list of items, or to 'db' with the karni.navigation app "
        "installed (or navigation: in karni.yaml, then karni build).",
    ),
    _e(
        "E536",
        "A navigation entry has both a route and entries",
        "exception",
        "karni.navigation.models.NavItem.clean (the admin form)",
        "An entry with a route is a link. A group is an entry without a route that holds other "
        "entries. One entry cannot be both: the menu shows a link with no entries under it.",
        "Give the group no route and put the link inside it as an entry of its own, or choose "
        "a group as the parent.",
    ),
    _e(
        "W630",
        "The database menu could not be read",
        "warning",
        "karni.navigation.checks.check_navigation (karni check)",
        "With KARNI_NAVIGATION = 'db', karni check reads the NavItem rows to compare their "
        "routes and requirements. The database did not answer, or the karni.navigation "
        "migration has not run, so nothing was compared. That is not an error: the database "
        "may be outside this machine's reach.",
        "Run migrate, check DATABASES, and run karni check again where the database answers. "
        "Add 'karni.W630' to SILENCED_SYSTEM_CHECKS where it never does.",
    ),
    _e(
        "W631",
        "No frontend pages file to compare the menu with",
        "warning",
        "karni.navigation.checks.check_navigation (karni check)",
        "karni check reads the pages from the KARNI_NAVIGATION_PAGES files (default "
        "frontend/src/routes.tsx). None of them exists, so the menu's routes were not compared.",
        "List the file that registers the frontend's routes in KARNI_NAVIGATION_PAGES, or set "
        "it to [] when the menu serves a client whose pages Karni cannot read (a mobile app).",
    ),
    # E6xx testing and seeding
    _e(
        "E601",
        "The resource under test is not routed",
        "test",
        "karni.testing.assert_crud / assert_isolated",
        "assert_crud tests a resource through its URLs, exactly as clients reach it.",
        "Route the viewset (karni make viewset <Model>, or auto_register), or pass the "
        "viewset class or its route name.",
    ),
    _e(
        "E602",
        "The API does not behave as its access declaration promises",
        "test",
        "karni.testing.assert_crud",
        "assert_crud derives every expected outcome (allowed actions, 403/404 denials, "
        "pagination, filtering, owner stamping, response schema) from the viewset's access and "
        "the OpenAPI schema. Each listed failure is a real difference.",
        "Fix each failure in the report: usually the access declaration, a custom "
        "get_queryset, or a serializer that does not match the schema. skip=[...] "
        "excludes a check that genuinely does not apply.",
    ),
    _e(
        "E603",
        "checks=/skip= names unknown checks",
        "exception",
        "karni.testing.assert_crud; assert_row_hidden; assert_admin_row_hidden",
        "Skipping (or selecting) a check that does not exist would hide nothing and mislead "
        "the reader.",
        "Use the check names the message lists.",
    ),
    _e(
        "E604",
        "A request raised an exception during assert_crud",
        "test",
        "karni.testing.assert_crud",
        "The API raised instead of answering, so the check could not run.",
        "Read the exception in the message and fix the view, serializer or data it names.",
    ),
    _e(
        "E605",
        "assert_isolated cannot isolate this resource",
        "exception",
        "karni.testing.assert_isolated; karni.testing.isolation",
        "Isolation is proved along a dimension (owner, tenant, ...) that the resource's "
        "access actually filters by.",
        "Give the resource an Owned(...) access (or install the module providing the "
        "dimension), and name only registered dimensions.",
    ),
    _e(
        "E606",
        "Rows leak to a user who must not see them",
        "test",
        "karni.testing.assert_isolated; assert_row_hidden; assert_admin_row_hidden",
        "One owner (or tenant) could read or change another's rows, or learn that a row "
        "outside their scope exists (a 403 where a missing row gets 404, a count, an "
        "expanded or exported related row): a data leak.",
        "Fix what each listed line names: usually the viewset's access (Owned('<owner "
        "path>'), a scoped grant, the tenant scope), or custom get_queryset / get_object / "
        "serializer / @action code that bypasses it.",
    ),
    _e(
        "E607",
        "There is no OpenAPI schema snapshot yet",
        "test",
        "karni.testing.assert_schema_snapshot",
        "CI compares the API schema with a committed snapshot, so an accidental breaking change "
        "fails the build. CI never writes snapshots.",
        "Generate it locally with the command in the message and commit the file.",
    ),
    _e(
        "E608",
        "The OpenAPI schema changed",
        "test",
        "karni.testing.assert_schema_snapshot",
        "Clients (and the generated frontend types) depend on the schema, so this change would "
        "reach them.",
        "If the change is intended, accept it with the command in the message and commit the "
        "snapshot. Otherwise, revert the change that caused it.",
    ),
    _e(
        "E609",
        "No factory can be built for this model",
        "exception",
        "karni.testing.factories",
        "Factories create rows of concrete models.",
        "Pass a concrete model class or an 'app_label.Model' string.",
    ),
    _e(
        "E610",
        "A factory cannot generate a value for a field",
        "exception",
        "karni.testing.factories",
        "Values are inferred from field types and names, and some custom fields have no safe "
        "default.",
        "Pass the value (create(Model, field=...)) or define an explicit factory in "
        "<app>/factories.py.",
    ),
    _e(
        "E611",
        "Required relations form a loop",
        "exception",
        "karni.testing.factories; karni.seeding",
        "Each row needs its required relation to exist first. In a loop, no order works.",
        "Make one of the foreign keys nullable, pass an existing row for that field, or "
        "seed one model yourself in a Seeder.seed() override.",
    ),
    _e(
        "E612",
        "Seeding keeps hitting a database constraint",
        "exception",
        "karni.seeding",
        "Generated values collided with a unique or check constraint on every attempt.",
        "Give the clashing fields distinct values in a seeder (karni make seeder <Model>), "
        "e.g. with factory.Sequence.",
    ),
    _e(
        "E613",
        "Seeding a row failed",
        "exception",
        "karni.seeding",
        "The model rejected a generated row (model validation or save() logic).",
        "Override Seeder.seed() for the model (karni make seeder <Model>) and create the "
        "rows yourself with context.create(..., field=value).",
    ),
    _e(
        "E614",
        "karni seed was given invalid arguments",
        "exception",
        "karni seed; manage.py karni_seed",
        "--model takes app_label.Model names and --count a non-negative number.",
        "Fix the argument the message names, e.g. karni seed --model events.Event --count 20.",
    ),
    _e(
        "E615",
        "karni seed refuses to run with DEBUG = False",
        "exception",
        "karni seed; manage.py karni_seed",
        "DEBUG = False usually means a production database, and seeding creates a demo "
        "superuser with a known password.",
        "Seed a development database. If you really mean it, pass --force.",
    ),
    _e(
        "E616",
        "A hidden-row check has nothing to prove against",
        "test",
        "karni.testing.assert_row_hidden; assert_admin_row_hidden",
        "A row-scope check only means something when the client can list the resource and sees "
        "some row (the positive control). A role-level refusal or an empty list hides every row "
        "alike, so every check would pass vacuously.",
        "Pass a client (or staff user) that can list the resource, and a row it does see as "
        "visible=. Test role-level refusals with assert_crud's denials instead.",
    ),
    _e(
        "E617",
        "karni seed refuses to add demo rows to a table that already has rows",
        "exception",
        "karni seed; manage.py karni_seed",
        "Seeded rows carry no mark, so seed cannot tell its own rows from real content. Adding "
        "random demo rows to a table that holds content mixes the two for good. Any row in a "
        "table the run would write to counts (the user table is left out: users are matched "
        "by login and never deleted).",
        "Pass --reset to wipe the project's tables first, --force to add demo rows on top, "
        "--model to narrow the run to empty tables, or load real content with karni load.",
    ),
    _e(
        "E618",
        "A public page fails the page checks",
        "test",
        "karni.testing.assert_pages",
        "assert_pages requests each page of a site and checks what visitors and search engines "
        "get: a 200, a title, a meta description, alt text on every image, same-site links that "
        "answer, and a 404 for a URL the site does not have. Each listed line is a page and a "
        "problem a visitor or a crawler would meet.",
        "Fix what each line names: usually the page's {% block title %} or {% block "
        'description %}, an img element without an alt attribute (alt="" for a decorative '
        "image), a link or {% static %} path to a URL that does not exist, or a catch-all "
        "route that should raise Http404. Turn a check off with require_title=False, "
        "require_description=False, require_alt=False, check_links=False or "
        "not_found_url=None, or leave links out with ignore=[...].",
    ),
    _e(
        "E619",
        "assert_pages was given no URLs",
        "exception",
        "karni.testing.assert_pages",
        "With no page to request, every check would pass without checking anything.",
        'Pass the site\'s pages, for example assert_pages(client, ["/", "/about/"]).',
    ),
    # E7xx agent tooling
    _e(
        "E701",
        "karni.rules.py is invalid",
        "exception",
        "karni.agent.overrides",
        "karni.rules.py adjusts the agent rules. It is read statically (never executed), so only "
        "literal values are allowed.",
        "Fix the line the message names. ADD/OVERRIDE/DISABLE/ADAPTERS take literal values. ADD "
        "uses codes like P001 with a non-empty 'rule'. OVERRIDE/DISABLE name only Karni K codes.",
    ),
    _e(
        "E702",
        "karni check found violations",
        "exception",
        "karni check; manage.py karni_check",
        "The architecture checks enforce the K rules (generated code is not hand-written, "
        "access is declared, and so on).",
        "Fix each listed violation (each names its K code, and `karni explain K106` explains "
        "one), or suppress a deliberate exception the way the violation describes.",
    ),
    _e(
        "E703",
        "A source file cannot be parsed",
        "exception",
        "karni.agent.check",
        "karni check reads your code statically, so a syntax error stops it.",
        "Fix the syntax error at the file and line in the message.",
    ),
    _e(
        "E704",
        "Karni's changelog is invalid",
        "exception",
        "karni.changelog",
        "karni upgrade reads the changelog to find and apply every breaking change.",
        "Maintainers: fix the entries the message lists (schema in karni/changelog/"
        "__init__.py). Users: reinstall karni-cli.",
    ),
    # E8xx import and export
    _e(
        "E801",
        "An import cannot proceed as asked",
        "api",
        "karni.transfer",
        "The mapping names a column the file lacks or a field the role may not write, the "
        "file has no header row, a commit was requested before the mandatory preview, or "
        "the model's import metadata (Karni.natural_key / import_key / import_lookup / "
        "import_transform / after_import) is malformed.",
        "Map columns to importable fields only (GET /<resource>/import/ lists them), "
        "preview before committing, and check the names in class Karni against the model.",
    ),
    _e(
        "E802",
        "The file format is not supported",
        "api",
        "karni.transfer.formats",
        "Import and export speak CSV and XLSX. Anything else is refused, and so is an upload "
        "whose format cannot be told from its name or content type.",
        "Upload a .csv or .xlsx file, or pass ?format=csv|xlsx. XLSX needs openpyxl (a core "
        "dependency).",
    ),
    _e(
        "E803",
        "Too many rows for one import or export",
        "api",
        "karni.transfer",
        "KARNI_IMPORT_MAX_ROWS caps an upload and KARNI_EXPORT_MAX_ROWS an export so one "
        "request cannot pin a worker or build an unbounded file.",
        "Split the upload, narrow the export's filters, or raise the setting for a project "
        "that needs more.",
    ),
    _e(
        "E804",
        "A content file cannot be loaded",
        "exception",
        "karni load; manage.py karni_load; karni.transfer.loading",
        "The file is missing, is not valid JSON or YAML, does not map model labels to lists of "
        "rows, names a model that is not installed, nests rows under a model with no key to "
        "match them on, or --as names no user. Nothing was written.",
        "The message names the file and the problem. Keys are model labels (events.Event), "
        "each holding a list of rows. A nested child needs a Karni.natural_key or a unique "
        "constraint with its parent. YAML needs PyYAML, or write the file as JSON.",
    ),
    _e(
        "E805",
        "A content file holds rows that cannot be loaded",
        "exception",
        "karni load; manage.py karni_load; karni.transfer.loading",
        "A row failed the validation the API runs (a missing required field, a bad choice, "
        "clean(), uniqueness), names a field the model does not have or a file cannot set, "
        "names a relation target that does not exist, lacks its key, or points at a file that "
        "is not there. The whole load runs in one transaction, so every row was rolled back.",
        "Each problem names the model, the row's key, the field and what is wrong. Fix the rows "
        "(relations are named by the target's natural key, paths are relative to the content "
        "file) and run again. karni load --dry-run checks a file without writing.",
    ),
    # E9xx debugging: karni why
    _e(
        "E901",
        "karni why: no API resource by that name",
        "exception",
        "karni.why.resolve.resolve_resource; karni why",
        "karni why explains the decisions of a routed BaseViewSet, so it needs the resource as "
        "the API routes it.",
        "Name the resource by its route prefix (events), router basename (events-event) or model "
        "label (events.Event). The message lists the routed resources, and `karni routes` lists "
        "every URL.",
    ),
    _e(
        "E902",
        "karni why: no such user",
        "exception",
        "karni.why.resolve.resolve_user; karni why --as",
        "A decision is always for one user. --as looks the user up by primary key, login field, "
        "email or username. A recorded request names its user by primary key.",
        "Pass --as with an email, username or primary key that exists, or --as anonymous for a "
        "request that is not signed in.",
    ),
    _e(
        "E903",
        "karni why: no request record for that id",
        "exception",
        "karni.why.resolve.load_record; karni why <status> <request-id>",
        "The dev server records each request as .karni/requests/<request id>.json, and only "
        "while DEBUG is on. Without the record there is nothing to replay.",
        "Reproduce the request with the dev server running (`karni serve`) and use its request "
        "id, or ask about the row directly: karni why <resource>/<id> --as <user> [--action ...].",
    ),
    _e(
        "E904",
        "karni why: the request record cannot be read",
        "exception",
        "karni.why.resolve.load_record",
        "The record is not JSON, or its version or fields are not what this karni reads "
        "(version 1: request_id, method, path, status, user, ...).",
        "Delete the file and reproduce the request. If it keeps happening, upgrade karni so the "
        "writer and the reader agree.",
    ),
    _e(
        "E905",
        "karni why: the resource has no such field",
        "exception",
        "karni.why.verdict.explain_field; karni why <resource>.<field>",
        "A field question names a model field or a field of the resource's serializer.",
        "Use a field name the message lists (the resource's API fields).",
    ),
    _e(
        "E906",
        "karni why: the resource routes no such action or method",
        "exception",
        "karni.why.resolve.resolve_action; karni why --action/--method",
        "--action names a routed viewset action (or the plain words view, update, delete, create, "
        "list). --method must be one that action answers.",
        "Use an action the message lists, or drop --method.",
    ),
    _e(
        "E907",
        "karni why: not a Karni BaseViewSet route",
        "exception",
        "karni.why.resolve.resolve_resource; karni.why.verdict.explain_record",
        "karni why explains the decisions of Karni's access layer, which only BaseViewSet routes "
        "have. Another view's permission_classes decide on their own.",
        "Read that view's permission_classes and get_queryset(), or move the endpoint onto a "
        "BaseViewSet with an access declaration.",
    ),
    _e(
        "E908",
        "karni why: the question is incomplete",
        "exception",
        "manage.py karni_why",
        "A question names what (a request id after its status, <resource>/<id>, "
        "<resource>.<field> or <resource>) and, except for a recorded request, who (--as).",
        "Follow the form the message shows, e.g. karni why events/42 --as alice@example.com, "
        "karni why 403 <request-id>, or karni why-empty events --as alice@example.com.",
    ),
    # E9xx/W9xx debugging: request ids, development capture, trace, replay
    _e(
        "E920",
        "karni replay needs DEBUG on",
        "exception",
        "karni.debug.replay; manage.py karni_replay",
        "A replay re-sends a captured request, force-authenticated as a captured user, against "
        "the configured database. That is a development tool. With DEBUG off it could act as any "
        "user on a production database, so Karni refuses.",
        "Run it in development, where DEBUG is on (DEBUG=true in the environment or .env). "
        "To check a fix in production, add a test instead.",
    ),
    _e(
        "E921",
        "Nothing was captured for this request id",
        "exception",
        "karni.debug.trace; manage.py karni_trace, karni_replay",
        "karni trace and karni replay read what the development capture wrote under .karni/ "
        "(requests/, trace/) plus change log entries with the id. Capture runs only with DEBUG on "
        "and KARNI_DEBUG_CAPTURE not False, keeps the newest KARNI_DEBUG_CAPTURE_KEEP records and "
        "KARNI_DEBUG_TRACE_DAYS of trace. Ids are 1-128 letters, digits, '_' and '-'.",
        "Turn DEBUG on, repeat the request, and pass the id from its X-Request-ID response "
        "header (or `last` for the newest capture). Check the id has no typo.",
    ),
    _e(
        "E922",
        "No failure snapshot with this id",
        "exception",
        "karni.debug.brief; karni explain --failure; manage.py karni_failure",
        "A failure snapshot is written to .karni/failures/ when a request or a Celery task raises "
        "an unhandled exception with DEBUG on. The newest KARNI_DEBUG_CAPTURE_KEEP are kept. A "
        "request that answered an error status without raising has none.",
        "Use the failure id from the request record or `karni trace <request-id>`, a failed "
        "request's id, or `last`. Reproduce the failure with DEBUG on if nothing was captured.",
    ),
    _e(
        "E923",
        "A redacted value cannot be replayed",
        "exception",
        "karni.debug.replay; karni replay --set",
        "Capture never stores passwords, tokens or other secrets: they are recorded as "
        "'[redacted]'. Replaying that literal could, for example, set a password to it, so "
        "the replay stops until the value is supplied.",
        "Pass each value the message lists: --set <field>=<value> (a dotted path into the "
        "body, or query:<name> for a query parameter), or leave them out with "
        "--drop-redacted.",
    ),
    _e(
        "E924",
        "The user to replay as cannot be found",
        "exception",
        "karni.debug.replay; karni replay --as",
        "A replay runs as the captured user, or the user --as names (a primary key, an "
        "email or a username). That user must exist in the database the replay uses, and "
        "the captured id must still belong to the captured email: after a reset, integer "
        "ids are reused by other users.",
        "Pass --as with an existing user's email, username or primary key, or pass --anonymous. "
        "Do not pass both.",
    ),
    _e(
        "W920",
        "RequestIdMiddleware runs after django-structlog's RequestMiddleware",
        "warning",
        "karni.checks.check_request_id_middleware",
        "django-structlog logs request_started with the X-Request-ID it finds. Karni's "
        "RequestIdMiddleware decides that id (a client's value is accepted only in development or "
        "from a trusted proxy). When it runs later, the first log lines carry a different, "
        "possibly client-chosen id than the response, tasks and history.",
        "Move 'karni.tracing.RequestIdMiddleware' above "
        "'django_structlog.middlewares.RequestMiddleware' in MIDDLEWARE (Karni's defaults "
        "put it first).",
    ),
    # E94x debugging: karni queries (karni.api.diagnose)
    _e(
        "E940",
        "karni queries cannot find the endpoint",
        "exception",
        "karni.api.diagnose.resolve_endpoint (manage.py karni_queries)",
        "karni queries requests the endpoint in-process, so it must resolve to a URL the "
        "project serves: a path, a routed resource (events, events/<id>) or a routed viewset "
        "(EventViewSet.list). A detail action named by its viewset needs a row the user can read.",
        "Pass a path that `karni routes` lists (/api/events/), a resource prefix it shows, or "
        "resource/<id>. The message lists the routed resources or viewsets.",
    ),
    _e(
        "E941",
        "karni queries cannot find the user (--as)",
        "exception",
        "karni.api.diagnose.resolve_user (manage.py karni_queries --as)",
        "The request runs force-authenticated as one user, named by primary key, email or "
        "username. The value matched none (or several).",
        "Pass a user that exists in this database (the message shows a few), seed some with "
        "karni seed, or drop --as for an anonymous request.",
    ),
    _e(
        "E942",
        "karni queries cannot build the request",
        "exception",
        "karni.api.diagnose.run (manage.py karni_queries --method / --data)",
        "--method must be an HTTP method the view answers at that URL, and --data a JSON body.",
        "Use a method the message lists for that URL, and pass --data as JSON "
        '(--data \'{"title": "Launch"}\').',
    ),
    _e(
        "E943",
        "The view raised while karni queries requested it",
        "exception",
        "manage.py karni_queries",
        "There is no query report for a request that raised. The message shows the traceback and "
        "what karni explain recognises in it.",
        "Fix the exception the traceback names (karni explain - explains a pasted traceback), "
        "then run karni queries again.",
    ),
    # E96x-E97x typed fields and database guarantees (karni.fields: E960-E970, W964-W967)
    _e(
        "E960",
        "A FloatField holds money",
        "check",
        "karni.fields.checks.check_money_floats",
        "A field named like money (price, amount, total, cost, fee, subtotal, tax, balance, ...) "
        "is a FloatField. Binary floats cannot represent most cent values, so sums drift (0.1 + "
        "0.2 != 0.3) and totals stop reconciling. No test with round numbers notices.",
        'Use `MoneyField(currency="EUR")` (or `currency_field="currency"`) from '
        "karni.fields, a PercentField for a rate, then karni make migration. If the field is "
        'not money, declare `class Karni: not_money = {"field": "<what it is>"}`.',
    ),
    _e(
        "E961",
        "A MoneyField's currency is not declared",
        "exception",
        "karni.fields.MoneyField; karni.fields.checks.check_field_declarations",
        "An amount without a currency is ambiguous: 10.00 could be any currency. MoneyField needs "
        "exactly one declaration: a fixed ISO 4217 code, or the CurrencyField on the same model "
        "that holds each row's currency.",
        'Write `MoneyField(currency="EUR")`, or `MoneyField(currency_field="currency")` '
        "with `currency = CurrencyField()` on the model.",
    ),
    _e(
        "E962",
        "A float reached a MoneyField",
        "exception",
        "karni.fields.MoneyField; karni.fields.quantize / allocate / split",
        "Money is stored and computed as Decimal. A float has already lost the exact value "
        "before Karni sees it (Decimal(0.1) is 0.1000000000000000055...), so assigning one or "
        "using one in a lookup is refused rather than silently rounded.",
        'Pass a Decimal (`Decimal("9.99")`), an int, or a string. Parse user input with '
        "Decimal(str), never float(str).",
    ),
    _e(
        "E963",
        "A typed field declaration cannot work",
        "exception",
        "karni.fields (PercentField, SlugField, SearchField, CountryField, CurrencyField, "
        "MoneyField); karni.fields.checks.check_field_declarations",
        "The arguments contradict each other or name something the model lacks: bounds that "
        "do not fit max_digits, a populate_from or SearchField source that is not a field, a "
        "code outside the ISO list, an unknown rounding mode or text search configuration.",
        "Fix the argument the message names. docs/fields.md lists every field's arguments.",
    ),
    _e(
        "E964",
        "A field cannot work on the configured database",
        "check",
        "karni.fields.checks.check_backends",
        "The field needs PostgreSQL (an ArrayField: array columns exist nowhere else), but a "
        "database in DATABASES that migrates this model is another backend. migrate would fail "
        "with a syntax error. The check says which field instead.",
        "Point that database at PostgreSQL, or replace the field with the portable one the "
        "message names (a JSONField holding a list instead of an ArrayField).",
    ),
    _e(
        "W964",
        "A PostgreSQL guarantee is missing on the configured database",
        "warning",
        "karni.fields.checks.check_backends",
        "The model works on this database but without something PostgreSQL provides: exact "
        "NUMERIC storage (SQLite keeps NUMERIC as a binary float), a GIN index, the tsvector "
        "column, the E.164 CHECK, or partial unique indexes.",
        "This is fine for tests and local development on SQLite. Run production on PostgreSQL. "
        "Silence karni.W964 where the difference is deliberate.",
    ),
    _e(
        "W965",
        "A foreign key on a financial or audited model cascades",
        "warning",
        "karni.fields.checks.check_cascades",
        "on_delete=CASCADE on a model that holds money (a MoneyField, a money-named decimal, a "
        "payments-like model) or keeps history (Karni.audit) means hard-deleting the referenced "
        "row silently deletes those rows too: payments, refunds or audit trails vanish.",
        "Choose on_delete deliberately: models.PROTECT (refuse while rows exist) or SET_NULL "
        "(null=True), then karni make migration. If the cascade is intended, declare it with "
        'the reason: `class Karni: cascade = {"<field>": "<why>"}`.',
    ),
    _e(
        "E966",
        "A PostgreSQL extension could not be created",
        "exception",
        "karni.fields.extensions.ensure_extension / CreateExtension (karni.accounts 0005)",
        "A migration needs an extension (btree_gist, pg_trgm, ...) and the database role may not "
        "create it. Trusted extensions (PostgreSQL 13+) need CREATE on the database, and the "
        "others need a superuser.",
        "Run the SQL the message prints: `CREATE EXTENSION IF NOT EXISTS <name>;` as a "
        "superuser in the project's database, or, for a trusted extension, `GRANT CREATE ON "
        'DATABASE "<db>" TO "<role>";`. Then migrate again.',
    ),
    _e(
        "W967",
        "A searched, filtered or ordered column has no index",
        "warning",
        "karni.fields.checks.check_usage_indexes; karni schema",
        "A routed viewset declares search_fields, filterset_fields, ordering_fields or an "
        "ordering on a column no index covers, so every such list request reads the whole "
        "table. Fast with seed data, slow in production.",
        "Add the index the message names to Meta.indexes (a SearchField for search), then run "
        "karni make migration. `karni schema <app>` shows what serves each column. For a table "
        'small enough to scan, silence it instead: SILENCED_SYSTEM_CHECKS = ["karni.W967"].',
    ),
    _e(
        "E968",
        "LiveUniqueConstraint on a model without soft delete",
        "check",
        "karni.fields.checks.check_field_declarations",
        "LiveUniqueConstraint limits uniqueness to rows whose deleted_at is NULL. A model without "
        "soft delete has no deleted_at, so the constraint cannot be created.",
        "Use models.UniqueConstraint, or inherit karni.models.BaseModel (or SoftDeleteModel).",
    ),
    _e(
        "E969",
        "karni schema was given an unknown app or model",
        "exception",
        "manage.py karni_schema (karni schema)",
        "karni schema reports the models you name, by app label or app.Model.",
        "Pass labels `karni context` lists (events, events.Event), or none for every model of "
        "your own apps.",
    ),
    _e(
        "E970",
        "A field-layer Karni option is malformed",
        "check",
        "karni.fields.checks (Karni.not_money, Karni.cascade, Karni.append_only)",
        "Opt-outs need a reason per field so the next reader knows the choice was deliberate. "
        "append_only names columns that only grow.",
        'Write `not_money = {"field": "<what it is>"}`, `cascade = {"field": "<why>"}`, '
        "`append_only = True` or a list of existing timestamp columns.",
    ),
    # E98x lifecycle (StateField) and limited resources (capacity, no_overlap)
    _e(
        "E980",
        "A StateField change the declared lifecycle does not allow",
        "exception",
        "karni.lifecycle (save(), transition(), StateField.validate, the generated serializer)",
        "A StateField declares its states and the transitions between them. Moving a row "
        "along an undeclared transition (out of a terminal state, backwards, or to a value "
        "that is not a state) is refused before any SQL: from the ORM, the admin (a form "
        "error), the API (a 400 on the field), commands and tasks alike. The column's CHECK "
        "constraint refuses an undeclared value from raw SQL too.",
        "Move the row to one of the legal states the message lists (instance.transition("
        "'<field>', '<state>'), or allowed_transitions('<field>') to ask), or add the "
        "transition to the field's transitions= if the lifecycle should allow it.",
    ),
    _e(
        "E981",
        "The row's state changed since it was loaded",
        "exception",
        "karni.models.GuardedModel._do_update (karni.lifecycle.StateConflict)",
        "A save that writes a StateField updates the row only if it still holds the state it was "
        "loaded with (UPDATE ... WHERE status = '<loaded>'). Another transaction changed it "
        "first, so nothing was written. Two concurrent transitions from one state can never both "
        "succeed. The API answers 409.",
        "Reload the row (refresh_from_db()) and decide again from the state the message names. In "
        "a UI, show the new state and let the user retry.",
    ),
    _e(
        "E982",
        "A new row starts in a state that is not an initial state",
        "exception",
        "karni.lifecycle (save() of a new row, the generated serializer's create)",
        "A StateField row is created in one of its initial states (default: the default "
        "state) and reaches the others through transitions, so a client cannot create an "
        "order that is already 'paid'. Karni's factories and seeders may create any state "
        "(karni.lifecycle.any_initial_state).",
        "Create the row in an initial state and call .transition(...), list the state in "
        "initial= if rows may legitimately start there, or wrap data loading in "
        "any_initial_state(reason='...').",
    ),
    _e(
        "E983",
        "A StateField is declared or named wrongly",
        "exception",
        "karni.fields.StateField; karni.lifecycle.transition",
        "The lifecycle must be complete and unambiguous: every state named in transitions or "
        "initial is declared, states use letters, digits, _ and - (they go into a CHECK "
        "constraint), every state is reachable, and transition() names a StateField.",
        "Fix the declaration the message names: declare the missing state, drop the "
        "self-transition, add a transition into an unreachable state, or name the right "
        "field.",
    ),
    _e(
        "E984",
        "The slot overlaps an existing row",
        "exception",
        "karni.constraints.NoOverlap (class Karni: no_overlap)",
        "PostgreSQL's EXCLUDE constraint refused the row because another live row of the same "
        "resource overlaps its range. The check runs in the database, so it holds under "
        "concurrency and against raw SQL. Soft-deleted rows and the states listed in ignore= "
        "never block. The API answers 409 naming the existing row.",
        "Pick a free slot, or cancel or delete the row the message names first. Touching "
        "ranges ([10:00, 11:00) and [11:00, 12:00)) do not overlap.",
    ),
    _e(
        "E985",
        "Not enough capacity left",
        "exception",
        "karni.capacity.reserve; the CapacityField CHECK constraint",
        "A CapacityField counts what is left of a limited resource and its CHECK keeps it at or "
        "above zero. reserve() locks the row and refuses when fewer units remain than were asked "
        "for. Lowering the total below what is already reserved is refused the same way. The API "
        "answers 409 with the resource and the remaining count.",
        "Ask for at most the remaining count the message gives, offer another resource or a "
        "waiting list, or release reservations before lowering the total.",
    ),
    _e(
        "E986",
        "A capacity counter is used the wrong way",
        "exception",
        "karni.capacity.reserve / release; CapacityField; karni.checks",
        "Capacity is consumed only through reserve() and release(), inside transaction.atomic() "
        "together with the write that uses it, by a positive quantity. Assigning the counter "
        "directly would let a stale instance overwrite reservations, and releasing more than was "
        "reserved means a double release.",
        "Call reserve(resource, quantity) / release(...) inside transaction.atomic(). Change the "
        "total field to resize. Point CapacityField(total=...) at an integer field of the same "
        "model.",
    ),
    _e(
        "E987",
        "A no_overlap declaration is invalid",
        "check",
        "karni.constraints.NoOverlap; karni.checks.check_guarded_models",
        "NoOverlap takes the resource field(s) and then the range: a range field "
        "(DateTimeRangeField, DateRangeField) or a (start, end) pair of date, date-time or "
        "number fields. ignore= must name model fields and, for a StateField, declared states.",
        "Fix the declaration the message names, e.g. no_overlap = NoOverlap('room', 'during', "
        "ignore={'status': ['cancelled']}).",
    ),
    _e(
        "E988",
        "A guarded field on a model without GuardedModel",
        "check",
        "karni.checks.check_guarded_models",
        "StateField, CapacityField and NoOverlap rely on karni.models.GuardedModel for the "
        "loaded-state tracking, the conditional UPDATE, the transition history and the named "
        "conflicts. Without it saves would skip all of that silently.",
        "Inherit karni.models.BaseModel (which includes GuardedModel), or add "
        "karni.models.GuardedModel to the model's bases.",
    ),
    _e(
        "W980",
        "no_overlap is not enforced on this database",
        "warning",
        "karni.checks.check_guarded_models",
        "Only PostgreSQL has EXCLUDE constraints. On SQLite (or any other backend) the "
        "NoOverlap constraint creates nothing, so overlapping rows are accepted. The "
        "StateField and CapacityField CHECK constraints do work on SQLite.",
        "Use PostgreSQL wherever overlaps matter (production, CI). Silence karni.W980 only for a "
        "development database where accepting overlaps is fine.",
    ),
)


def registry(extra: Iterable[ErrorCode] = (), *, modules: bool = True) -> dict[str, ErrorCode]:
    """Every code by name: Karni's, each installed module's, and ``extra``.

    Modules register through the ``karni.errorcodes`` entry-point group.
    """
    entries: list[ErrorCode] = list(CODES)
    if modules:
        from importlib.metadata import entry_points

        for entry_point in entry_points(group="karni.errorcodes"):
            entries.extend(entry_point.load())
    entries.extend(extra)
    found: dict[str, ErrorCode] = {}
    for entry in entries:
        if entry.code in found:
            raise KarniError(
                f"Error code {entry.code} is registered twice ({found[entry.code].source} and "
                f"{entry.source}). Codes are permanent and unique: give the newer entry the "
                "next free code."
            )
        found[entry.code] = entry
    return found


def get(code: str) -> ErrorCode | None:
    """The entry for ``code`` (case-insensitive), or ``None``."""
    return registry().get(code.strip().upper())


def problems(entries: Iterable[ErrorCode]) -> list[str]:
    """Registry integrity problems (format, kind, empty fields) — used by tests."""
    found: list[str] = []
    for entry in entries:
        if not _CODE.match(entry.code):
            found.append(f"{entry.code}: not a code like E104, W101 or PAY001")
        if entry.kind not in KINDS:
            found.append(f"{entry.code}: kind {entry.kind!r} is not one of {KINDS}")
        core = re.match(r"^[EW]\d{3}$", entry.code) is not None
        if core and entry.code.startswith("W") != (entry.kind == "warning"):
            found.append(f"{entry.code}: W codes are exactly the warnings")
        for name in ("title", "why", "fix", "source"):
            if not getattr(entry, name).strip():
                found.append(f"{entry.code}: empty {name}")
    return found
