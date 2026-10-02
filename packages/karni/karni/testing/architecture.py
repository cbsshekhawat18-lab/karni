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
from importlib import import_module

from django.apps import AppConfig
from django.utils.module_loading import module_has_submodule

from karni.agent.check import SqlVisitor, http_client_imports
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


# --- model-base ---------------------------------------------------------------


def check_model_base() -> list[Violation]:
    from karni.models import AuditedModel, SoftDeleteModel, TimestampedModel, UUIDModel

    # BaseModel or any composition of Karni's mixins counts; only a model
    # built on django.db.models.Model alone is a violation.
    karni_bases = (UUIDModel, TimestampedModel, SoftDeleteModel, AuditedModel)

    violations: list[Violation] = []
    for cfg in project_app_configs():
        for model in cfg.get_models():
            if model._meta.auto_created or model._meta.proxy:
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


# --- viewset-base -------------------------------------------------------------


def check_viewset_base() -> list[Violation]:
    from rest_framework.viewsets import GenericViewSet

    from karni.api import BaseViewSet

    violations: list[Violation] = []
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
    for cls in candidates:
        if not issubclass(cls, BaseViewSet):
            violations += _class_violation(
                cls,
                "viewset-base",
                f"{cls.__name__} bypasses BaseViewSet",
                "inherit karni.api.BaseViewSet",
            )
    return violations


# --- admin-convention ---------------------------------------------------------


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


# --- raw-sql ------------------------------------------------------------------


def check_raw_sql() -> list[Violation]:
    allowed = config("sql_allowed")
    violations: list[Violation] = []
    for cfg in project_app_configs():
        for path in project_sources(cfg):
            if matches_any(path, allowed):
                continue
            try:
                tree = ast.parse(path.read_text())
            except (OSError, SyntaxError):
                continue
            visitor = SqlVisitor()
            visitor.visit(tree)
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


# --- http-client (import-based only, F9) -------------------------------------


def check_http_client() -> list[Violation]:
    allowed = config("http_allowed")
    violations: list[Violation] = []
    for cfg in project_app_configs():
        for path in project_sources(cfg):
            if matches_any(path, allowed):
                continue
            try:
                tree = ast.parse(path.read_text())
            except (OSError, SyntaxError):
                continue
            # One finding per import statement, shared with `karni rules --check`.
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


# --- redundant-serializer (conservative per F3) --------------------------------


def _is_meta_only(cls: type, stop: type) -> bool:
    for klass in cls.__mro__:
        if klass is stop:
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
                            f"delete it — BaseViewSet(model={model.__name__}) generates this",
                        )
                except Exception:  # noqa: BLE001 - one bad model must not kill the rule
                    continue
    return violations


# --- aggregation --------------------------------------------------------------

ALL_CHECKS = (
    check_model_base,
    check_viewset_base,
    check_admin_convention,
    check_raw_sql,
    check_http_client,
    check_redundant_serializer,
)


def run_checks() -> list[str]:
    """``karni.checks`` entry point: every architecture violation, rendered."""
    return [v.render() for check in ALL_CHECKS for v in check()]


# --- pytest surface -----------------------------------------------------------


def _assert_clean(violations: list[Violation]) -> None:
    assert not violations, "\n" + "\n".join(v.render() for v in violations)


def test_models_inherit_base_model() -> None:
    _assert_clean(check_model_base())


def test_viewsets_inherit_base_viewset() -> None:
    _assert_clean(check_viewset_base())


def test_admins_follow_the_override_convention() -> None:
    _assert_clean(check_admin_convention())


def test_no_raw_sql_outside_allowed_dirs() -> None:
    _assert_clean(check_raw_sql())


def test_no_direct_http_clients() -> None:
    _assert_clean(check_http_client())


def test_no_redundant_serializers() -> None:
    _assert_clean(check_redundant_serializer())
