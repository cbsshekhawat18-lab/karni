"""The examples in docs/testing.md are real code: each is extracted and run here.

A block after ``<!-- karni:example:<name>`` is executed with its project
imports (``events.viewsets``, ``events.models``) pointed at the suite's
equivalents, so the documented test files cannot rot.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.test import override_settings

DOCS = Path(__file__).resolve().parents[4] / "docs" / "testing.md"
PROJECT_IMPORT = "from events.viewsets import EventViewSet"
IMPORTS = {
    PROJECT_IMPORT: "from tests.testing.crud_urls import EventViewSet",
    "from events.models import Event": "from tests.testapp.models import Event",
}
#: What the admin example's comment says the project declares.
ADMIN_ROLES = {"organizer": {"grants": {"testapp.event:*": "own"}}}

pytestmark = pytest.mark.django_db


def example_source(name: str = "crud") -> str:
    text = DOCS.read_text()
    match = re.search(rf"<!-- karni:example:{name} [^>]*-->\s*```python\n(.*?)```", text, re.S)
    assert match, f"docs/testing.md lost its karni:example:{name} block"
    return match.group(1)


@pytest.fixture(autouse=True)
def _crud_routes() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.testing.crud_urls",
        KARNI_API_ROUTER="tests.testing.crud_urls.get_router",
    ):
        yield


def run_example(name: str, case_name: str) -> unittest.TestResult:
    source = example_source(name)
    for project, ours in IMPORTS.items():
        source = source.replace(project, ours)
    namespace: dict[str, object] = {"__name__": f"docs_example_{name}"}
    exec(compile(source, str(DOCS), "exec"), namespace)
    case = namespace[case_name]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)  # type: ignore[arg-type]
    result = unittest.TestResult()
    suite.run(result)
    return result


def _problems(result: unittest.TestResult) -> str:
    return "\n".join(f"{test}: {trace}" for test, trace in (*result.failures, *result.errors))


def test_the_documented_example_is_short() -> None:
    lines = example_source().strip().splitlines()
    assert len(lines) < 20, f"the documented example grew to {len(lines)} lines"
    assert PROJECT_IMPORT in example_source()


def test_the_documented_example_passes() -> None:
    result = run_example("crud", "EventAPITests")
    assert result.testsRun == 3 and not _problems(result), _problems(result)


def test_the_documented_hidden_row_example_passes() -> None:
    result = run_example("hidden", "EventScopeTests")
    assert result.testsRun == 1 and not _problems(result), _problems(result)


def test_the_documented_admin_hidden_row_example_passes() -> None:
    from karni.accounts.roles import sync_roles

    with override_settings(KARNI_ROLES=ADMIN_ROLES):
        sync_roles()
        result = run_example("hidden-admin", "EventAdminScopeTests")
    assert result.testsRun == 1 and not _problems(result), _problems(result)
