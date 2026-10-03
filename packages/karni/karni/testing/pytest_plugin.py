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
* **Fixture** ``query_budget`` — :func:`karni.testing.performance.query_budget`::

      def test_report(client, query_budget):
          with query_budget(4):
              client.get("/reports/weekly/")

* **Fixture** ``client_as`` — :meth:`karni.testing.APITestCase.client_as` for
  pytest-style tests (the same roles give the same user within a test)::

      def test_cancel(client_as):
          assert client_as("organizer").post(url).status_code == 200

Override / escape hatches: ``pytest --karni-query-budget=warn`` (or ``off``)
for one run, ``karni_query_budget_mode = warn`` in the pytest ini file for the
project, ``-p no:karni`` to disable the plugin entirely.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

_MODES = ("raise", "warn", "off")
_UNSET = object()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "karni_query_budget_mode",
        "KARNI_QUERY_BUDGET_MODE for the test session: raise (default), warn or off.",
        default="raise",
    )
    parser.addini(
        "karni_seed",
        "Seed for factory/Faker randomness, reseeded per test (default 0; 'off' to disable).",
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
        "--karni-update-snapshots",
        dest="karni_update_snapshots",
        action="store_true",
        default=False,
        help="Rewrite OpenAPI snapshots instead of comparing them.",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("karni_update_snapshots", default=False):
        from karni.testing import schema

        schema.UPDATE_SNAPSHOTS = True


def _mode(config: pytest.Config) -> str:
    mode = config.getoption("karni_query_budget") or config.getini("karni_query_budget_mode")
    if mode not in _MODES:
        raise pytest.UsageError(
            f"karni_query_budget_mode = {mode!r}; expected one of {', '.join(_MODES)}."
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
