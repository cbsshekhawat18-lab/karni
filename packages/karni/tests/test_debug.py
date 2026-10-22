"""Request ids end to end, the development capture under ``.karni/``, trace, replay, failures.

Docs: docs/debugging/capture.md and docs/debugging/trace-and-replay.md.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import MiddlewareNotUsed
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from karni import tracing
from karni.audit.models import ChangeBatch, ChangeLog
from karni.debug import store, trace_event
from karni.debug.middleware import RECORD_VERSION, CaptureMiddleware
from karni.debug.store import capture_root as real_capture_root  # before conftest redirects it
from tests.testapp.models import Price

pytestmark = pytest.mark.django_db

RECORD_KEYS = {
    "version",
    "request_id",
    "at",
    "method",
    "path",
    "query",
    "headers",
    "body",
    "content_type",
    "user",
    "view",
    "resource",
    "action",
    "view_kwargs",
    "status",
    "duration_ms",
    "error_code",
    "failure_id",
}


@pytest.fixture(autouse=True)
def _eager_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tasks run inline (no broker); retries re-run inline too."""
    from celery import current_app

    monkeypatch.setattr(current_app.conf, "task_always_eager", True)


@pytest.fixture
def karni_dir(tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Capture on (DEBUG) into a temporary directory, with the debug URLconf.

    The project root stays packages/karni (the tests are the "project" code
    whose frames carry locals); only the capture directory moves.
    """
    monkeypatch.setattr(store, "capture_root", lambda: tmp_path / ".karni")
    settings.DEBUG = True
    settings.ROOT_URLCONF = "tests.debug_urls"
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]
    return tmp_path / ".karni"


@pytest.fixture
def user() -> Any:
    return get_user_model().objects.create_user(email="ada@example.com", password="pw-unused-1")


def _client(user: Any = None) -> APIClient:
    client = APIClient(raise_request_exception=False)
    if user is not None:
        client.force_authenticate(user)
    return client


def _events(request_id: str) -> list[dict[str, Any]]:
    return list(store.iter_events({request_id}))


# --- request ids --------------------------------------------------------------


def test_every_response_carries_a_request_id(settings: Any) -> None:
    settings.ROOT_URLCONF = "tests.debug_urls"
    response = _client().get("/debug/staff/")
    assert tracing.is_valid_request_id(response["X-Request-ID"])


@pytest.mark.parametrize(
    ("debug", "trust", "proxies", "accepted"),
    [
        (True, False, 1, True),  # development: the client's id is used
        (False, False, 1, False),  # production: never by default
        (False, True, 1, True),  # the proxy overwrites the header
        (False, True, 0, False),  # no proxy in front: every header is the client's
    ],
)
def test_an_incoming_request_id_is_accepted_only_when_trusted(
    settings: Any, debug: bool, trust: bool, proxies: int, accepted: bool
) -> None:
    settings.ROOT_URLCONF = "tests.debug_urls"
    settings.DEBUG = debug
    settings.KARNI_REQUEST_ID_TRUST_HEADER = trust
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": proxies}
    settings.ALLOWED_HOSTS = ["testserver"]
    response = _client().get("/debug/staff/", HTTP_X_REQUEST_ID="client-chosen-id")
    assert (response["X-Request-ID"] == "client-chosen-id") is accepted


def test_an_unsafe_incoming_id_is_replaced_even_in_development(karni_dir: Path) -> None:
    response = _client().get("/debug/staff/", HTTP_X_REQUEST_ID="../../etc/passwd")
    assert response["X-Request-ID"] != "../../etc/passwd"
    assert tracing.is_valid_request_id(response["X-Request-ID"])
    assert not (karni_dir.parent.parent / "etc").exists()


def test_tasks_and_their_retries_keep_the_request_id(karni_dir: Path, user: Any) -> None:
    response = _client(user).post(
        "/debug/prices/", {"mail_to": "ada@example.com", "fail_times": 2}, format="json"
    )
    assert response.status_code == 201
    rid = response["X-Request-ID"]
    names = [event["event"] for event in _events(rid)]
    assert names.count("task.started") == 3  # the first run and two retries
    assert names.count("task.retried") == 2
    assert "task.succeeded" in names and "email.sent" in names
    assert names[0] == "request.start" and "request.end" in names
    # The email carries the id in a header.
    [message] = mail.outbox
    assert message.extra_headers[tracing.EMAIL_HEADER] == rid


def test_the_publish_header_restores_the_id_in_the_worker() -> None:
    """A worker sees the id through the message header, not the publisher's context."""
    headers: dict[str, Any] = {}
    with tracing.bound_request_id("req-abc"):
        tracing._before_task_publish(headers=headers)
    assert headers[tracing.CELERY_HEADER] == "req-abc"

    class Request:
        karni_request_id = "req-abc"
        retries = 1
        is_eager = False

    class Task:
        name = "shop.tasks.sync"
        request = Request()

    assert tracing.get_request_id() is None
    tracing._task_prerun(task_id="t-1", task=Task())
    assert tracing.get_request_id() == "req-abc"
    # A retry is published from inside the task, so it carries the same id.
    retry_headers: dict[str, Any] = {}
    tracing._before_task_publish(headers=retry_headers)
    assert retry_headers[tracing.CELERY_HEADER] == "req-abc"
    tracing._task_postrun(task_id="t-1")
    assert tracing.get_request_id() is None


def test_a_task_without_an_id_gets_its_own() -> None:
    class Task:
        name = "shop.tasks.nightly"
        request = None

    tracing._task_prerun(task_id="t-2", task=Task())
    try:
        assert tracing.is_valid_request_id(tracing.get_request_id())
    finally:
        tracing._task_postrun(task_id="t-2")


def test_email_outside_a_request_has_no_header() -> None:
    mail.send_mail("Hi", "Body", None, ["x@example.com"])
    assert tracing.EMAIL_HEADER not in mail.outbox[0].extra_headers
    with tracing.bound_request_id("cmd-1"):
        mail.send_mail("Hi", "Body", None, ["x@example.com"])
    assert mail.outbox[1].extra_headers[tracing.EMAIL_HEADER] == "cmd-1"


def test_outgoing_headers() -> None:
    assert tracing.outgoing_headers() == {}
    with tracing.bound_request_id("out-1"):
        assert tracing.outgoing_headers() == {"X-Request-ID": "out-1"}


def test_change_log_and_batches_record_the_request_id(karni_dir: Path, user: Any) -> None:
    response = _client(user).post("/debug/prices/", {"amount": "2.00"}, format="json")
    rid = response["X-Request-ID"]
    entry = ChangeLog.objects.get(request_id=rid)
    assert entry.action == "create"
    from karni.audit.capture import change_batch

    with tracing.bound_request_id("import-1"), change_batch("import", "prices.csv"):
        Price.objects.create(amount="3.00")
    assert ChangeBatch.objects.get(request_id="import-1").kind == "import"
    assert ChangeLog.objects.filter(request_id="import-1").count() == 1
    assert [event["event"] for event in _events("import-1")] == ["audit.batch"]


# --- capture is inert without DEBUG -------------------------------------------


def test_capture_is_inert_when_debug_is_off(
    tmp_path: Path, settings: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "capture_root", lambda: tmp_path / ".karni")
    settings.DEBUG = False
    settings.ROOT_URLCONF = "tests.debug_urls"
    with pytest.raises(MiddlewareNotUsed):
        CaptureMiddleware(lambda request: None)
    client = _client(user)
    client.post("/debug/prices/", {"mail_to": "a@example.com", "explode": True}, format="json")
    client.get("/debug/crash/")
    with tracing.bound_request_id("x-1"):
        trace_event("webhook.sent", url="https://example.com")
    assert not (tmp_path / ".karni").exists()


def test_the_capture_directory_is_under_the_project_root(settings: Any, tmp_path: Path) -> None:
    settings.BASE_DIR = tmp_path
    assert real_capture_root() == tmp_path.resolve() / ".karni"


def test_capture_can_be_switched_off_in_development(karni_dir: Path, settings: Any) -> None:
    settings.KARNI_DEBUG_CAPTURE = False
    _client().get("/debug/crash/")
    assert not karni_dir.exists()


# --- the request record --------------------------------------------------------


def test_the_request_record_follows_the_contract(karni_dir: Path, user: Any) -> None:
    response = _client(user).post(
        "/api/venues/?ordering=name", {"name": "Hall", "city": "Pune"}, format="json"
    )
    assert response.status_code == 201
    rid = response["X-Request-ID"]
    record = json.loads((karni_dir / "requests" / f"{rid}.json").read_text())
    assert set(record) == RECORD_KEYS
    assert record["version"] == RECORD_VERSION
    assert record["method"] == "POST" and record["path"] == "/api/venues/"
    assert record["query"] == {"ordering": ["name"]}
    assert record["body"] == {"name": "Hall", "city": "Pune"}
    assert record["content_type"] == "application/json"
    assert record["user"] == {
        "id": str(user.pk),
        "email": "ada@example.com",
        "username": None,
        "is_staff": False,
        "is_superuser": False,
    }
    assert record["view"] == "tests.testapp.viewsets.VenueViewSet"
    assert record["resource"] and record["action"] == "create"
    assert record["status"] == 201 and record["error_code"] is None
    assert record["failure_id"] is None and isinstance(record["duration_ms"], float)
    assert (karni_dir / "requests" / ".gitignore").read_text().strip().endswith("*")
    # Headers as the client sent them: not the X-Request-ID Karni assigned.
    assert "X-Request-Id" not in record["headers"]
    sent = _client().get("/debug/staff/", HTTP_X_REQUEST_ID="mine-1")
    assert sent["X-Request-ID"] == "mine-1"
    assert store.read_request("mine-1")["headers"]["X-Request-Id"] == "mine-1"  # type: ignore[index]


def test_error_codes_on_the_record(karni_dir: Path, user: Any) -> None:
    denied = _client(user).get("/debug/staff/")
    record = store.read_request(denied["X-Request-ID"])
    assert record is not None and record["status"] == 403
    assert record["error_code"] == "permission_denied"
    # A Karni-coded API error wins over DRF's generic "invalid".
    bad_expand = _client().get("/api/venues/?expand=nope")
    found = store.read_request(bad_expand["X-Request-ID"])
    assert found is not None and found["status"] == 400
    assert found["error_code"] == "E126"
    ok = store.read_request(_client().get("/api/venues/")["X-Request-ID"])
    assert ok is not None and ok["error_code"] is None


def test_records_and_failures_are_bounded(karni_dir: Path, settings: Any) -> None:
    settings.KARNI_DEBUG_CAPTURE_KEEP = 3
    for _ in range(5):
        _client().get("/debug/crash/")
    assert len(list((karni_dir / "requests").glob("*.json"))) == 3
    assert len(list((karni_dir / "failures").glob("*.json"))) == 3


def test_old_trace_files_are_pruned(karni_dir: Path) -> None:
    (karni_dir / "trace").mkdir(parents=True)
    old = karni_dir / "trace" / "2000-01-01.jsonl"
    old.write_text("{}\n")
    store._pruned_trace_on = None
    with tracing.bound_request_id("p-1"):
        trace_event("webhook.sent", url="https://example.com")
    assert not old.exists()


# --- failures -----------------------------------------------------------------


def test_an_unhandled_exception_writes_a_failure_snapshot(karni_dir: Path, user: Any) -> None:
    response = _client(user).post(
        "/debug/prices/", {"explode": True, "password": "pw-in-body-1"}, format="json"
    )
    assert response.status_code == 500
    record = store.read_request(response["X-Request-ID"])
    assert record is not None and record["failure_id"]
    snapshot = store.read_failure(record["failure_id"])
    assert snapshot is not None
    assert snapshot["kind"] == "request" and snapshot["request_id"] == record["request_id"]
    assert snapshot["exception"]["type"] == "RuntimeError"
    origin = snapshot["frames"][snapshot["origin"]]
    assert origin["file"].endswith("debug_urls.py") and origin["kind"] == "project"
    assert origin["function"] == "PriceView.post"
    assert origin["locals"]["password"] == "[redacted]"
    assert origin["locals"]["price"]["__model__"] == "testapp.Price"
    assert origin["locals"]["price"]["note"] == "[redacted]"
    assert all("locals" not in frame for frame in snapshot["frames"] if frame["kind"] == "library")
    assert snapshot["view"]["view"] == "tests.debug_urls.PriceView"
    assert snapshot["user"]["roles"] == [] and snapshot["user"]["email"] == "ada@example.com"
    assert snapshot["queries"]["count"] >= 1
    assert snapshot["settings"]["DEBUG"] is True
    assert "PASSWORD" not in json.dumps(snapshot["settings"]["DATABASES"])
    assert "tests.testapp" in snapshot["settings"]["INSTALLED_APPS"]
    assert snapshot["settings"]["KARNI"]["KARNI_DEBUG_CAPTURE"] is True


def test_a_task_failure_writes_a_snapshot(karni_dir: Path) -> None:
    from tests.testapp.tasks import broken_task

    with tracing.bound_request_id("task-run-1"):
        broken_task.apply(args=["tok-secret-value-9"])
    [failed] = [event for event in _events("task-run-1") if event["event"] == "task.failed"]
    snapshot = store.read_failure(failed["failure_id"])
    assert snapshot is not None and snapshot["kind"] == "task"
    assert snapshot["task"]["name"] == "tests.testapp.tasks.broken_task"
    assert snapshot["task"]["arguments"] == {"token": "[redacted]"}
    assert snapshot["exception"]["message"] == "cannot process the order"
    assert "tok-secret-value-9" not in json.dumps(snapshot)


def test_failure_brief(karni_dir: Path, user: Any) -> None:
    response = _client(user).post("/debug/prices/", {"explode": True}, format="json")
    out = io.StringIO()
    call_command("karni_failure", "last", stdout=out)
    brief = out.getvalue()
    assert "RuntimeError" in brief
    assert "Where: tests/debug_urls.py" in brief or "debug_urls.py:" in brief
    assert f"karni replay {response['X-Request-ID']} --as ada@example.com" in brief
    assert "Next steps:" in brief
    by_request = io.StringIO()
    call_command("karni_failure", response["X-Request-ID"], "--json", stdout=by_request)
    assert json.loads(by_request.getvalue())["request_id"] == response["X-Request-ID"]
    with pytest.raises(CommandError, match="E922"):
        call_command("karni_failure", "0000deadbeef")


# --- the secret scan -------------------------------------------------------------


def test_no_secret_reaches_the_capture_directory(karni_dir: Path, user: Any, settings: Any) -> None:
    """Passwords, tokens, Authorization, cookies, SECRET_KEY, Karni.sensitive: never written."""
    from rest_framework_simplejwt.tokens import RefreshToken

    access = str(RefreshToken.for_user(user).access_token)
    secrets = {
        "password in a JSON body": "hunter2-json-body",
        "password in a form body": "hunter2-form-body",
        "password in a multipart body": "hunter2-multipart",
        "token in the query": "query-token-4321",
        "Karni.sensitive field": "sensitive-note-789",
        "pattern-named field": "api-token-value-555",
        "bearer token": access,
        "session cookie": "cookie-session-value-1",
        "csrf token": "csrf-header-value-77",
        "SECRET_KEY": settings.SECRET_KEY,
    }
    client = APIClient(raise_request_exception=False)
    client.cookies["sessionid"] = secrets["session cookie"]
    auth = {
        "HTTP_AUTHORIZATION": f"Bearer {access}",
        "HTTP_X_CSRFTOKEN": secrets["csrf token"],
    }
    # A JSON body that crashes with every secret in its locals and message.
    crashed = client.post(
        f"/debug/prices/?token={secrets['token in the query']}",
        {
            "explode": True,
            "password": secrets["password in a JSON body"],
            "note": secrets["Karni.sensitive field"],
            "api_token": secrets["pattern-named field"],
            "nested": {"refresh_token": "nested-refresh-1"},
        },
        format="json",
        **auth,
    )
    assert crashed.status_code == 500
    # A form body and a multipart body that crash too.
    client.post(
        "/debug/prices/",
        f"explode=1&password={secrets['password in a form body']}",
        content_type="application/x-www-form-urlencoded",
        **auth,
    )
    client.post(
        "/debug/prices/",
        {"explode": "1", "password": secrets["password in a multipart body"]},
        format="multipart",
        **auth,
    )
    # A successful request and a plain-view crash with the same credentials.
    client.post("/debug/prices/", {"note": secrets["Karni.sensitive field"]}, format="json", **auth)
    client.get(f"/debug/crash/?token={secrets['token in the query']}", **auth)

    files = [path for path in karni_dir.rglob("*") if path.is_file()]
    assert any(path.parent.name == "failures" for path in files)
    leaks = [
        f"{label} in {path.relative_to(karni_dir)}"
        for path in files
        for label, secret in {**secrets, "nested": "nested-refresh-1"}.items()
        if secret.encode() in path.read_bytes()
    ]
    assert not leaks, leaks
    # ...and the redaction is visible, not silent.
    record = store.read_request(crashed["X-Request-ID"])
    assert record is not None
    assert record["headers"]["Authorization"] == "Bearer [redacted]"
    assert record["headers"]["Cookie"] == "sessionid=[redacted]"
    assert record["query"] == {"token": ["[redacted]"]}
    assert record["body"]["password"] == "[redacted]" and record["body"]["note"] == "[redacted]"
    assert record["body"]["nested"] == {"refresh_token": "[redacted]"}


def test_the_redactor_rules(settings: Any) -> None:
    from karni.debug.redact import Redactor

    redactor = Redactor()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxfQ.c2lnbmF0dXJlLXZhbHVl"
    assert redactor.value({"access": jwt, "user": {"id": 1}}) == {
        "access": "[redacted]",
        "user": {"id": 1},
    }
    assert redactor.scrub(f"key={settings.SECRET_KEY};") == "key=[redacted];"
    assert redactor.value({"api_key": "k", "city": "c"}) == {"api_key": "[redacted]", "city": "c"}
    # Price.Karni.sensitive, matched like the name patterns: case-insensitively.
    assert redactor.value({"note": "n", "Note": "n"}) == {
        "note": "[redacted]",
        "Note": "[redacted]",
    }
    redactor.collect({"login": {"password": "pw-123456"}})
    assert redactor.scrub("failed for pw-123456!") == "failed for [redacted]!"
    assert redactor.headers({"Authorization": "Token abc", "Cookie": "a=1; b=2"}) == {
        "Authorization": "Token [redacted]",
        "Cookie": "a=[redacted]; b=[redacted]",
    }
    settings.KARNI_AUDIT_REDACT = ["pin"]
    assert Redactor().value({"pin": "1", "password": "x"}) == {"pin": "[redacted]", "password": "x"}


# --- karni_trace -----------------------------------------------------------------


def test_trace_tells_the_story_in_order(karni_dir: Path, user: Any) -> None:
    response = _client(user).post(
        "/debug/prices/", {"mail_to": "ada@example.com", "fail_times": 1}, format="json"
    )
    rid = response["X-Request-ID"]
    out = io.StringIO()
    call_command("karni_trace", rid, stdout=out)
    text = out.getvalue()
    assert text.startswith(f"Request {rid}: POST /debug/prices/ -> 201")
    order = [
        "request.start",
        "audit.change",
        "task.started",
        "task.retried",
        "email.sent",
        "task.succeeded",
        "request.end",
    ]
    positions = [text.index(name) for name in order]
    assert positions == sorted(positions), text
    as_json = io.StringIO()
    call_command("karni_trace", "last", "--json", stdout=as_json)
    story = json.loads(as_json.getvalue())
    assert story["request_id"] == rid
    assert {event["source"] for event in story["events"]} == {"trace", "database"}


def test_trace_links_requests_through_shared_refs(karni_dir: Path) -> None:
    with tracing.bound_request_id("checkout-1"):
        trace_event("payment.checkout", refs=["shop.Payment:7"])
    with tracing.bound_request_id("webhook-1"):
        trace_event("webhook.received", provider="test", refs=["shop.Payment:7"])
    out = io.StringIO()
    call_command("karni_trace", "webhook-1", "--json", stdout=out)
    linked = json.loads(out.getvalue())["linked"]
    assert [entry["request_id"] for entry in linked] == ["checkout-1"]


def test_trace_without_a_capture_says_how_to_enable_it(karni_dir: Path) -> None:
    with pytest.raises(CommandError, match="E921.*DEBUG on"):
        call_command("karni_trace", "never-seen")
    with pytest.raises(CommandError, match="E921.*not a request id"):
        call_command("karni_trace", "../secrets")


# --- karni_replay ------------------------------------------------------------------


def test_replay_as_another_user_reports_the_change(karni_dir: Path, user: Any) -> None:
    denied = _client(user).get("/debug/staff/")
    assert denied.status_code == 403
    get_user_model().objects.create_user(
        email="root@example.com", password="pw-unused-2", is_staff=True
    )
    out = io.StringIO()
    call_command("karni_replay", denied["X-Request-ID"], "--as", "root@example.com", stdout=out)
    text = out.getvalue()
    assert "as root@example.com (rolled back)" in text and "was 403, now 200" in text
    same = io.StringIO()
    call_command("karni_replay", denied["X-Request-ID"], "--json", stdout=same)
    result = json.loads(same.getvalue())
    assert result["change"] == "same as captured (403)" and result["new_request_id"]
    replayed = store.read_request(result["new_request_id"])
    assert replayed is not None and replayed["status"] == 403


def test_replay_rolls_writes_back_unless_committed(karni_dir: Path, user: Any) -> None:
    created = _client(user).post(
        "/debug/prices/", {"amount": "4.00", "mail_to": "ada@example.com"}, format="json"
    )
    before = Price.objects.count()
    mail.outbox.clear()
    out = io.StringIO()
    call_command("karni_replay", created["X-Request-ID"], stdout=out)
    assert "same as captured (201)" in out.getvalue()
    assert "email (not sent): to ada@example.com" in out.getvalue()
    assert Price.objects.count() == before
    assert mail.outbox == []
    call_command("karni_replay", created["X-Request-ID"], "--commit", stdout=io.StringIO())
    assert Price.objects.count() == before + 1


def test_replay_refuses_redacted_values_until_supplied(karni_dir: Path, user: Any) -> None:
    response = _client(user).post(
        "/debug/prices/?token=abc-query-1", {"password": "x-secret-1"}, format="json"
    )
    rid = response["X-Request-ID"]
    with pytest.raises(CommandError, match=r"E923.*password, query:token.*--set password="):
        call_command("karni_replay", rid)
    out = io.StringIO()
    call_command("karni_replay", rid, "--set", "password=new", "--set", "query:token=t", stdout=out)
    assert "same as captured (201)" in out.getvalue()
    dropped = io.StringIO()
    call_command("karni_replay", rid, "--drop-redacted", stdout=dropped)
    assert "left out (redacted): password, query:token" in dropped.getvalue()


def test_replay_refuses_without_debug(karni_dir: Path, user: Any, settings: Any) -> None:
    response = _client(user).get("/debug/staff/")
    settings.DEBUG = False
    with pytest.raises(CommandError, match="E920"):
        call_command("karni_replay", response["X-Request-ID"])


def test_replay_unknown_user(karni_dir: Path, user: Any) -> None:
    response = _client(user).get("/debug/staff/")
    with pytest.raises(CommandError, match="E924"):
        call_command("karni_replay", response["X-Request-ID"], "--as", "nobody@example.com")


# --- the system check ------------------------------------------------------------------


def test_w920_flags_the_request_id_middleware_after_structlog(settings: Any) -> None:
    from karni.checks import check_request_id_middleware

    assert check_request_id_middleware() == []
    settings.MIDDLEWARE = [
        "django_structlog.middlewares.RequestMiddleware",
        "karni.tracing.RequestIdMiddleware",
    ]
    [warning] = check_request_id_middleware()
    assert warning.id == "karni.W920"
    settings.MIDDLEWARE = ["django_structlog.middlewares.RequestMiddleware"]
    assert check_request_id_middleware() == []
