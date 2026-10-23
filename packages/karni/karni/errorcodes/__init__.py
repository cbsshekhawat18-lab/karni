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
``E5xx`` settings and optional dependencies · ``E6xx`` testing and seeding ·
``E7xx`` agent tooling (``karni check``, ``karni.rules.py``, changelog) ·
``E8xx`` import and export · ``E90x``–``E94x``/``W92x`` debugging (``karni
why``, request ids, the development capture, ``karni trace``, ``karni replay``,
``karni queries``) · ``E96x``/``E97x`` typed fields and database guarantees
(``karni.fields``) · ``E98x``/``W98x`` lifecycle and limited resources
(``StateField``, capacity, ``no_overlap``).
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
        "or the action (or '*' alone). A scope is 'all', 'own', 'related:<key>' or "
        "'custom:<name>'.",
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
        "email or a username). That user must exist in the database the replay uses.",
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
        "karni make migration. `karni schema <app>` shows what serves each column. Silence "
        "karni.W967 for a table small enough to scan.",
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
