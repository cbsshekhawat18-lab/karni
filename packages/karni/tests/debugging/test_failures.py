"""The failure catalogue (``karni explain -``): one test per pattern, on REAL failure text.

Every fixture in ``fixtures/`` is text a real failure printed. They were
captured by triggering each failure in a copy of examples/eventhub (sqlite,
``KARNI_CACHE=locmem``) with a deliberately slow ``events/serializers.py``,
then redacted (local paths became ``/home/dev/eventhub``):

=============================  ============================================================
fixture                        how it was produced
=============================  ============================================================
missing_driver                 ``DATABASE_URL=postgres://… manage.py check`` without psycopg
db_refused                     ``manage.py migrate`` against a port nothing listens on
db_compose_host                ``manage.py migrate`` with the compose host ``db`` from the host
cli_c012                       ``karni migrate`` without psycopg (the CLI's coded error)
no_such_table                  ``manage.py karni_seed`` before ``migrate``
no_such_column                 a GET after adding ``Event.subtitle`` without a migration
makemigrations_check           ``manage.py makemigrations --check --dry-run`` after that change
unapplied_migrations           ``manage.py runserver`` with the migration made, not applied
e104_owned_path                ``Owned("organiser")`` on EventViewSet, then ``manage.py check``
check_e101                     VenueViewSet without ``access``, then ``manage.py check``
e504_settings                  ``KARNI_STORAGE=s3 manage.py check`` (no bucket)
settings_not_configured        ``python -c "import events.models"``
karni_check_model_base         ``karni check`` with a model on ``models.Model``
pytest_e117                    a pytest listing 12 events through the slow serializer
pytest_e129                    ``pytest --pyargs karni.testing.performance``
assert_num_queries             ``self.assertNumQueries(4)`` around the listing
pytest_django_num_queries      ``django_assert_num_queries(4)`` around the listing
dev_budget_warning             the dev server's budget warning for the listing
dev_query_log                  the dev query log line for the listing
api_404 / api_403 / api_401    the dev server's log and body for those requests
csrf_token_missing             a session-mode POST without X-CSRFToken
csrf_origin                    a session-mode POST from an untrusted Origin
cors_blocked                   Chromium's console for a fetch with CORS closed
spectacular_warning            ``manage.py spectacular --validate --fail-on-warn``
disallowed_host                a request with ``Host: evil.example``
redis_refused                  ``KARNI_CACHE=redis`` with nothing at REDIS_URL
unknown_zero_division          a ZeroDivisionError in a SerializerMethodField
=============================  ============================================================

The live tests at the bottom trigger Karni's own failures in-process, so the
catalogue keeps matching the messages Karni prints today.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import override_settings
from rest_framework.test import APIClient

from karni.agent.rules import RULES
from karni.errorcodes import failures
from karni.errorcodes.failures import Diagnosis, diagnose

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[4]
ROOT = "/home/dev/eventhub"
RULE_DICTS = [rule.to_dict() for rule in RULES]


def _diagnose(name: str) -> Diagnosis:
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    return diagnose(text, root=ROOT, rules=RULE_DICTS)


def _first(name: str) -> failures.Finding:
    result = _diagnose(name)
    assert result.recognised, result.render()
    return result.findings[0]


#: fixture -> (the class or code of the first finding, strings its rendering must contain)
EXPECTED: dict[str, tuple[str, tuple[str, ...]]] = {
    "missing_driver": ("C012", ("psycopg", 'pip install "psycopg[binary]"')),
    "db_refused": ("C013", ('"127.0.0.1", port 5999', "karni serve -d")),
    "db_compose_host": ("C013", ("compose service name", "failed to resolve host 'db'")),
    "cli_c012": ("C012", ("psycopg",)),
    "no_such_table": ("migrations-not-applied", ("karni_accounts_user", "karni migrate")),
    "no_such_column": ("migration-missing", ("events_event.subtitle", "karni make migration")),
    "makemigrations_check": ("migration-missing", ("'events'", "karni make migration")),
    "unapplied_migrations": ("migrations-not-applied", ("1 migration(s) of events",)),
    "e104_owned_path": ("E104", ("Owned('organiser')", "Where: events/viewsets.py:26")),
    "check_e101": ("E101", ("VenueViewSet declares no `access`",)),
    "e504_settings": ("E504", ("AWS_STORAGE_BUCKET_NAME",)),
    "settings_not_configured": ("settings-not-configured", ("django.setup()",)),
    "karni_check_model_base": ("K101", ("[model-base]", "Where: events/models.py:109")),
    "pytest_e117": (
        "E117",
        (
            "12× events_venue from EventSerializer.venue_city",
            "Where: events/serializers.py:25 in get_venue_city",
            "Next:  karni queries EventViewSet.list --as <user>",
        ),
    ),
    "pytest_e129": (
        "E129",
        (
            "24× events_booking from TicketTierSerializer.remaining",
            "karni queries EventViewSet.list",
        ),
    ),
    "assert_num_queries": (
        "query-count",
        ("ran 9 queries, but the test expects 4", "5× events_venue"),
    ),
    "pytest_django_num_queries": ("query-count", ("ran 9 queries, but the test expects 4",)),
    "dev_budget_warning": (
        "E117",
        (
            "EventViewSet.list ran 28 queries against a budget of 8",
            "karni queries EventViewSet.list",
        ),
    ),
    "dev_query_log": (
        "query-log-duplicates",
        (
            "24 of them repeated statements",
            "Next:  karni queries /api/events/?page_size=50 --as <user>",
        ),
    ),
    "api_404": ("access-404", ("Owned('organizer')", "Next:  karni why /api/events/")),
    "api_403": ("access-403", ("--method PATCH", "readable")),
    "api_401_session": ("access-unauthenticated", ("/api/bookings/", "force_authenticate")),
    "csrf_token_missing": ("csrf", ("CSRF token missing", "X-CSRFToken")),
    "csrf_origin": ("csrf", ("http://localhost:3000", "KARNI_FRONTEND_URL")),
    "cors_blocked": ("cors", ("http://127.0.0.1:8918", "CORS_ALLOWED_ORIGINS")),
    "spectacular_warning": (
        "schema-method-type",
        ("get_organizer_email", "Where: events/serializers.py:16", "extend_schema_field"),
    ),
    "disallowed_host": ("disallowed-host", ("'evil.example'", "ALLOWED_HOSTS")),
    "redis_refused": ("redis-unreachable", ("127.0.0.1:6999", "KARNI_CACHE=locmem")),
}


def test_every_fixture_has_a_test() -> None:
    names = {path.stem for path in FIXTURES.glob("*.txt")}
    assert names == {*EXPECTED, "unknown_zero_division"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_real_failure_is_recognised(name: str) -> None:
    expected, fragments = EXPECTED[name]
    finding = _first(name)
    assert expected in (finding.code, finding.key), _diagnose(name).render()
    rendered = _diagnose(name).render()
    for fragment in fragments:
        assert fragment in rendered, f"{fragment!r} not in:\n{rendered}"
    assert finding.fix and finding.docs.startswith("https://")


def test_an_unknown_failure_is_said_plainly_never_guessed() -> None:
    result = _diagnose("unknown_zero_division")
    assert not result.recognised
    rendered = result.render()
    assert rendered.startswith(
        "Not a failure Karni recognises: ZeroDivisionError: division by zero"
    )
    assert "Where: events/serializers.py:33 in get_capacity_ratio" in rendered
    assert "will not guess" in rendered
    assert result.as_dict()["findings"] == []


def test_a_dev_log_beside_a_traceback_does_not_explain_it() -> None:
    """The dev server prints its query log next to the traceback: it is a side note."""
    text = "\n".join(
        (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
        for name in ("dev_query_log", "unknown_zero_division")
    )
    result = diagnose(text, root=ROOT, rules=RULE_DICTS)
    assert not result.recognised
    assert [finding.key for finding in result.also] == ["query-log-duplicates"]
    rendered = result.render()
    assert rendered.startswith("Not a failure Karni recognises: ZeroDivisionError")
    assert "\n\nAlso in the text:\n\nClass: Repeated queries in the dev query log" in rendered


def test_a_report_is_read_from_its_own_block() -> None:
    """A pasted run with several budget failures: each cause is read from its own report."""
    finding = _first("pytest_e117")
    assert finding.cause.count("events_venue") == 1


def test_specific_findings_come_before_summary_codes() -> None:
    codes = [finding.code for finding in _diagnose("karni_check_model_base").findings]
    assert codes == ["K101", "E702"]


def test_json_shape() -> None:
    data = _diagnose("pytest_e117").as_dict()
    assert data["recognised"] is True
    finding = data["findings"][0]
    assert finding["code"] == "E117"
    assert finding["next"] == "karni queries EventViewSet.list --as <user>"
    assert finding["where"] == "events/serializers.py:25 in get_venue_city"
    assert set(finding) == {
        *("class", "code", "title", "cause", "where", "fix", "next", "why", "docs"),
    }


def test_frames_are_classified() -> None:
    text = (FIXTURES / "e104_owned_path.txt").read_text(encoding="utf-8")
    frames = failures.parse_frames(text)
    kinds = {frame.kind for frame in frames}
    assert kinds == {"project", "karni", "library"}
    raised = failures.Text(text, Path(ROOT)).raised()
    assert raised is not None and raised.location(Path(ROOT)) == (
        "karni/api/access.py:909 in validate_access"
    )


def test_a_ruff_code_is_not_a_karni_code() -> None:
    assert not diagnose("events/models.py:1:89: E501 Line too long (103 > 88)").recognised


def test_patterns_are_an_escape_hatch() -> None:
    def custom(text: failures.Text, ctx: Any) -> list[failures.Finding]:
        if "PaymentGatewayDown" not in text.flat:
            return []
        return [failures.Finding("gateway", "Gateway down", "x", "retry", "https://x")]

    result = diagnose("PaymentGatewayDown: 503", patterns=(*failures.PATTERNS, custom))
    assert result.findings[0].key == "gateway"


def test_the_module_is_stdlib_only() -> None:
    """karni-cli loads it by path without Django: only stdlib and relative imports."""
    tree = ast.parse(Path(failures.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in sys.stdlib_module_names, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module is not None
            assert node.module.split(".")[0] in sys.stdlib_module_names | {"__future__"}


# live: Karni's own failures, triggered now


def _live(error: BaseException) -> Diagnosis:
    text = "".join(traceback.format_exception(error))
    return diagnose(text, rules=RULE_DICTS)


def test_live_owned_path_error() -> None:
    from karni.api import Access, BaseViewSet, Owned
    from tests.testapp.models import Event

    with pytest.raises(Exception) as info:

        class TypoViewSet(BaseViewSet):
            model = Event
            access = Access(read=Owned("organiser"), write=Owned("organiser"))
            auto_register = False

    finding = _live(info.value).findings[0]
    assert finding.code == "E104"
    assert "Owned('organiser')" in finding.cause


@pytest.mark.django_db
def test_live_query_budget() -> None:
    from karni.testing.factories import create
    from tests.testapp.models import Event

    for _ in range(3):
        create(Event)
    with (
        override_settings(KARNI_QUERY_BUDGET={"list": 1}, KARNI_QUERY_BUDGET_MODE="raise"),
        pytest.raises(AssertionError) as info,
    ):
        APIClient().get("/api/events/")
    finding = _live(info.value).findings[0]
    assert finding.code == "E117"
    assert finding.next == "karni queries EventViewSet.list --as <user>"


@pytest.mark.django_db
def test_live_missing_table() -> None:
    with pytest.raises(Exception) as info, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM events_nowhere")
    finding = _live(info.value).findings[0]
    assert finding.key == "migrations-not-applied"
    assert "events_nowhere" in finding.cause


@pytest.mark.django_db
def test_live_row_outside_the_read_scope() -> None:
    response = APIClient().get("/api/users/00000000-0000-0000-0000-000000000000/")
    assert response.status_code in (401, 403, 404)
    body = response.content.decode()
    path = "/api/users/00000000-0000-0000-0000-000000000000/"
    result = diagnose(f'"GET {path} HTTP/1.1" {response.status_code} 58\n{body}')
    assert result.findings[0].key.startswith("access-")
    assert result.findings[0].next.startswith("karni why /api/users/")


def test_live_disallowed_host() -> None:
    request = RequestFactory().get("/", HTTP_HOST="evil.example")
    with override_settings(ALLOWED_HOSTS=["testserver"]), pytest.raises(Exception) as info:
        request.get_host()
    assert _live(info.value).findings[0].key == "disallowed-host"


def test_every_class_has_a_docs_anchor() -> None:
    page = (REPO / "docs" / "debugging" / "explain.md").read_text(encoding="utf-8")
    for key in failures.CLASSES:
        assert f'<a id="{key}"></a>' in page, f"docs/debugging/explain.md has no anchor {key}"
    for name in EXPECTED:
        key = _first(name).key
        assert key in failures.CLASSES or key.startswith(("code-", "rule-")), key
