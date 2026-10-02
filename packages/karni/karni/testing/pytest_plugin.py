"""Karni's pytest plugin — loaded automatically wherever ``karni`` is installed.

Registered through the ``pytest11`` entry point ``karni``. It does two things
and nothing at all outside a configured Django project:

* **Budgets raise in tests.** For the whole session it sets
  ``settings.KARNI_QUERY_BUDGET_MODE = "raise"``: a test request that pushes
  a ``BaseViewSet`` action over its query budget fails with the grouped
  duplicate report (:mod:`karni.performance`). ``override_settings`` still
  changes it per test.
* **Fixture** ``query_budget`` — :func:`karni.testing.performance.query_budget`::

      def test_report(client, query_budget):
          with query_budget(4):
              client.get("/reports/weekly/")

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
    group = parser.getgroup("karni")
    group.addoption(
        "--karni-query-budget",
        dest="karni_query_budget",
        choices=_MODES,
        default=None,
        help="KARNI_QUERY_BUDGET_MODE for this run (overrides the ini option).",
    )


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


@pytest.fixture
def query_budget() -> Callable[..., Any]:
    """``with query_budget(n): ...`` — fail if the block runs more than ``n`` queries."""
    from karni.testing.performance import query_budget as budget

    return budget
