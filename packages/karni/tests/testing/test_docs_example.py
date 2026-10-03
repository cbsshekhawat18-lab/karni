"""The 15-line example in docs/testing.md is real code: it is extracted and run here.

The block after ``<!-- karni:example:crud`` is executed with its project import
(``events.viewsets``) pointed at the suite's equivalent resource, so the
documented test file cannot rot.
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
SUITE_IMPORT = "from tests.testing.crud_urls import EventViewSet"

pytestmark = pytest.mark.django_db


def example_source() -> str:
    text = DOCS.read_text()
    match = re.search(r"<!-- karni:example:crud[^>]*-->\s*```python\n(.*?)```", text, re.S)
    assert match, "docs/testing.md lost its karni:example:crud block"
    return match.group(1)


@pytest.fixture(autouse=True)
def _crud_routes() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.testing.crud_urls",
        KARNI_API_ROUTER="tests.testing.crud_urls.get_router",
    ):
        yield


def test_the_documented_example_is_short() -> None:
    lines = example_source().strip().splitlines()
    assert len(lines) < 20, f"the documented example grew to {len(lines)} lines"
    assert PROJECT_IMPORT in example_source()


def test_the_documented_example_passes() -> None:
    namespace: dict[str, object] = {"__name__": "docs_example"}
    exec(
        compile(example_source().replace(PROJECT_IMPORT, SUITE_IMPORT), str(DOCS), "exec"),
        namespace,
    )
    case = namespace["EventAPITests"]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)  # type: ignore[arg-type]
    result = unittest.TestResult()
    suite.run(result)
    problems = [f"{test}: {trace}" for test, trace in (*result.failures, *result.errors)]
    assert result.testsRun == 3 and not problems, "\n".join(problems)
