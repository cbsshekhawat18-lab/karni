"""Architecture rules — each a pure ``check_*() -> list[Violation]`` function.

Run as tests (``pytest --pyargs karni.testing.architecture``) or through
``manage.py karni_check`` (entry point ``karni.checks:architecture``).
No Django work happens at module import; checks touch no database.

Opt-out, on the offending line / the line above a class-def / the line above
its first decorator::

    # karni: allow(<rule-id>): <reason>
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from importlib import import_module
from pathlib import Path

from django.apps import AppConfig
from django.utils.module_loading import module_has_submodule

from karni.agent.check import (
    SqlVisitor,
    access_override_defs,
    http_client_imports,
    unpaginated_action_calls,
)
from karni.exceptions import KarniAssertionError
from karni.testing import checkcache
from karni.testing._source import (
    Violation,
    check_optout,
    class_marker_lines,
    config,
    matches_any,
    project_app_configs,
    project_sources,
    relative,
)

# The N+1 scaling check needs a database, so it lives in karni.testing.performance;
# importing it here puts it in the suite every Karni project already runs in CI
# (`pytest --pyargs karni.testing.architecture`). Collected by pytest only.
from karni.testing.performance import (  # noqa: F401
    pytest_generate_tests,
    test_list_and_retrieve_queries_do_not_grow_with_rows,
)

VIEWSET_MODULES = ("viewsets", "api", "serializers")


def _project_modules(cfg: AppConfig) -> list[object]:
    modules = []
    for name in VIEWSET_MODULES:
        if module_has_submodule(cfg.module, name):
            modules.append(import_module(f"{cfg.name}.{name}"))
    return modules


def _class_violation(cls: type, rule: str, message: str, hint: str = "") -> list[Violation]:
    marked = class_marker_lines(cls)
    if marked is None:  # generated class, unretrievable source — skip (F2)
        return []
    path, lines = marked
    violation = Violation(
        rule=rule, location=f"{relative(path)}:{lines[-1]}", message=message, hint=hint
    )
    return check_optout(path, rule, lines, violation)


# model-base


def check_model_base() -> list[Violation]:
    from karni.models import (
        AuditedModel,
        IntegerKeyModel,
        SoftDeleteModel,
        TimestampedModel,
        UUIDModel,
    )

    # BaseModel, BigIntBaseModel or any composition of Karni's mixins counts;
    # only a model built on django.db.models.Model alone is a violation.
    karni_bases = (UUIDModel, IntegerKeyModel, TimestampedModel, SoftDeleteModel, AuditedModel)

    violations: list[Violation] = []
    for cfg in project_app_configs():
        for model in cfg.get_models():
            if model._meta.auto_created or model._meta.proxy:
                continue
            if _is_external_table(model):
                continue
            if issubclass(model, karni_bases):
                continue
            violations += _class_violation(
                model,
                "model-base",
                f"{model.__name__} inherits django.db.models.Model directly",
                "inherit karni.models.BaseModel (or compose its mixins)",
            )
    return violations


def _is_external_table(model: type) -> bool:
    """A table or view another system owns (``karni.db``, experimental): model-base accepts it.

    Both declarations are needed: ``class Karni: external = True`` and
    ``Meta.managed = False`` (``karni.E270`` reports the first without the second).
    """
    from karni.db import is_external

    return is_external(model) and not model._meta.managed  # type: ignore[attr-defined]


# viewset-base


def _viewset_candidates() -> list[type]:
    """Project viewsets: GenericViewSet subclasses in project modules + the router's."""
    from rest_framework.viewsets import GenericViewSet

    seen: set[type] = set()
    candidates: list[type] = []
    for cfg in project_app_configs():
        for module in _project_modules(cfg):
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, GenericViewSet)
                    and obj.__module__.startswith(cfg.name)
                    and obj not in seen
                ):
                    seen.add(obj)
                    candidates.append(obj)
    project_prefixes = tuple(cfg.name for cfg in project_app_configs())
    try:
        from django.conf import settings
        from django.utils.module_loading import import_string

        factory = import_string(
            getattr(settings, "KARNI_API_ROUTER", "karni.api.routers.get_default_router")
        )
        for _prefix, viewset, _basename in factory().registry:
            if viewset.__module__.startswith(project_prefixes) and viewset not in seen:
                seen.add(viewset)
                candidates.append(viewset)
    except Exception:  # noqa: BLE001 - registry inspection is best-effort
        pass
    return candidates


def check_viewset_base() -> list[Violation]:
    from karni.api import BaseViewSet

    violations: list[Violation] = []
    for cls in _viewset_candidates():
        if not issubclass(cls, BaseViewSet):
            violations += _class_violation(
                cls,
                "viewset-base",
                f"{cls.__name__} bypasses BaseViewSet",
                "inherit karni.api.BaseViewSet",
            )
    return violations


# viewset-access


def check_viewset_access() -> list[Violation]:
    """A routable BaseViewSet (``model``/``queryset`` set) with no ``access`` (ADR 0001 Q2.1).

    An inherited declaration counts, and so does an overridden
    ``get_access()``. Abstract bases without a model are skipped. Opting out
    only silences the build: at runtime the viewset still denies everything.
    """
    from karni.api import BaseViewSet

    violations: list[Violation] = []
    for cls in _viewset_candidates():
        if not issubclass(cls, BaseViewSet):
            continue  # viewset-base reports it
        if getattr(cls, "access", None) is not None:
            continue
        if cls.get_access is not BaseViewSet.get_access:
            continue
        if cls.model is None and cls.queryset is None:
            continue
        violations += _class_violation(
            cls,
            "viewset-access",
            f"{cls.__name__} declares no access, so every request is denied",
            "add access = Access(read=..., write=...), or Unscoped(reason=...)",
        )
    return violations


# access-override


def check_access_override() -> list[Violation]:
    """Every ``filter_queryset_for_user`` override in project code needs a reason (Q2.7)."""
    return _each_file(_access_override_in)


def _access_override_in(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, candidates in access_override_defs(tree):
        violations += check_optout(
            path,
            "access-override",
            candidates,
            Violation(
                rule="access-override",
                location=f"{relative(path)}:{lineno}",
                message="filter_queryset_for_user is overridden",
                hint="express the row rule in access (Where(...)), or add an "
                "allow marker with the reason",
            ),
        )
    return violations


# unpaginated-action


def check_unpaginated_action() -> list[Violation]:
    """List-returning actions must paginate (ADR 0001 Q3.6).

    An ``@action`` (or ``list`` override) serialising ``many=True`` without
    ``paginate_queryset`` / ``paginated_response`` returns a whole table.
    """
    return _each_file(_unpaginated_action_in)


def _unpaginated_action_in(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, candidates in unpaginated_action_calls(tree):
        violations += check_optout(
            path,
            "unpaginated-action",
            candidates,
            Violation(
                rule="unpaginated-action",
                location=f"{relative(path)}:{lineno}",
                message="list-returning action serialises many=True without pagination",
                hint="return self.paginated_response(queryset), or add an allow "
                "marker with the reason",
            ),
        )
    return violations


# admin-convention


def check_admin_convention() -> list[Violation]:
    from django.contrib.admin.sites import all_sites

    from karni.admin import KarniModelAdmin

    project_models = {model for cfg in project_app_configs() for model in cfg.get_models()}
    violations: list[Violation] = []
    judged: set[tuple[type, type]] = set()
    for site in all_sites:
        for model, model_admin in site._registry.items():
            cls = type(model_admin)
            if model not in project_models or (model, cls) in judged:
                continue
            judged.add((model, cls))
            if isinstance(model_admin, KarniModelAdmin):
                continue
            violations += _class_violation(
                cls,
                "admin-convention",
                f"{cls.__name__} (for {model.__name__}) is not a KarniModelAdmin",
                "subclass karni.admin.KarniModelAdmin or use AdminMeta on the model",
            )
    return violations


# raw-sql


def check_raw_sql() -> list[Violation]:
    allowed = config("sql_allowed")
    return _each_file(_raw_sql_in, lambda path: not matches_any(path, allowed))


def _raw_sql_in(path: Path, tree: ast.Module) -> list[Violation]:
    visitor = SqlVisitor()
    visitor.visit(tree)
    violations: list[Violation] = []
    for lineno, what in visitor.hits:
        violations += check_optout(
            path,
            "raw-sql",
            [lineno],
            Violation(
                rule="raw-sql",
                location=f"{relative(path)}:{lineno}",
                message=f"raw SQL via {what} outside an allowed directory",
                hint="move it under a sql_allowed path or add an allow marker",
            ),
        )
    return violations


# http-client (import-based only, F9)


def check_http_client() -> list[Violation]:
    allowed = config("http_allowed")
    return _each_file(_http_client_in, lambda path: not matches_any(path, allowed))


def _http_client_in(path: Path, tree: ast.Module) -> list[Violation]:
    # One finding per import statement, shared with `karni rules --check`.
    violations: list[Violation] = []
    for lineno, name in http_client_imports(tree):
        violations += check_optout(
            path,
            "http-client",
            [lineno],
            Violation(
                rule="http-client",
                location=f"{relative(path)}:{lineno}",
                message=f"direct HTTP client import: {name}",
                hint="call it from a */services/* module instead",
            ),
        )
    return violations


# redundant-serializer (conservative per F3)


def _is_meta_only(cls: type, stop: type) -> bool:
    for klass in cls.__mro__:
        # Karni's own serializer bases (e.g. KarniModelSerializer) carry
        # framework attributes; only the project's classes count as a body.
        if klass is stop or klass.__module__.startswith("karni."):
            break
        body = {
            k
            for k in vars(klass)
            if not k.startswith("__") and k not in {"Meta", "_declared_fields"}
        }
        if body or getattr(klass, "_declared_fields", {}):
            return False
    return True


def _field_signature(serializer: object) -> dict[str, tuple[str, bool, bool]]:
    sig = {}
    for name, field in serializer.fields.items():  # type: ignore[attr-defined]
        type_name = type(field).__name__.removeprefix("Karni")
        sig[name] = (type_name, bool(field.read_only), bool(field.write_only))
    return sig


def check_redundant_serializer() -> list[Violation]:
    from rest_framework.serializers import ModelSerializer

    from karni.api.serializers import build_serializer

    violations: list[Violation] = []
    seen: set[type] = set()
    for cfg in project_app_configs():
        for module in _project_modules(cfg):
            for obj in vars(module).values():
                if (
                    not isinstance(obj, type)
                    or not issubclass(obj, ModelSerializer)
                    or obj is ModelSerializer
                    or not obj.__module__.startswith(cfg.name)
                    or obj in seen
                ):
                    continue
                seen.add(obj)
                model = getattr(getattr(obj, "Meta", None), "model", None)
                if model is None or not _is_meta_only(obj, ModelSerializer):
                    continue
                try:
                    generated = build_serializer(model)
                    if _field_signature(obj()) == _field_signature(generated()):
                        violations += _class_violation(
                            obj,
                            "redundant-serializer",
                            f"{obj.__name__} is identical to the auto-generated serializer",
                            f"delete it, since BaseViewSet(model={model.__name__}) generates this",
                        )
                except Exception:  # noqa: BLE001 - one bad model must not kill the rule
                    continue
    return violations


# aggregation

# audited-bulk-write (ADR 0002, P4)


def _audited_model_names() -> set[str]:
    """Class names of every model that keeps change history (``Karni.audit``)."""
    from django.apps import apps

    from karni.meta import karni_option

    return {model.__name__ for model in apps.get_models() if karni_option(model, "audit", False)}


def _receiver_root(node: ast.expr) -> str | None:
    """The leftmost name of an attribute/call chain (``Price`` in ``Price.objects.filter()``)."""
    current: ast.expr = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Name):
            return current.id
        else:
            return None


def check_audited_bulk_write() -> list[Violation]:
    """``QuerySet.update()`` / ``bulk_update()`` on an audited model bypass its history."""
    audited = _audited_model_names()
    if not audited:
        return []
    return _each_file(lambda path, tree: _audited_bulk_write_in(path, tree, audited))


def _audited_bulk_write_in(path: Path, tree: ast.Module, audited: set[str]) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"update", "bulk_update"}
        ):
            continue
        root = _receiver_root(node.func.value)
        if root not in audited:
            continue
        violations += check_optout(
            path,
            "audited-bulk-write",
            [node.lineno],
            Violation(
                rule="audited-bulk-write",
                location=f"{relative(path)}:{node.lineno}",
                message=(
                    f"{root}.…{node.func.attr}() bypasses the change history "
                    f"{root} keeps (Karni.audit): no entry is written"
                ),
                hint="save() each instance instead, or add an allow marker with the reason",
            ),
        )
    return violations


# running every rule, with the check cache (experimental)

FileRule = Callable[[Path, ast.Module], list[Violation]]


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text())
    except (OSError, SyntaxError, ValueError):
        return None


def _each_file(rule: FileRule, applies: Callable[[Path], bool] | None = None) -> list[Violation]:
    """``rule`` over every project source file ``applies`` to, parsed once each."""
    violations: list[Violation] = []
    for cfg in project_app_configs():
        for path in project_sources(cfg):
            if applies is not None and not applies(path):
                continue
            tree = _parse(path)
            if tree is not None:
                violations += rule(path, tree)
    return violations


# hand-written-tree (tree models, experimental)


def _self_parent(model: type) -> str | None:
    """The name of a ``parent`` foreign key from ``model`` to itself, else ``None``."""
    for field in model._meta.concrete_fields:  # type: ignore[attr-defined]
        if not (field.many_to_one and field.related_model is model):
            continue
        if field.name == "parent" or field.name.startswith("parent_"):
            return str(field.name)
    return None


def check_hand_written_tree() -> list[Violation]:
    """Experimental. A project model with a ``parent`` foreign key to itself, not a tree model."""
    from karni.models import TreeModel

    violations: list[Violation] = []
    for cfg in project_app_configs():
        for model in cfg.get_models():
            if model._meta.auto_created or model._meta.proxy or issubclass(model, TreeModel):
                continue
            name = _self_parent(model)
            if name is None:
                continue
            violations += _class_violation(
                model,
                "hand-written-tree",
                f"{model.__name__}.{name} is a foreign key to {model.__name__} itself: a "
                "hand-written tree, without cycle-safe queries, tree endpoints or a tree UI",
                "inherit karni.models.TreeModel first (class "
                f"{model.__name__}(TreeModel, BaseModel)) and drop the field, or opt out with "
                "the reason",
            )
    return violations


def _file_rules() -> dict[str, tuple[FileRule, Callable[[Path], bool] | None, str]]:
    """The rules that read one file at a time: ``name -> (rule, applies, extra inputs)``."""
    sql, http = config("sql_allowed"), config("http_allowed")
    audited = _audited_model_names()
    rules: dict[str, tuple[FileRule, Callable[[Path], bool] | None, str]] = {
        "access-override": (_access_override_in, None, ""),
        "unpaginated-action": (_unpaginated_action_in, None, ""),
        "raw-sql": (_raw_sql_in, lambda path: not matches_any(path, sql), ""),
        "http-client": (_http_client_in, lambda path: not matches_any(path, http), ""),
    }
    if audited:
        rules["audited-bulk-write"] = (
            lambda path, tree: _audited_bulk_write_in(path, tree, audited),
            None,
            ",".join(sorted(audited)),
        )
    return rules


class _Source:
    """One source file, parsed the first time a rule needs it (never when every rule hits)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._tree: list[ast.Module | None] = []

    def tree(self) -> ast.Module | None:
        if not self._tree:
            self._tree.append(_parse(self.path))
        return self._tree[0]

    def runner(self, rule: FileRule) -> Callable[[], list[list[str]]]:
        def run() -> list[list[str]]:
            tree = self.tree()
            if tree is None:
                return []
            return [[v.rule, v.location, v.message, v.hint] for v in rule(self.path, tree)]

        return run


def _cached_file_rules(cache: checkcache.CheckCache) -> dict[str, list[Violation]]:
    """Every file rule's findings, each file parsed at most once, unchanged files from the cache."""
    rules = _file_rules()
    for name, (_rule, _applies, extra) in rules.items():
        cache.extra(f"architecture:{name}", extra)
    found: dict[str, list[Violation]] = {name: [] for name in rules}
    for cfg in project_app_configs():
        for path in project_sources(cfg):
            if not cache.wanted(path):
                continue
            source = _Source(path)
            for name, (rule, applies, _extra) in rules.items():
                if applies is None or applies(path):
                    rows = cache.per_file(f"architecture:{name}", path, source.runner(rule))
                    found[name] += [Violation(*row) for row in rows]
    return found


ALL_CHECKS = (
    check_model_base,
    check_viewset_base,
    check_viewset_access,
    check_access_override,
    check_unpaginated_action,
    check_admin_convention,
    check_raw_sql,
    check_http_client,
    check_redundant_serializer,
    check_audited_bulk_write,
    check_hand_written_tree,
)


#: The rules that read one file at a time, by their check function (the check cache).
_FILE_RULES = {
    check_access_override: "access-override",
    check_unpaginated_action: "unpaginated-action",
    check_raw_sql: "raw-sql",
    check_http_client: "http-client",
    check_audited_bulk_write: "audited-bulk-write",
}


def run_checks() -> list[str]:
    """``karni.checks`` entry point: every architecture violation, rendered.

    The rules that read one file at a time go through the active check cache
    (:mod:`karni.testing.checkcache`, experimental): an unchanged file is not
    parsed again. With ``--changed`` only the findings in the changed files
    are reported.
    """
    cache = checkcache.active()
    cached = _cached_file_rules(cache)
    found: list[Violation] = []
    for check in ALL_CHECKS:
        name = _FILE_RULES.get(check)
        if name is not None:
            found += cached.get(name, [])
        else:
            found += [v for v in check() if cache.reports(v.location)]
    return [v.render() for v in found]


# pytest surface


def _assert_clean(violations: list[Violation]) -> None:
    if violations:
        raise KarniAssertionError(
            f"{len(violations)} architecture violation(s). Each names its rule and fix "
            "(`karni explain <code>` for more):\n" + "\n".join(v.render() for v in violations),
            code="E702",
        )


def test_models_inherit_base_model() -> None:
    _assert_clean(check_model_base())


def test_viewsets_inherit_base_viewset() -> None:
    _assert_clean(check_viewset_base())


def test_viewsets_declare_access() -> None:
    _assert_clean(check_viewset_access())


def test_access_overrides_state_a_reason() -> None:
    _assert_clean(check_access_override())


def test_list_actions_are_paginated() -> None:
    _assert_clean(check_unpaginated_action())


def test_admins_follow_the_override_convention() -> None:
    _assert_clean(check_admin_convention())


def test_no_raw_sql_outside_allowed_dirs() -> None:
    _assert_clean(check_raw_sql())


def test_no_direct_http_clients() -> None:
    _assert_clean(check_http_client())


def test_no_redundant_serializers() -> None:
    _assert_clean(check_redundant_serializer())


def test_audited_models_are_not_bulk_written() -> None:
    _assert_clean(check_audited_bulk_write())


def test_trees_inherit_tree_model() -> None:
    _assert_clean(check_hand_written_tree())
