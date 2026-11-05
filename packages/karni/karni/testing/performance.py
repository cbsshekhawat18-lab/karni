"""Query budgets and N+1 detection for tests (ADR 0001 Decision 3, §3.2).

Three layers, all on by default in a Karni project's test run:

1. **Per-endpoint budgets.** The ``karni`` pytest plugin
   (:mod:`karni.testing.pytest_plugin`) sets ``KARNI_QUERY_BUDGET_MODE =
   "raise"``, so any test request that makes a ``BaseViewSet`` action exceed
   its budget fails with the grouped duplicate report.
2. **The** ``query_budget`` **fixture / context manager** for an explicit
   maximum around any block — a non-viewset view, a service::

       def test_dashboard(client, query_budget):
           with query_budget(5):
               client.get("/dashboard/")

3. **The scaling check** (N-independence): for every routed project
   ``BaseViewSet`` (an external model's aside, :mod:`karni.db`), ``list`` is
   measured with 2 and with 12 rows and ``retrieve`` with 2 and with 12
   related rows per to-many relation the serializer renders; the query count
   must not grow. A viewset with an aggregation (:mod:`karni.aggregation`,
   experimental) has its ``aggregate`` action measured at the same row counts
   too, grouped by its first declared group, with ``top=1`` and, when it
   declares a second group, ``stack``. The row counts are
   ``KARNI_SCALING_ROWS`` and, per viewset, ``query_scaling = Scaling(rows=(5,
   500), seconds=0.3)`` (experimental, :class:`karni.performance.Scaling`),
   whose ``seconds`` is a time budget for the request at the large count
   (``E476``). An absolute budget cannot see an N+1 in a one-row test — this
   can. Rows come from
   :mod:`karni.testing.factories` (explicit ``<app>/factories.py`` factories
   win), the requester gets every role the ``read`` predicate names and owns
   the rows its ``Owned`` paths name. It runs as part of the architecture
   suite every project's CI already runs::

       pytest --pyargs karni.testing.architecture   # includes the scaling check
       pytest --pyargs karni.testing.performance    # the scaling check alone

Override / escape hatches: ``query_budget = Budget(list=N, reason=...)`` on a
viewset; ``# karni: allow(query-scaling): <reason>`` above a viewset class to
take it out of the scaling check; ``--karni-query-budget=warn|off`` (or the
``karni_query_budget_mode`` ini option) for the whole run; and
``override_settings(KARNI_QUERY_BUDGET_MODE="off")`` for one test.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

from karni.exceptions import KarniAssertionError
from karni.performance import QueryBudgetExceeded, QueryRecorder, budget_failure, record_queries

__all__ = [
    "SCALING_LARGE",
    "SCALING_SMALL",
    "ScalingCase",
    "ScalingResult",
    "aggregate_query",
    "check_scaling",
    "pytest_generate_tests",
    "query_budget",
    "scaling_cases",
    "test_list_and_retrieve_queries_do_not_grow_with_rows",
]

SCALING_SMALL: Final = 2
SCALING_LARGE: Final = 12
#: Related rows per to-many relation below the measured level.
FANOUT: Final = 2
#: How deep the seeding follows the serializer's nested relations.
SEED_DEPTH: Final = 3

RULE: Final = "query-scaling"


@contextmanager
def query_budget(
    limit: int, *, label: str = "block", using: str | None = None
) -> Iterator[QueryRecorder]:
    """Fail with the grouped duplicate report if the block runs more than ``limit`` queries.

    Usable anywhere (``with query_budget(3): ...``); the ``query_budget``
    pytest fixture returns this function. Yields the recorder, so a test can
    also inspect ``recorder.count`` / ``recorder.report()``.

    :raises karni.performance.QueryBudgetExceeded: (an ``AssertionError``).
    """
    with record_queries(using=using) as recorder:
        yield recorder
    if recorder.count > limit:
        raise QueryBudgetExceeded(
            budget_failure(
                label,
                recorder.report(),
                limit,
                "Repeated statements above are the usual cause (N+1): select_related/"
                "prefetch_related the relation, or raise the limit if the work is real.",
            )
        )


# the scaling check


@dataclass(frozen=True)
class ScalingCase:
    """One ``(viewset, action)`` the scaling check measures."""

    viewset: type[Any]
    action: str
    #: Set when the opt-out marker has no reason (the case then fails).
    optout_error: str = ""
    #: ``?expand=`` values the request carries (a list measured with every expansion).
    expand: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        suffix = f"?expand={','.join(self.expand)}" if self.expand else ""
        return f"{self.viewset.__name__}.{self.action}{suffix}"


@dataclass(frozen=True)
class ScalingResult:
    """Query counts at the small and the large row count, plus the large run's report.

    ``rows`` are the row counts compared (experimental), ``seconds`` the time
    of the request at the large count and ``budget`` the viewset's time
    budget (``Scaling(seconds=...)``), ``None`` without one.
    """

    case: ScalingCase
    small: int = 0
    large: int = 0
    report: str = ""
    skipped: str = ""
    rows: tuple[int, int] = (SCALING_SMALL, SCALING_LARGE)
    seconds: float = 0.0
    budget: float | None = None
    endpoint: str = ""

    @property
    def grows(self) -> bool:
        return self.large > self.small

    @property
    def too_slow(self) -> bool:
        """Experimental. The request at the large row count took longer than the time budget."""
        return self.budget is not None and self.seconds > self.budget

    def slow_message(self) -> str:
        """Experimental. What a failed time budget says: the endpoint, rows, time and queries."""
        where = f" ({self.endpoint})" if self.endpoint else ""
        return (
            f"{self.case.id}{where}: {self.rows[1]} rows took {self.seconds:.3f}s against a time "
            f"budget of {self.budget:g}s, in {self.large} queries.\n{self.report}\n"
            "Find the slow statement above: karni queries <endpoint> --explain shows its plan on "
            "PostgreSQL (a sequential scan wants an index). Raise the budget only when the work "
            f"is real: query_scaling = Scaling(seconds=...) on {self.case.viewset.__name__}."
        )

    def message(self) -> str:
        small_rows, large_rows = self.rows
        return (
            f"{self.case.id}: {self.small} queries with {small_rows} rows, {self.large} with "
            f"{large_rows}: the query count grows with the data (N+1).\n{self.report}\n"
            "The optimiser derives select_related/prefetch_related from the serializer, but a "
            "SerializerMethodField or property needs select_related/prefetch_related hints on "
            f"{self.case.viewset.__name__} (or APIMeta.select/prefetch). Opt out only with "
            f"# karni: allow({RULE}): <reason> above the class."
        )


def _optout(viewset: type[Any]) -> tuple[bool, str]:
    """``(opted_out, error)`` from a ``# karni: allow(query-scaling)`` class marker."""
    from karni.testing._source import class_marker_lines, find_allow, relative

    marked = class_marker_lines(viewset)
    if marked is None:
        return False, ""
    path, lines = marked
    allow = find_allow(path, RULE, lines)
    if allow is None:
        return False, ""
    if allow.reason:
        return True, ""
    return False, (
        f"[opt-out-reason] {relative(path)}:{allow.line}: karni: allow({RULE}) requires a "
        f"non-empty reason: write `# karni: allow({RULE}): <why the growth is expected>` "
        "above the class."
    )


def scaling_cases() -> list[ScalingCase]:
    """``list``/``retrieve`` (and ``aggregate``) of every routed project ``BaseViewSet``.

    A viewset opted out with ``# karni: allow(query-scaling): <reason>`` is left out.
    """
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet
    from karni.testing._source import project_app_configs

    prefixes = tuple(config.name for config in project_app_configs())
    router = resolve_router()
    if not prefixes or router is None:
        return []
    cases: list[ScalingCase] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in router.registry:
        if viewset in seen or not issubclass(viewset, BaseViewSet):
            continue
        if not viewset.__module__.startswith(prefixes):
            continue
        if _serves_external(viewset):
            continue
        seen.add(viewset)
        opted_out, error = _optout(viewset)
        if opted_out:
            continue
        for action in ("list", "retrieve"):
            if callable(getattr(viewset, action, None)):
                cases.append(ScalingCase(viewset, action, error))
        expand = expansions(viewset)
        if expand and callable(getattr(viewset, "list", None)):
            cases.append(ScalingCase(viewset, "list", error, expand=expand))
        if aggregate_query(viewset):
            cases.append(ScalingCase(viewset, "aggregate", error))
    return cases


def aggregate_query(viewset: type[Any]) -> dict[str, str]:
    """The query the scaling check sends to ``aggregate``: ``{}`` without an aggregation.

    The first declared group with ``top=1`` (so the "Other" query runs too),
    stacked by the second declared group when there is one.
    """
    from karni.aggregation import Aggregation, aggregation_of
    from karni.errorcodes import KarniError

    model = viewset.model if viewset.model is not None else getattr(viewset.queryset, "model", None)
    declared = viewset.__dict__.get("aggregation") or getattr(viewset, "aggregation", None)
    try:
        aggregation = (
            Aggregation.coerce(declared, viewset.__name__)
            if declared is not None
            else aggregation_of(model)
        )
    except KarniError:
        return {}  # karni check reports it (E380)
    if aggregation is None or not aggregation.group_by:
        return {}
    query = {"group_by": aggregation.group_by[0], "top": "1"}
    first = aggregation.group_by[0].partition(":")[0]
    others = [entry for entry in aggregation.group_by if entry.partition(":")[0] != first]
    if others:
        query["stack"] = others[0]
    return query


def _serves_external(viewset: type[Any]) -> bool:
    """A viewset over an external table or view (``karni.db``, experimental): not measured.

    Another system fills that table, so the check cannot seed rows the way
    the table really holds them.
    """
    from karni.db import is_external

    model = viewset.model if viewset.model is not None else getattr(viewset.queryset, "model", None)
    return model is not None and is_external(model)


def expansions(viewset: type[Any]) -> tuple[str, ...]:
    """Every ``?expand=`` key the viewset accepts (its own mapping, else the forward relations)."""
    from collections.abc import Mapping

    from karni.api.expansion import auto_expandable_fields

    explicit = getattr(viewset, "expandable_fields", None)
    if isinstance(explicit, Mapping):
        return tuple(sorted(explicit))
    model = viewset.model if viewset.model is not None else viewset.queryset.model
    return tuple(sorted(auto_expandable_fields(model)))


def _role_names(predicate: Any) -> set[str]:
    from karni.api.access import AllOf, AnyOf, HasRole, Owned

    if isinstance(predicate, HasRole):
        return set(predicate.names)
    if isinstance(predicate, AnyOf | AllOf):
        return set().union(*(_role_names(part) for part in predicate.parts))
    if isinstance(predicate, Owned) and predicate.bypass is not None:
        return _role_names(predicate.bypass)
    return set()


def _has_can(predicate: Any) -> bool:
    from karni.api.access import AllOf, AnyOf, Can, Owned

    if isinstance(predicate, Can):
        return True
    if isinstance(predicate, AnyOf | AllOf):
        return any(_has_can(part) for part in predicate.parts)
    if isinstance(predicate, Owned) and predicate.bypass is not None:
        return _has_can(predicate.bypass)
    return False


def _requester(viewset: type[Any], model: type[Any]) -> tuple[Any, dict[str, Any]]:
    """A user who may read the seeded rows, and the factory kwargs that make them theirs."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    from karni.api.access import Access
    from karni.testing.factories import create

    user = create(get_user_model())
    declaration = getattr(viewset, "access", None)
    owner: dict[str, Any] = {}
    if not isinstance(declaration, Access):
        return user, owner
    roles = _role_names(declaration.read)
    if roles and hasattr(user, "groups"):  # roles are Django groups (HasRole)
        for name in sorted(roles):
            user.groups.add(Group.objects.get_or_create(name=name)[0])
        return user, owner  # a role holder already sees every row
    if _has_can(declaration.read) and hasattr(user, "is_superuser"):
        user.is_superuser = True  # every grant with scope `all` (karni.accounts.roles)
        user.save(update_fields=["is_superuser"])
        return user, owner
    for owned in declaration.read.owned():
        if model is get_user_model() and owned.path in {"pk", model._meta.pk.name}:
            continue
        head = owned.path.split("__", 1)[0]
        try:
            field = model._meta.get_field(head)
        except Exception:  # noqa: BLE001 - an invalid path is validate_access's to report
            continue
        if getattr(field, "many_to_many", False) and "__" not in owned.path:
            owner[owned.path] = [user]
        elif getattr(field, "concrete", False):
            owner[owned.path] = user
    return user, owner


def _seed_children(row: Any, plan: Any, fanout: int, depth: int) -> None:
    """Give ``row`` ``fanout`` related rows on every to-many relation ``plan`` renders."""
    from karni.api.optimizer import model_relation
    from karni.testing.factories import create_batch

    if depth >= SEED_DEPTH:
        return
    model = type(row)
    for name, many in plan.to_many.items():
        relation = model_relation(model, name)
        if relation is None:
            continue
        if relation.many_to_many:
            through = getattr(getattr(row, name), "through", None)
            if through is not None and not through._meta.auto_created:
                continue  # custom through rows need values only a project factory knows
            children = create_batch(many.model, fanout)
            getattr(row, name).add(*children)
        elif relation.one_to_many and hasattr(relation, "field"):
            children = create_batch(many.model, fanout, **{relation.field.name: row})
        else:
            continue
        for child in children:
            if many.plan is not None:
                _seed_children(child, many.plan, FANOUT, depth + 1)
    for name, one in plan.to_one.items():
        target = getattr(row, name, None)
        if target is not None:
            _seed_children(target, one.plan, FANOUT, depth + 1)


def _view(
    viewset: type[Any], action: str, user: Any, query: dict[str, Any] | None = None
) -> tuple[Any, Any]:
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    view = viewset()
    view.action = action
    view.request = Request(APIRequestFactory().get("/", query or {}))
    view.request.user = user
    view.format_kwarg = None
    view.args, view.kwargs = (), {}
    return view, view.get_serializer_class()


def _measure(
    viewset: type[Any], action: str, user: Any, pk: Any = None, query: dict[str, Any] | None = None
) -> tuple[int, Any, str]:
    from rest_framework.test import APIRequestFactory, force_authenticate

    request = APIRequestFactory().get("/", query or {})
    force_authenticate(request, user=user)
    handler = viewset.as_view({"get": action})
    kwargs: dict[str, Any] = {}
    if pk is not None:
        kwargs[viewset.lookup_url_kwarg or viewset.lookup_field] = str(pk)
    with record_queries() as recorder:
        response = handler(request, **kwargs)
    return recorder.count, response, recorder.report().render()


def _row_count(response: Any) -> int:
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return int(data.get("count", len(data["results"])))
    return len(data) if isinstance(data, list) else 0


def check_scaling(case: ScalingCase) -> ScalingResult:
    """Measure ``case`` at :data:`SCALING_SMALL` and :data:`SCALING_LARGE` rows.

    Runs with budgets and the response cache off, inside the caller's
    transaction (use the ``db`` fixture). Returns a skipped result, with the
    reason, when the seeded rows are not visible to the generated requester
    (e.g. a ``Where(...)`` read rule) — give the model an explicit factory
    that produces readable rows, or opt the viewset out with a reason.
    """
    from django.test.utils import override_settings

    from karni.api.optimizer import plan_for
    from karni.pagination import hard_max_page_size
    from karni.performance import scaling_rows
    from karni.testing.factories import create

    viewset, action = case.viewset, case.action
    model = viewset.model if viewset.model is not None else viewset.queryset.model
    declared = getattr(viewset, "query_scaling", None)
    rows_small, rows_large = scaling_rows(declared)
    budget = getattr(declared, "seconds", None)
    measured: dict[str, Any] = {"rows": (rows_small, rows_large), "budget": budget}
    measured["endpoint"] = _endpoint(viewset, action)
    with override_settings(KARNI_QUERY_BUDGET_MODE="off", KARNI_API_CACHE=False):
        user, owner = _requester(viewset, model)
        expand = {"expand": ",".join(case.expand)} if case.expand else {}
        view, serializer_class = _view(viewset, action, user, expand)
        plan = plan_for(serializer_class, model, view.get_serializer_context())
        if action == "aggregate":
            query = aggregate_query(viewset)
            for _ in range(rows_small):
                create(model, **owner)
            _measure(viewset, action, user, query=query)  # warm-up: one-time lookups
            small, response, _report = _measure(viewset, action, user, query=query)
            for _ in range(rows_large - rows_small):
                create(model, **owner)
            large, response, report, seconds = _timed(budget, viewset, action, user, query=query)
            status = response.status_code
        elif action == "list":
            # Rows already present (other fixtures, the requester itself) render in
            # both runs; one page must hold them plus every seeded row.
            page = {"page_size": model._default_manager.count() + rows_large, **expand}
            if page["page_size"] > hard_max_page_size():
                return ScalingResult(
                    case, skipped=f"{case.id}: too many rows exist before seeding to compare pages"
                )
            for _ in range(rows_small):
                _seed_children(create(model, **owner), plan, FANOUT, 0)
            _measure(viewset, action, user, query=page)  # warm-up: one-time lookups
            small, response, _report = _measure(viewset, action, user, query=page)
            for _ in range(rows_large - rows_small):
                _seed_children(create(model, **owner), plan, FANOUT, 0)
            large, response, report, seconds = _timed(budget, viewset, action, user, query=page)
            status = response.status_code
            if status == 200 and _row_count(response) < rows_large:
                return ScalingResult(
                    case,
                    skipped=f"{case.id}: only {_row_count(response)} of {rows_large} seeded "
                    "rows are visible to the generated requester",
                )
        else:
            few, many = create(model, **owner), create(model, **owner)
            _seed_children(few, plan, rows_small, 0)
            _seed_children(many, plan, rows_large, 0)
            _measure(viewset, action, user, few.pk)
            small, response, _report = _measure(viewset, action, user, few.pk)
            large, response, report, seconds = _timed(budget, viewset, action, user, many.pk)
            status = response.status_code
        if status != 200:
            return ScalingResult(
                case, skipped=f"{case.id}: GET answered {status} for the generated requester"
            )
    return ScalingResult(case, small=small, large=large, report=report, seconds=seconds, **measured)


def _timed(
    budget: float | None,
    viewset: type[Any],
    action: str,
    user: Any,
    pk: Any = None,
    query: dict[str, Any] | None = None,
) -> tuple[int, Any, str, float]:
    """:func:`_measure` with its time; with a time budget the faster of two runs counts."""
    import time

    started = time.perf_counter()
    count, response, report = _measure(viewset, action, user, pk, query)
    seconds = time.perf_counter() - started
    if budget is not None and seconds > budget:
        started = time.perf_counter()
        count, response, report = _measure(viewset, action, user, pk, query)
        seconds = min(seconds, time.perf_counter() - started)
    return count, response, report, seconds


def _endpoint(viewset: type[Any], action: str) -> str:
    """``GET /api/events/`` (``{id}/`` for a detail): the route of ``viewset``, when routed."""
    from django.urls import NoReverseMatch, reverse

    from karni.api.routers import resolve_router

    router = resolve_router()
    for _prefix, routed, basename in getattr(router, "registry", ()):
        if routed is viewset:
            try:
                if action == "list":
                    return f"GET {reverse(f'{basename}-list')}"
                path = reverse(f"{basename}-detail", kwargs={"pk": "0"})
                return f"GET {path.removesuffix('0/')}{{id}}/"
            except NoReverseMatch:
                return f"GET {_prefix}/"
    return ""


def pytest_generate_tests(metafunc: Any) -> None:
    """Parametrise the scaling test with :func:`scaling_cases` (empty without Django)."""
    if "karni_scaling_case" not in metafunc.fixturenames:
        return
    import pytest
    from django.apps import apps
    from django.conf import settings

    cases = scaling_cases() if settings.configured and apps.ready else []
    metafunc.parametrize(
        "karni_scaling_case",
        [pytest.param(case, id=case.id, marks=_database_marks(case)) for case in cases],
    )


def _database_marks(case: ScalingCase) -> list[Any]:
    """A model on another database (``Karni.database``) is measured on that alias too."""
    import pytest
    from django.db import router

    model = getattr(case.viewset, "model", None)
    alias = router.db_for_read(model) if model is not None else "default"
    if alias in (None, "default"):
        return []
    return [pytest.mark.django_db(databases=["default", alias])]


def test_list_and_retrieve_queries_do_not_grow_with_rows(
    db: None, karni_scaling_case: ScalingCase
) -> None:
    """Every routed project viewset's ``list``/``retrieve`` (and ``aggregate``) is N-independent."""
    import pytest

    if karni_scaling_case.optout_error:
        raise KarniAssertionError(karni_scaling_case.optout_error, code="E130")
    result = check_scaling(karni_scaling_case)
    if result.skipped:
        pytest.skip(result.skipped)
    if result.grows:
        raise KarniAssertionError(result.message(), code="E129")
    if result.too_slow:
        raise KarniAssertionError(result.slow_message(), code="E476")
