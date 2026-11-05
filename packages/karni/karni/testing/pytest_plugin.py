"""Karni's pytest plugin — loaded automatically wherever ``karni`` is installed.

Registered through the ``pytest11`` entry point ``karni``. Outside a
configured Django project it only reseeds factory randomness:

* **Reproducible test data.** Before every test, factory-boy's and Faker's
  shared random generator is reseeded from ``karni_seed`` (default ``0``)
  and the test's node id, so generated values (:mod:`karni.testing.values`)
  are the same on every run and independent of test order. ``--karni-seed=N``
  changes the seed for one run, ``--karni-seed=off`` leaves randomness alone.
* **Snapshots.** ``--karni-update-snapshots`` rewrites OpenAPI snapshots
  instead of comparing them (:func:`karni.testing.assert_schema_snapshot`).
* **Budgets raise in tests.** For the whole session it sets
  ``settings.KARNI_QUERY_BUDGET_MODE = "raise"``: a test request that pushes
  a ``BaseViewSet`` action over its query budget fails with the grouped
  duplicate report (:mod:`karni.performance`). ``override_settings`` still
  changes it per test.
* **A cache of their own.** Every cache alias in ``CACHES`` is a
  local-memory cache for the test, empty at its start, so nothing a test
  caches (rate-limit counters, "already queued" flags, cached pages) reaches
  another test, a later run or the development server sharing Redis. A
  ``DummyCache`` alias stays as it is. ``@pytest.mark.karni_project_cache``
  keeps the project's own ``CACHES`` for one test (one that needs Redis),
  and ``karni_test_cache = project`` in the pytest ini file for every test.
* **Fresh rate limits per test.** DRF's throttles keep their counters in a
  cache of their own for each test, empty at its start, so tests that post
  to a public form (``KARNI_PUBLIC_CREATE_RATE``) or log in many times do
  not use up each other's limits, and a run never inherits the counters of
  an earlier run from Redis. A test that checks a limit still sees it work.
  This holds with the project's own cache too.
* **Tables for external models** (experimental). Once a test database is
  migrated, every external model routed to it (``class Karni: external =
  True``, :mod:`karni.db`) whose table or view is missing gets a table built
  from its fields, and on PostgreSQL the schema its ``db_table`` names
  (:func:`karni.testing.external.create_external_tables`). A table or view
  that exists already is left alone. ``--karni-external-tables=off`` (or
  ``karni_external_tables = off`` in the ini file) turns it off.
* **Fixture** ``query_budget`` — :func:`karni.testing.performance.query_budget`::

      def test_report(client, query_budget):
          with query_budget(4):
              client.get("/reports/weekly/")

* **Fixture** ``client_as`` — :meth:`karni.testing.APITestCase.client_as` for
  pytest-style tests (the same roles give the same user within a test)::

      def test_cancel(client_as):
          assert client_as("organizer").post(url).status_code == 200

Override / escape hatches: ``pytest --karni-external-tables=off`` to create no
table for external models, ``pytest --karni-query-budget=warn`` (or ``off``)
for one run, ``karni_query_budget_mode = warn`` in the pytest ini file for the
project, ``-p no:karni`` to disable the plugin entirely. Define a fixture
named ``_karni_fresh_throttles`` in ``conftest.py`` to replace the per-test
throttle cache (an empty one that does nothing keeps the shared cache), or
one named ``_karni_test_cache`` to replace the per-test cache.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from karni.errorcodes import docs_url

_MODES = ("raise", "warn", "off")
_CACHE_MODES = ("locmem", "project")
_PROJECT_CACHE_MARK = "karni_project_cache"
_DUMMY_CACHE = "django.core.cache.backends.dummy.DummyCache"
#: What a test's local-memory cache keeps of the project's alias.
_CACHE_KEYS_KEPT = ("KEY_PREFIX", "VERSION", "KEY_FUNCTION", "TIMEOUT")
_UNSET = object()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "karni_query_budget_mode",
        "KARNI_QUERY_BUDGET_MODE for the test session: raise (default), warn or off.",
        default="raise",
    )
    parser.addini(
        "karni_test_cache",
        "The cache tests use: locmem (default, one empty local-memory cache per test) or "
        "project (the project's own CACHES).",
        default="locmem",
    )
    parser.addini(
        "karni_external_tables",
        "Create the tables of external models in each test database: create (default) or off.",
        default="create",
    )
    parser.addini(
        "karni_seed",
        "Seed for factory/Faker randomness, reseeded per test (default 0, 'off' to disable).",
        default="0",
    )
    group = parser.getgroup("karni")
    group.addoption(
        "--karni-query-budget",
        dest="karni_query_budget",
        choices=_MODES,
        default=None,
        help="KARNI_QUERY_BUDGET_MODE for this run (overrides the ini option).",
    )
    group.addoption(
        "--karni-seed",
        dest="karni_seed",
        default=None,
        help="Seed for generated test data this run (overrides the karni_seed ini option).",
    )
    group.addoption(
        "--karni-external-tables",
        dest="karni_external_tables",
        choices=("create", "off"),
        default=None,
        help="Create the tables of external models in each test database (overrides the ini "
        "option).",
    )
    group.addoption(
        "--karni-update-snapshots",
        dest="karni_update_snapshots",
        action="store_true",
        default=False,
        help="Rewrite OpenAPI snapshots instead of comparing them.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{_PROJECT_CACHE_MARK}: keep the project's own CACHES for this test "
        "(Karni's plugin gives every other test an empty local-memory cache).",
    )
    if config.getoption("karni_update_snapshots", default=False):
        from karni.testing import schema

        schema.UPDATE_SNAPSHOTS = True
    _external_tables(config)


def _external_tables(config: pytest.Config) -> None:
    """Create the tables of external models after each test database's migrate (unless off)."""
    mode = config.getoption("karni_external_tables", default=None) or config.getini(
        "karni_external_tables"
    )
    if str(mode).strip().lower() not in {"create", "off"}:
        raise pytest.UsageError(
            f"karni_external_tables = {mode!r} is not valid. Set it (or "
            "--karni-external-tables) to create or off."
        )
    if str(mode).strip().lower() == "off":
        return
    try:
        from django.db.models.signals import post_migrate
    except ImportError:  # pragma: no cover - Django is a karni dependency
        return
    from karni.testing.external import after_migrate

    post_migrate.connect(after_migrate, dispatch_uid="karni.testing.external.after_migrate")


def _mode(config: pytest.Config) -> str:
    mode = config.getoption("karni_query_budget") or config.getini("karni_query_budget_mode")
    if mode not in _MODES:
        raise pytest.UsageError(
            f"E118: karni_query_budget_mode = {mode!r} is not valid. Set it (or "
            f"--karni-query-budget) to one of {', '.join(_MODES)}. See {docs_url('E118')}"
        )
    return str(mode)


@pytest.fixture(autouse=True, scope="session")
def _karni_query_budget_mode(request: pytest.FixtureRequest) -> Iterator[None]:
    """Session-wide ``KARNI_QUERY_BUDGET_MODE`` (``raise`` unless configured otherwise)."""
    mode = _mode(request.config)
    try:
        from django.conf import settings
    except ImportError:  # pragma: no cover - Django is a karni dependency
        yield
        return
    if not settings.configured:
        yield
        return
    previous = getattr(settings, "KARNI_QUERY_BUDGET_MODE", _UNSET)
    settings.KARNI_QUERY_BUDGET_MODE = mode
    try:
        yield
    finally:
        if previous is _UNSET:
            del settings.KARNI_QUERY_BUDGET_MODE
        else:
            settings.KARNI_QUERY_BUDGET_MODE = previous


def _cache_mode(config: pytest.Config) -> str:
    mode = str(config.getini("karni_test_cache")).strip().lower() or "locmem"
    if mode not in _CACHE_MODES:
        raise pytest.UsageError(
            f"karni_test_cache = {mode!r} is not valid. Set it to locmem (an empty "
            "local-memory cache per test) or project (the project's own CACHES)."
        )
    return mode


def _local_caches(configured: dict[str, Any]) -> dict[str, Any]:
    """The ``CACHES`` a test runs with: each alias a local-memory cache of its own.

    ``KEY_PREFIX``, ``VERSION``, ``KEY_FUNCTION`` and ``TIMEOUT`` are kept, so
    keys look as they do in the project. A ``DummyCache`` alias is kept as
    it is, since it already stores nothing.
    """
    found: dict[str, Any] = {}
    for alias, options in configured.items():
        if options.get("BACKEND") == _DUMMY_CACHE:
            found[alias] = dict(options)
            continue
        found[alias] = {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"karni-test-{alias}",
            **{key: options[key] for key in _CACHE_KEYS_KEPT if key in options},
        }
    return found


@pytest.fixture(autouse=True)
def _karni_test_cache(request: pytest.FixtureRequest) -> Iterator[None]:
    """Run the test on an empty local-memory cache per alias (``karni_test_cache``)."""
    try:
        from django.conf import settings
    except ImportError:  # pragma: no cover - Django is a karni dependency
        yield
        return
    if (
        not settings.configured
        or request.node.get_closest_marker(_PROJECT_CACHE_MARK) is not None
        or _cache_mode(request.config) == "project"
    ):
        yield
        return
    from django.core.cache import caches

    # Only CACHES is swapped and put back. override_settings would restore the
    # whole settings object, and so drop what a session fixture set up during
    # this test (pytest-django's --no-migrations sets MIGRATION_MODULES then).
    previous = settings.CACHES
    _swap_caches(settings, _local_caches(dict(previous)))
    try:
        for alias in settings.CACHES:
            caches[alias].clear()
        yield
    finally:
        for alias in settings.CACHES:
            caches[alias].clear()
        _swap_caches(settings, previous)


def _swap_caches(settings: Any, value: Any) -> None:
    """Set ``CACHES`` and tell Django, which then rebuilds its cache handlers."""
    from django.test.signals import setting_changed

    settings.CACHES = value
    setting_changed.send(sender=type(settings._wrapped), setting="CACHES", value=value, enter=True)


@pytest.fixture(autouse=True)
def _karni_fresh_throttles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give DRF's throttles an empty cache of their own for this test.

    ``SimpleRateThrottle.cache`` (shared by the ``anon``/``user`` throttles,
    the auth throttles and :class:`karni.api.throttling.ActionRateThrottle`)
    is the default cache, which outlives a test and, on Redis, a run.
    """
    try:
        from django.conf import settings
    except ImportError:  # pragma: no cover - Django is a karni dependency
        return
    if not settings.configured:
        return
    try:
        from django.core.cache.backends.locmem import LocMemCache
        from rest_framework.throttling import SimpleRateThrottle
    except ImportError:  # pragma: no cover - DRF is a karni dependency
        return
    throttle_cache = LocMemCache("karni-test-throttles", {})
    throttle_cache.clear()
    monkeypatch.setattr(SimpleRateThrottle, "cache", throttle_cache)


@pytest.fixture(autouse=True)
def _karni_seed(request: pytest.FixtureRequest) -> None:
    """Reseed factory-boy/Faker randomness from ``karni_seed`` and the test id."""
    seed = request.config.getoption("karni_seed") or request.config.getini("karni_seed")
    if str(seed).strip().lower() in {"off", "none", ""}:
        return
    try:
        from factory.random import reseed_random
    except ImportError:  # pragma: no cover - factory-boy is a karni dependency
        return
    reseed_random(f"{seed}:{request.node.nodeid}")


@pytest.fixture
def client_as(db: None) -> Callable[..., Any]:
    """``client_as(*roles, user=None)`` — a client per role; ``None`` alone is anonymous."""
    from karni.testing.api import client_as as make_client
    from karni.testing.api import user_with_roles

    users: dict[tuple[str, ...], Any] = {}

    def factory(*roles: str | None, user: Any = None) -> Any:
        if user is None and roles == (None,):
            return make_client(None)
        if user is None:
            key = tuple(sorted(role for role in roles if role))
            if key not in users:
                users[key] = user_with_roles(*key)
            user = users[key]
        return make_client(user=user)

    return factory


@pytest.fixture
def query_budget() -> Callable[..., Any]:
    """``with query_budget(n): ...`` — fail if the block runs more than ``n`` queries."""
    from karni.testing.performance import query_budget as budget

    return budget
