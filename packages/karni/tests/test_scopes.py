"""The named-scope pipeline (ADR 0001, Decision 1: the tenancy shape).

v1 ships one scope, ``soft_delete``. Most of this module proves that the
pipeline is ready for ``karni-tenancy``. It registers a test-only ``tenant``
scope the way the module will: through the registry, or a ``karni.scopes``
entry point, with no change to any model or manager. Then it checks that:

* the scope reaches ``objects``, related descriptors (FK and M2M),
  prefetches, the derived admin, and DRF lookups through
  ``_default_manager``;
* ``without(name, reason=...)`` lifts exactly the named scope, and the
  deprecated ``all_objects`` keeps the tenant (ADR rule R2);
* an unbound tenant raises an error that names the fix (ruling Q1.3);
* ``ScopeMeta.tenant = "shared"`` opts a model out (ruling Q1.6).

The models live in ``tests.scopeapp``, an installed app, so M2M query
names resolve. They are plain ``BaseModel``\\ s with a ``tenant`` column.
"""

from __future__ import annotations

import ast
import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Expression
from django.test import RequestFactory, override_settings
from rest_framework import serializers

import karni.scopes
from karni.admin.base import build_model_admin
from karni.checks import check_scopes
from karni.deprecation import (
    DOCS_BASE_URL,
    KarniDeprecationWarning,
    deprecation_message,
    docs_url,
    warn_deprecated,
)
from karni.introspect import scopes_section
from karni.managers import BaseManager, ScopedManagerMixin, SoftDeleteManager
from karni.models import BaseModel
from karni.scopes import (
    SOFT_DELETE,
    Scope,
    ScopeContextMissing,
    ScopeError,
    ScopeRegistry,
    SoftDeleteScope,
    UnknownScope,
    apply_scopes,
    registry,
    scope_option,
)
from tests.scopeapp.models import Country, Project, Task, Topic
from tests.testapp.models import Book, Event, Review, Shelf

APP_LABEL = "scopeapp"
WHY = "test: reach rows a scope hides"


# --- a fake tenant scope, bound through a ContextVar --------------------------

_current_tenant: ContextVar[str | None] = ContextVar("karni_tests_tenant", default=None)


@contextmanager
def tenant(name: str) -> Iterator[None]:
    """Bind the current tenant for a block (the fix the error message names)."""
    token = _current_tenant.set(name)
    try:
        yield
    finally:
        _current_tenant.reset(token)


class CurrentTenant(Expression):
    """The bound tenant, read when the SQL is compiled, not when it is built.

    This is why a class-level ``queryset = Model.objects.all()``, built at
    import time, still follows the tenant bound when it runs.
    """

    def __init__(self, model: type[models.Model]) -> None:
        super().__init__(output_field=models.CharField())
        self.model = model

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, list[str]]:
        value = _current_tenant.get()
        if value is None:
            raise ScopeContextMissing(
                self.model, "tenant", fix="wrap the code in `with tenant('<name>'):`"
            )
        return "%s", [value]


class FakeTenantScope(Scope):
    """What ``karni-tenancy`` will register, cut down to ``tests.scopeapp``."""

    name = "tenant"
    order = 20

    def applies_to(self, model: type[models.Model]) -> bool:
        return (
            issubclass(model, BaseModel)
            and model._meta.app_label == APP_LABEL
            and scope_option(model, "tenant") != "shared"
        )

    def filter(self, queryset: Any) -> Any:
        return queryset.filter(tenant=CurrentTenant(queryset.model))


@pytest.fixture
def tenant_scope() -> Iterator[Scope]:
    """Register the fake tenant scope for one test. No model or manager changes."""
    scope = registry.register(FakeTenantScope())
    yield scope
    registry.unregister(scope.name)


@pytest.fixture
def data(db: None) -> SimpleNamespace:
    """Two tenants with one live and one soft-deleted task each, plus shared rows."""
    acme = Project.objects.create(tenant="acme", name="Acme roadmap")
    globex = Project.objects.create(tenant="globex", name="Globex roadmap")
    ns = SimpleNamespace(acme=acme, globex=globex)
    ns.acme_task = Task.objects.create(tenant="acme", project=acme, title="acme live")
    ns.acme_dead = Task.objects.create(tenant="acme", project=acme, title="acme dead")
    ns.globex_task = Task.objects.create(tenant="globex", project=globex, title="globex live")
    ns.globex_dead = Task.objects.create(tenant="globex", project=globex, title="globex dead")
    # Inconsistent on purpose: a globex row under an acme parent proves that
    # related managers apply the scope themselves.
    ns.stray = Task.objects.create(tenant="globex", project=acme, title="stray")
    ns.acme_dead.delete()
    ns.globex_dead.delete()
    ns.acme_topic = Topic.objects.create(tenant="acme", name="acme topic")
    ns.globex_topic = Topic.objects.create(tenant="globex", name="globex topic")
    ns.acme_task.topics.add(ns.acme_topic, ns.globex_topic)
    ns.country = Country.objects.create(name="India")
    return ns


def _titles(queryset: Any) -> set[str]:
    return {task.title for task in queryset}


# --- the pipeline -------------------------------------------------------------


class TestPipeline:
    def test_core_registers_soft_delete_first(self) -> None:
        assert registry.names() == (SOFT_DELETE,)
        scope = registry.get(SOFT_DELETE)
        assert isinstance(scope, SoftDeleteScope)
        assert scope.order == 10
        assert registry.for_model(Shelf) == (scope,)
        assert registry.for_model(Review) == (scope,)  # a standalone SoftDeleteModel

    def test_every_karni_default_manager_runs_the_pipeline(self) -> None:
        from django.contrib.auth import get_user_model

        for manager in (Shelf.objects, Review.objects, get_user_model().objects):
            assert isinstance(manager, ScopedManagerMixin), manager
        assert issubclass(BaseManager, ScopedManagerMixin)
        assert issubclass(SoftDeleteManager, ScopedManagerMixin)

    @pytest.mark.django_db
    def test_apply_scopes_is_the_whole_default_filter(self) -> None:
        Shelf.objects.create(name="kept")
        Shelf.objects.create(name="gone").delete()
        everything = Shelf._base_manager.all()  # Django's unscoped base manager
        assert everything.count() == 2
        assert [s.name for s in apply_scopes(everything)] == ["kept"]
        assert apply_scopes(everything, lifted=frozenset({SOFT_DELETE})).count() == 2

    @pytest.mark.django_db
    def test_without_reads_past_a_prefetch_cache_but_keeps_the_relation(self) -> None:
        shelf = Shelf.objects.create(name="mine")
        Shelf.objects.create(name="other").books.create(title="stranger")
        alive = Book.objects.create(shelf=shelf, title="alive")
        dead = Book.objects.create(shelf=shelf, title="dead")
        dead.delete()

        prefetched = Shelf.objects.prefetch_related("books").get(pk=shelf.pk)
        assert list(prefetched.books.all()) == [alive]  # served by the prefetch
        assert set(prefetched.books.without(SOFT_DELETE, reason=WHY)) == {alive, dead}
        # The caller's instance and its prefetch cache are untouched.
        assert "books" in prefetched._prefetched_objects_cache
        assert list(prefetched.books.all()) == [alive]


class TestWithoutArguments:
    def test_reason_is_required(self) -> None:
        with pytest.raises(TypeError, match="reason"):
            Shelf.objects.without(SOFT_DELETE)  # type: ignore[call-arg]

    @pytest.mark.parametrize("reason", ["", "   ", None, 42])
    def test_reason_must_be_a_non_empty_string(self, reason: Any) -> None:
        with pytest.raises(ScopeError, match=r'needs a reason: pass reason="') as exc:
            Shelf.objects.without(SOFT_DELETE, reason=reason)
        assert 'Shelf.objects.without("soft_delete")' in str(exc.value)

    def test_a_scope_name_is_required(self) -> None:
        with pytest.raises(ScopeError, match=r'needs the name of the scope.*"soft_delete"'):
            Shelf.objects.without(reason=WHY)

    def test_querysets_point_back_to_the_manager(self) -> None:
        with pytest.raises(ScopeError, match=r"Shelf\.objects\.without\(\"soft_delete\", reason="):
            Shelf.objects.filter(name="x").without(SOFT_DELETE, reason=WHY)

    def test_unknown_names_raise_listing_the_registered_ones(self) -> None:
        with pytest.raises(UnknownScope, match="'soft-delete'.*registered: soft_delete"):
            Shelf.objects.without("soft-delete", reason=WHY)
        assert issubclass(UnknownScope, LookupError)

    @pytest.mark.django_db
    def test_the_reason_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="karni.scopes"):
            Shelf.objects.without(SOFT_DELETE, reason="restore screen")
        (record,) = [r for r in caplog.records if r.name == "karni.scopes"]
        assert record.levelno == logging.DEBUG  # soft_delete lifts are routine
        assert record.getMessage() == "lifted scope(s) soft_delete on testapp.Shelf: restore screen"

    @pytest.mark.django_db
    def test_lifting_a_scope_that_does_not_cover_the_model_is_a_no_op(
        self, tenant_scope: Scope
    ) -> None:
        # Shelf is outside the fake tenant scope; lifting it changes nothing.
        queryset = Shelf.objects.without("tenant", reason=WHY)
        assert str(queryset.query) == str(Shelf.objects.all().query)


# --- the tenant scope reaches every default-manager path -------------------------


@pytest.mark.django_db
class TestTenantScopeReach:
    def test_objects(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        with tenant("acme"):
            assert _titles(Task.objects.all()) == {"acme live"}
            assert list(Project.objects.all()) == [data.acme]
        with tenant("globex"):
            assert _titles(Task.objects.all()) == {"globex live", "stray"}

    def test_related_descriptors(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        with tenant("acme"):
            assert _titles(data.acme.tasks.all()) == {"acme live"}  # not "stray"
            assert list(data.acme_task.topics.all()) == [data.acme_topic]
            assert list(data.acme_topic.tasks.all()) == [data.acme_task]
        with tenant("globex"):  # the M2M link exists, the acme task is out of scope
            assert not data.acme_topic.tasks.exists()

    def test_prefetches(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        with tenant("acme"):
            (project,) = Project.objects.prefetch_related("tasks", "tasks__topics")
            (task,) = project.tasks.all()
            assert task.title == "acme live"
            assert list(task.topics.all()) == [data.acme_topic]

    def test_the_derived_admin(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        task_admin = build_model_admin(Task)(Task, admin.AdminSite())
        request = RequestFactory().get("/")
        with tenant("acme"):
            # The admin lifts soft_delete only: deleted acme rows, no globex ones.
            assert _titles(task_admin.get_queryset(request)) == {"acme live", "acme dead"}

    def test_drf_default_manager_lookups(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        class TaskSerializer(serializers.ModelSerializer):
            class Meta:
                model = Task
                fields = ["title", "tenant", "project"]

        payload = {"title": "x", "tenant": "acme"}
        with tenant("acme"):
            assert not Task._default_manager.filter(pk=data.globex_task.pk).exists()
            other = TaskSerializer(data={**payload, "project": str(data.globex.pk)})
            assert not other.is_valid()
            assert "does not exist" in str(other.errors["project"][0])
            assert TaskSerializer(data={**payload, "project": str(data.acme.pk)}).is_valid()

    def test_a_queryset_built_before_binding_follows_the_bound_tenant(
        self, tenant_scope: Scope, data: SimpleNamespace
    ) -> None:
        class_level = Task.objects.filter(title__endswith="live")  # e.g. a viewset attribute
        with tenant("acme"):
            assert _titles(class_level.all()) == {"acme live"}
        with tenant("globex"):
            assert _titles(class_level.all()) == {"globex live"}

    def test_shared_models_opt_out(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        assert scope_option(Country, "tenant") == "shared"
        assert scope_option(Task, "tenant") is None
        assert [s.name for s in registry.for_model(Country)] == [SOFT_DELETE]
        assert [s.name for s in registry.for_model(Task)] == [SOFT_DELETE, "tenant"]
        assert list(Country.objects.all()) == [data.country]  # no tenant needed


@pytest.mark.django_db
class TestWithoutLiftsOnlyTheNamedScope:
    def test_each_scope_alone_and_both(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        with tenant("acme"):
            assert _titles(Task.objects.without("tenant", reason=WHY)) == {
                "acme live",
                "globex live",
                "stray",
            }
            assert _titles(Task.objects.without(SOFT_DELETE, reason=WHY)) == {
                "acme live",
                "acme dead",
            }
            assert _titles(Task.objects.without(SOFT_DELETE, reason=WHY).dead()) == {"acme dead"}
            both = Task.objects.without(SOFT_DELETE, "tenant", reason=WHY)
            assert both.count() == 5

    def test_on_related_managers(self, tenant_scope: Scope, data: SimpleNamespace) -> None:
        with tenant("acme"):
            lifted = data.acme.tasks.without(SOFT_DELETE, reason=WHY)
            assert _titles(lifted) == {"acme live", "acme dead"}  # still no "stray"
            assert _titles(data.acme.tasks.without("tenant", reason=WHY)) == {
                "acme live",
                "stray",
            }

    def test_deprecated_aliases_keep_the_tenant(
        self, tenant_scope: Scope, data: SimpleNamespace
    ) -> None:
        with tenant("acme"), pytest.warns(KarniDeprecationWarning):
            assert _titles(Task.all_objects.all()) == {"acme live", "acme dead"}
            assert _titles(Task.objects.all_with_deleted()) == {"acme live", "acme dead"}
            assert _titles(Task.objects.deleted_only()) == {"acme dead"}

    def test_tenant_lifts_log_at_info(
        self, tenant_scope: Scope, data: SimpleNamespace, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="karni.scopes"):
            Task.objects.without("tenant", SOFT_DELETE, reason="billing report")
        (record,) = [r for r in caplog.records if r.name == "karni.scopes"]
        assert record.levelno == logging.INFO
        assert "billing report" in record.getMessage()


@pytest.mark.django_db
class TestUnboundTenantFailsClosed:
    def test_every_path_raises_naming_the_fix(
        self, tenant_scope: Scope, data: SimpleNamespace
    ) -> None:
        task_admin = build_model_admin(Task)(Task, admin.AdminSite())
        paths = {
            "objects": lambda: list(Task.objects.all()),
            "related": lambda: list(data.acme.tasks.all()),
            "m2m": lambda: list(data.acme_task.topics.all()),
            "prefetch": lambda: list(
                Project.objects.without("tenant", reason=WHY).prefetch_related("tasks")
            ),
            "admin": lambda: list(task_admin.get_queryset(RequestFactory().get("/"))),
            "lift soft_delete only": lambda: list(Task.objects.without(SOFT_DELETE, reason=WHY)),
        }
        for label, run in paths.items():
            with pytest.raises(ScopeContextMissing) as exc:
                run()
            message = str(exc.value)
            assert "is filtered by the 'tenant' scope, but no tenant is bound" in message, label
            assert "Fix: wrap the code in `with tenant('<name>'):`" in message, label
            assert '.objects.without("tenant", reason="...")' in message, label

    def test_lifting_the_tenant_or_a_shared_model_needs_no_binding(
        self, tenant_scope: Scope, data: SimpleNamespace
    ) -> None:
        assert Task.objects.without("tenant", reason=WHY).count() == 3
        assert Country.objects.count() == 1

    def test_the_default_fix_text(self) -> None:
        error = ScopeContextMissing(Task, "tenant")
        assert error.model is Task and error.scope == "tenant"
        assert "Fix: bind the current tenant before querying." in str(error)


# --- registration: entry points, KARNI_SCOPES, validation ------------------------


class FakeEntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self.value = f"tests.test_scopes:{name}"
        self._loaded = loaded

    def load(self) -> object:
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


@pytest.fixture
def entry_points(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[FakeEntryPoint]]:
    """Stand-in ``karni.scopes`` entry points; the registry re-reads them."""
    installed: list[FakeEntryPoint] = []

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        assert group == "karni.scopes"
        return list(installed)

    monkeypatch.setattr(karni.scopes, "metadata", SimpleNamespace(entry_points=fake_entry_points))
    registry.reset()
    yield installed
    monkeypatch.undo()
    registry.reset()


class TestRegistration:
    @pytest.mark.django_db
    def test_an_installed_module_adds_a_scope_with_no_project_code(
        self, entry_points: list[FakeEntryPoint]
    ) -> None:
        entry_points.append(FakeEntryPoint("tenant", FakeTenantScope))  # a class is instantiated
        registry.reset()

        assert registry.names() == (SOFT_DELETE, "tenant")
        assert [s.name for s in registry.for_model(Task)] == [SOFT_DELETE, "tenant"]
        with pytest.raises(ScopeContextMissing):
            list(Task.objects.all())

    def test_entry_points_must_name_a_scope(self, entry_points: list[FakeEntryPoint]) -> None:
        entry_points.append(FakeEntryPoint("broken", object()))
        registry.reset()
        with pytest.raises(ImproperlyConfigured, match="entry point 'broken'.*expected a karni"):
            registry.names()

    def test_entry_point_import_errors_name_the_entry_point(
        self, entry_points: list[FakeEntryPoint]
    ) -> None:
        entry_points.append(FakeEntryPoint("tenant", ImportError("no module karni_tenancy")))
        registry.reset()
        with pytest.raises(ImproperlyConfigured, match="'tenant'.*failed to load: no module"):
            registry.names()

    def test_names_are_unique(self, tenant_scope: Scope) -> None:
        with pytest.raises(ImproperlyConfigured, match="'tenant' is already registered"):
            registry.register(FakeTenantScope())

    @pytest.mark.parametrize(
        ("attrs", "error"),
        [
            ({"name": "not valid", "order": 1}, "name must be an identifier"),
            ({"name": "region", "order": "1"}, "order must be an int"),
        ],
    )
    def test_scopes_are_validated(self, attrs: dict[str, Any], error: str) -> None:
        bad = type("BadScope", (FakeTenantScope,), attrs)()
        with pytest.raises(ImproperlyConfigured, match=error):
            ScopeRegistry().register(bad)

    def test_unregistering_an_unknown_name_raises(self) -> None:
        with pytest.raises(UnknownScope):
            ScopeRegistry().unregister("tenant")


@pytest.mark.django_db
class TestKarniScopesSetting:
    def test_an_empty_list_switches_soft_delete_off(self) -> None:
        Shelf.objects.create(name="kept")
        Shelf.objects.create(name="gone").delete()
        with override_settings(KARNI_SCOPES=[]):
            assert registry.active() == ()
            assert Shelf.objects.count() == 2
            # Lifting a registered but disabled scope stays valid.
            assert Shelf.objects.without(SOFT_DELETE, reason=WHY).count() == 2
        assert Shelf.objects.count() == 1  # the cache resets with the setting

    def test_the_list_sets_the_order(self, tenant_scope: Scope) -> None:
        with override_settings(KARNI_SCOPES=["tenant", SOFT_DELETE]):
            assert [s.name for s in registry.active()] == ["tenant", SOFT_DELETE]

    @pytest.mark.parametrize(
        ("value", "error"),
        [
            (["soft_delete", "tenant"], "unknown scope.*tenant.*registered: soft_delete"),
            ("soft_delete", "must be a list of scope names"),
            (["soft_delete", "soft_delete"], "lists a scope twice"),
        ],
    )
    def test_bad_values_raise(self, value: Any, error: str) -> None:
        with override_settings(KARNI_SCOPES=value):
            with pytest.raises(ImproperlyConfigured, match=error):
                registry.active()
            (message,) = check_scopes()
            assert message.id == "karni.E002"

    def test_a_registered_scope_left_out_is_a_warning(self, tenant_scope: Scope) -> None:
        assert check_scopes() == []
        with override_settings(KARNI_SCOPES=[SOFT_DELETE]):
            (message,) = check_scopes()
        assert message.id == "karni.W001"
        assert "'tenant' is registered but not listed in KARNI_SCOPES" in message.msg


# --- karni context --------------------------------------------------------------


class OnlyEvents(Scope):
    name = "region"
    order = 30

    def applies_to(self, model: type[models.Model]) -> bool:
        return model is Event

    def filter(self, queryset: Any) -> Any:
        return queryset


class AllButEvents(OnlyEvents):
    name = "most"
    order = 31

    def applies_to(self, model: type[models.Model]) -> bool:
        return model is not Event


class Everything(OnlyEvents):
    name = "everything"
    order = 32

    def applies_to(self, model: type[models.Model]) -> bool:
        return True


@pytest.fixture
def testapp_only() -> Iterator[None]:
    """List only tests.testapp's models in ``karni context``."""
    from django.apps import apps

    others = [cfg.label for cfg in apps.get_app_configs() if cfg.label != "testapp"]
    with override_settings(KARNI_CONTEXT_SKIP_APPS=others):
        yield


@pytest.mark.django_db
class TestContextSection:
    def test_the_default_pipeline_prints_nothing(self) -> None:
        assert scopes_section() is None

    def test_non_default_scopes_are_listed_with_their_models(self, testapp_only: None) -> None:
        added = [OnlyEvents(), AllButEvents(), Everything()]
        for scope in added:
            registry.register(scope)
        try:
            line = scopes_section()
        finally:
            for scope in added:
                registry.unregister(scope.name)
        assert line == (
            "SCOPES: region(Event) most(all except Event) everything(all); "
            'lift: objects.without("<scope>", reason=...)'
        )

    def test_switching_soft_delete_off_is_printed(self) -> None:
        with override_settings(KARNI_SCOPES=[]):
            assert scopes_section() == (
                'SCOPES: soft_delete(off); lift: objects.without("<scope>", reason=...)'
            )


# --- deprecations ---------------------------------------------------------------

ALIAS_DOCS = DOCS_BASE_URL + "models.md#deprecated-soft-delete-aliases"
DEPRECATED_NAMES = {"all_objects", "all_with_deleted", "deleted_only", "SoftDeleteManagerMixin"}


class TestDeprecationHelper:
    def test_message_format_is_stable(self) -> None:
        assert deprecation_message("a()", "b()", removed_in="1.0", doc_anchor="x.md#y") == (
            "a() is deprecated; use b() instead. It will be removed in Karni 1.0. "
            f"See {DOCS_BASE_URL}x.md#y"
        )
        assert docs_url("/models.md#z") == DOCS_BASE_URL + "models.md#z"

    def test_warns_at_the_caller_of_the_deprecated_api(self) -> None:
        def deprecated() -> None:
            warn_deprecated("old()", "new()", removed_in="1.0", doc_anchor="models.md")

        with pytest.warns(KarniDeprecationWarning, match=r"old\(\) is deprecated") as record:
            deprecated()  # this line
        assert record[0].filename == __file__
        assert issubclass(KarniDeprecationWarning, DeprecationWarning)

    def test_the_suite_turns_karni_deprecations_into_errors(self) -> None:
        """pyproject.toml filterwarnings: an unasserted deprecated call fails a test."""
        with pytest.raises(KarniDeprecationWarning):
            warn_deprecated("old()", "new()", removed_in="1.0", doc_anchor="models.md")

    @pytest.mark.parametrize(
        ("module", "fails"),
        [("karni", True), ("karni.admin.base", True), ("karni_payments", False), ("django", False)],
    )
    def test_the_suite_fails_on_deprecations_karni_code_triggers(
        self, module: str, fails: bool
    ) -> None:
        """...and on any DeprecationWarning attributed to Karni's own modules."""
        with warnings.catch_warnings(record=True) as seen:
            try:
                warnings.warn_explicit("old API", DeprecationWarning, "x.py", 1, module=module)
            except DeprecationWarning:
                raised = True
            else:
                raised = False
        assert raised is fails
        assert len(seen) == (0 if fails else 1)


@pytest.mark.django_db
class TestSoftDeleteAliases:
    """``all_objects``, ``all_with_deleted()``, ``deleted_only()`` and the old mixin
    name still work in 0.2, warn, and go in 1.0."""

    @pytest.fixture
    def rows(self) -> SimpleNamespace:
        shelf = Shelf.objects.create(name="mine")
        Shelf.objects.create(name="other").books.create(title="stranger").delete()
        alive = Book.objects.create(shelf=shelf, title="alive")
        dead = Book.objects.create(shelf=shelf, title="dead")
        dead.delete()
        return SimpleNamespace(shelf=shelf, alive=alive, dead=dead)

    def test_all_objects(self, rows: SimpleNamespace) -> None:
        expected = (
            'Book.all_objects is deprecated; use Book.objects.without("soft_delete", '
            f"reason=...) instead. It will be removed in Karni 1.0. See {ALIAS_DOCS}"
        )
        with pytest.warns(KarniDeprecationWarning) as record:
            manager = Book.all_objects
        assert str(record[0].message) == expected
        assert record[0].filename == __file__
        assert manager.count() == 3
        assert isinstance(manager, BaseManager)
        assert manager.without(SOFT_DELETE, reason=WHY).count() == 3

    def test_all_with_deleted_and_deleted_only(self, rows: SimpleNamespace) -> None:
        with pytest.warns(KarniDeprecationWarning, match=r"objects\.all_with_deleted\(\)") as rec:
            everything = rows.shelf.books.all_with_deleted()
        assert rec[0].filename == __file__
        assert set(everything) == {rows.alive, rows.dead}  # the relation filter stays
        dead_only = r'without\("soft_delete", reason=\.\.\.\)\.dead\(\)'
        with pytest.warns(KarniDeprecationWarning, match=dead_only):
            assert list(rows.shelf.books.deleted_only()) == [rows.dead]
        with pytest.warns(KarniDeprecationWarning, match="removed in Karni 1.0"):
            assert Book.objects.deleted_only().count() == 2

    def test_the_old_mixin_name(self) -> None:
        with pytest.warns(KarniDeprecationWarning, match="use karni.managers.ScopedManagerMixin"):
            from karni.managers import SoftDeleteManagerMixin
        assert SoftDeleteManagerMixin is ScopedManagerMixin

    def test_no_internal_caller_uses_an_alias(self) -> None:
        """Karni's own code uses the new API. The suite's filterwarnings enforce
        this at runtime; this scan also covers paths no test executes."""
        package = Path(karni.scopes.__file__).parent
        defined_in = {package / "managers.py", package / "models.py"}
        offenders = []
        for path in sorted(package.rglob("*.py")):
            if path in defined_in:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Attribute):
                    names = [node.attr]
                elif isinstance(node, ast.Name):
                    names = [node.id]
                elif isinstance(node, ast.ImportFrom):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if DEPRECATED_NAMES.intersection(names):
                    offenders.append(f"{path.relative_to(package)}:{node.lineno}")
        assert offenders == []
