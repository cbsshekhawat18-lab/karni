"""Terms acceptance (karni.accounts.terms, experimental): the routes, the record and the gate.

Every test runs against a URLconf built for it: ``karni.accounts.urls``
builds its list once, at import, and the gate is only in the middleware chain
of a handler loaded while ``KARNI_TERMS`` requires acceptance (each test
client loads its own on the first request).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import Client, RequestFactory
from django.urls import include, path
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.views import SpectacularAPIView
from pytest_django import DjangoAssertNumQueries, Settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from karni.accounts import terms
from karni.accounts.matrix import DEFAULT_MATRIX_EXCLUDE
from karni.accounts.models import TermsAcceptance
from karni.accounts.terms import PermanentRecordError, TermsGateMiddleware
from karni.accounts.urls import build_urlpatterns
from karni.checks import check_terms_middleware
from karni.conf.validation import validate_settings
from karni.errorcodes import get as get_code

pytestmark = pytest.mark.django_db

VERSION = "2026-11"
TERMS: dict[str, Any] = {"version": VERSION, "url": "/terms/", "required": True}
STATUS = "/api/auth/terms/"
ACCEPT = "/api/auth/terms/accept/"
ME = "/api/auth/me/"
PLAIN = "/api/plain/"
VENUES = "/api/venues/"
PASSWORD = "terms-pass-123!x"


class PlainView(APIView):
    """A plain DRF view under /api/ for signed-in users."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


class OpenView(APIView):
    """A plain DRF view under /api/ anyone may call."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"ok": True})


def django_view(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"ok": True})


def _urlconf() -> ModuleType:
    """A URLconf built now, with the accounts routes for the current settings."""
    from django.contrib import admin

    module = ModuleType("terms_urls")
    module.__dict__["urlpatterns"] = [
        path("admin/", admin.site.urls),
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/auth/", include(build_urlpatterns())),
        path("api/plain/", PlainView.as_view()),
        path("api/open/", OpenView.as_view()),
        path("api/django/", django_view),
        path("api/", include("karni.api.urls")),
        path("outside/", PlainView.as_view()),
    ]
    return module


def remount(settings: Settings) -> None:
    settings.ROOT_URLCONF = _urlconf()


@pytest.fixture(autouse=True)
def _terms(settings: Settings) -> Iterator[None]:
    cache.clear()
    settings.KARNI_AUTH_MODE = "jwt"
    settings.KARNI_TERMS = dict(TERMS)
    remount(settings)
    yield
    cache.clear()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def users() -> Any:
    return get_user_model().objects


def make_user(email: str = "ada@example.com", **extra: Any) -> Any:
    return users().create_user(email=email, password=PASSWORD, **extra)


def signed_in(user: Any) -> APIClient:
    """A client carrying the user's access token, as a mobile app sends it."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def session_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


def assert_gated(response: Any, version: str = VERSION) -> dict[str, Any]:
    assert response.status_code == 403, response.content
    body: dict[str, Any] = response.json()
    assert body["code"] == "E245"
    assert body["detail"].startswith("E245: ")
    assert body["version"] == version
    assert body["url"] == "/terms/"
    assert response["Cache-Control"] == "no-store"
    assert get_code("E245") is not None  # karni explain knows it
    return body


def accept(api: APIClient, version: str = VERSION, **body: Any) -> Any:
    return api.post(ACCEPT, {"version": version, **body}, format="json")


# settings


def _validate(settings: Settings, value: Any) -> None:
    from django.conf import settings as django_settings

    settings.KARNI_TERMS = value
    validate_settings(django_settings)


def test_validation_accepts_the_documented_shapes(settings: Settings) -> None:
    _validate(settings, None)
    _validate(settings, dict(TERMS))
    _validate(
        settings,
        {
            "version": "v3",
            "url": "https://example.com/terms/",
            "required": False,
            "paths": ["/api/", "/admin/"],
            "exempt": ["/api/public/"],
        },
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("2026-11", "must be a dict like"),
        ({}, "must be a dict like"),
        ({"url": "/terms/"}, "KARNI_TERMS['version'] = None must be a non-empty string"),
        ({"version": "  ", "url": "/terms/"}, "must be a non-empty string"),
        ({"version": "v" * 101, "url": "/terms/"}, "at most 100 are stored"),
        ({"version": "v1"}, "KARNI_TERMS['url'] = None must be a string"),
        ({"version": "v1", "url": 3}, "KARNI_TERMS['url'] = 3 must be a string"),
        ({"version": "v1", "url": "/t/", "required": "yes"}, "must be True or False"),
        ({"version": "v1", "url": "/t/", "paths": "/api/"}, "KARNI_TERMS['paths']"),
        ({"version": "v1", "url": "/t/", "paths": ["api/"]}, "start with '/'"),
        ({"version": "v1", "url": "/t/", "exempt": [3]}, "KARNI_TERMS['exempt']"),
        ({"version": "v1", "url": "/t/", "exempts": []}, "unknown keys ['exempts']"),
    ],
)
def test_validation_refuses_a_bad_value(settings: Settings, value: Any, message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="E504") as raised:
        _validate(settings, value)
    assert message in str(raised.value)


def test_the_gate_leaves_the_chain_unless_acceptance_is_required(settings: Settings) -> None:
    def respond(request: HttpRequest) -> HttpResponse:
        return HttpResponse()

    assert TermsGateMiddleware(respond).get_response is respond
    settings.KARNI_TERMS = {**TERMS, "required": False}
    with pytest.raises(MiddlewareNotUsed):
        TermsGateMiddleware(respond)
    settings.KARNI_TERMS = None
    with pytest.raises(MiddlewareNotUsed):
        TermsGateMiddleware(respond)


def test_karni_settings_lists_the_gate_after_authentication() -> None:
    from django.conf import settings as django_settings

    middleware = list(django_settings.MIDDLEWARE)
    assert middleware.index("karni.accounts.terms.TermsGateMiddleware") > middleware.index(
        "django.contrib.auth.middleware.AuthenticationMiddleware"
    )
    assert check_terms_middleware() == []


class ProjectGate(TermsGateMiddleware):
    """A project's own gate."""


def test_e248_reports_a_missing_or_misplaced_gate(settings: Settings) -> None:
    gate = "karni.accounts.terms.TermsGateMiddleware"
    auth = "django.contrib.auth.middleware.AuthenticationMiddleware"
    full = list(settings.MIDDLEWARE)
    settings.MIDDLEWARE = [entry for entry in full if entry != gate]
    [missing] = check_terms_middleware()
    assert missing.id == "karni.E248" and "no TermsGateMiddleware" in missing.msg
    settings.MIDDLEWARE = [gate, *(entry for entry in full if entry != gate)]
    [early] = check_terms_middleware()
    assert early.id == "karni.E248" and f"comes before {auth}" in early.msg
    settings.MIDDLEWARE = [f"{__name__}.ProjectGate" if entry == gate else entry for entry in full]
    assert check_terms_middleware() == []
    settings.MIDDLEWARE = [entry for entry in full if entry != gate]
    settings.KARNI_TERMS = {**TERMS, "required": False}
    assert check_terms_middleware() == []
    assert get_code("E248") is not None


# routes


def test_the_routes_exist_only_while_the_setting_is_set(settings: Settings) -> None:
    names = {p.name for p in build_urlpatterns() if getattr(p, "name", None)}
    assert {"karni-accounts-terms", "karni-accounts-terms-accept"} <= names
    settings.KARNI_TERMS = None
    names = {p.name for p in build_urlpatterns() if getattr(p, "name", None)}
    assert not names & {"karni-accounts-terms", "karni-accounts-terms-accept"}
    remount(settings)
    user = make_user()
    assert signed_in(user).get(STATUS).status_code == 404


def test_a_urlconf_built_while_set_answers_e249_once_unset(settings: Settings) -> None:
    client = signed_in(make_user())
    settings.KARNI_TERMS = None
    for response in (client.get(STATUS), accept(client)):
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "E249" and body["detail"].startswith("E249: ")
        assert "version" not in body
    assert get_code("E249") is not None
    assert TermsAcceptance.objects.count() == 0


def test_the_routes_need_a_signed_in_user(client: APIClient) -> None:
    assert client.get(STATUS).status_code == 401
    assert accept(client).status_code == 401


# terms/ and terms/accept/


def test_the_status_before_and_after_accepting() -> None:
    client = signed_in(make_user())
    before = client.get(STATUS)
    assert before.status_code == 200
    assert before.json() == {
        "version": VERSION,
        "url": "/terms/",
        "required": True,
        "accepted": False,
        "accepted_at": None,
    }
    accepted = accept(client)
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["accepted"] is True and body["accepted_at"]
    assert client.get(STATUS).json() == body


def test_accept_stores_the_ip_the_user_agent_and_the_client() -> None:
    user = make_user()
    device = {"platform": "ios", "app_version": "2.4.0", "device": "iPhone15,2"}
    response = signed_in(user).post(
        ACCEPT,
        {"version": VERSION, "client": device},
        format="json",
        REMOTE_ADDR="203.0.113.9",
        HTTP_USER_AGENT="ExampleApp/2.4.0 (iOS 18.1)",
    )
    assert response.status_code == 201, response.content
    row = TermsAcceptance.objects.get(user=user)
    assert row.version == VERSION
    assert row.ip == "203.0.113.9"
    assert row.user_agent == "ExampleApp/2.4.0 (iOS 18.1)"
    assert row.client == device
    assert row.accepted_at is not None


def test_the_ip_honours_num_proxies(settings: Settings) -> None:
    forwarded = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "198.51.100.1, 203.0.113.7"}
    first = make_user("one@example.com")
    signed_in(first).post(ACCEPT, {"version": VERSION}, format="json", **forwarded)
    # One proxy in front (Karni's default): the address that proxy saw.
    assert TermsAcceptance.objects.get(user=first).ip == "203.0.113.7"

    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    second = make_user("two@example.com")
    signed_in(second).post(ACCEPT, {"version": VERSION}, format="json", **forwarded)
    assert TermsAcceptance.objects.get(user=second).ip == "10.0.0.1"


def test_an_address_that_is_not_an_ip_falls_back_to_remote_addr() -> None:
    user = make_user()
    signed_in(user).post(
        ACCEPT,
        {"version": VERSION},
        format="json",
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR="not-an-address",
    )
    assert TermsAcceptance.objects.get(user=user).ip == "10.0.0.1"


def test_a_long_user_agent_is_cut() -> None:
    user = make_user()
    signed_in(user).post(ACCEPT, {"version": VERSION}, format="json", HTTP_USER_AGENT="x" * 5000)
    assert len(TermsAcceptance.objects.get(user=user).user_agent) == terms.USER_AGENT_MAX_LENGTH


def test_accepting_the_same_version_again_changes_nothing() -> None:
    user = make_user()
    client = signed_in(user)
    first = accept(client)
    again = accept(client, client={"platform": "web"})
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert TermsAcceptance.objects.filter(user=user).count() == 1
    assert TermsAcceptance.objects.get(user=user).client is None


def test_accept_refuses_another_version() -> None:
    user = make_user()
    response = accept(signed_in(user), "2025-01")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "E246" and body["detail"].startswith("E246: ")
    assert body["version"] == VERSION and body["url"] == "/terms/"
    assert "'2025-01'" in body["detail"]
    assert get_code("E246") is not None
    assert not TermsAcceptance.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    ("client_info", "message"),
    [
        (["ios"], "Send a JSON object"),
        ("ios", "Send a JSON object"),
        ({"blob": "x" * 5000}, "Send at most 4096"),
    ],
)
def test_accept_refuses_a_client_that_is_not_a_small_object(client_info: Any, message: str) -> None:
    user = make_user()
    response = signed_in(user).post(
        ACCEPT, {"version": VERSION, "client": client_info}, format="json"
    )
    assert response.status_code == 400
    assert message in str(response.json()["client"])
    assert not TermsAcceptance.objects.filter(user=user).exists()


def test_accept_without_a_version_is_a_400() -> None:
    response = signed_in(make_user()).post(ACCEPT, {}, format="json")
    assert response.status_code == 400 and "version" in response.json()


def test_accept_in_session_mode(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    user = make_user()
    response = accept(session_client(user))
    assert response.status_code == 201
    assert TermsAcceptance.objects.filter(user=user, version=VERSION).exists()


def test_accept_is_safe_against_a_parallel_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from karni.accounts.models import TermsAcceptanceQuerySet

    user = make_user()
    parallel = TermsAcceptance.objects.create(user=user, version=VERSION)
    original = TermsAcceptanceQuerySet.first
    missed: list[bool] = []

    def first(self: TermsAcceptanceQuerySet) -> Any:
        # The first lookup ran before the parallel request committed its row.
        if not missed:
            missed.append(True)
            return None
        return original(self)

    monkeypatch.setattr(TermsAcceptanceQuerySet, "first", first)
    row, created = terms.accept(user, VERSION)
    assert created is False and row.pk == parallel.pk
    assert TermsAcceptance.objects.filter(user=user).count() == 1


# the gate


def test_the_gate_refuses_until_the_user_accepts_with_a_token() -> None:
    client = signed_in(make_user())
    body = assert_gated(client.get(PLAIN))
    assert 'POST /api/auth/terms/accept/ and {"version": "2026-11"}' in body["detail"]
    assert accept(client).status_code == 201
    assert client.get(PLAIN).status_code == 200


def test_the_gate_refuses_until_the_user_accepts_with_a_session(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    client = session_client(make_user())
    assert_gated(client.get(PLAIN))
    assert accept(client).status_code == 201
    assert client.get(PLAIN).status_code == 200


def test_the_gate_covers_a_karni_viewset_and_a_plain_django_view() -> None:
    client = signed_in(make_user())
    assert_gated(client.get(VENUES))
    assert_gated(client.get("/api/django/"))
    assert_gated(client.post(VENUES, {"name": "Arena", "city": "Berlin"}, format="json"))
    accept(client)
    assert client.get(VENUES).status_code == 200
    assert client.get("/api/django/").status_code == 200


def test_an_anonymous_request_passes_and_the_view_decides(client: APIClient) -> None:
    assert client.get(PLAIN).status_code == 401
    assert client.get(VENUES).status_code == 200


def test_a_token_drf_refuses_passes_to_the_view() -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert client.get(PLAIN).status_code == 401
    client.credentials(HTTP_AUTHORIZATION="Bearer two parts")
    assert client.get(PLAIN).status_code == 401


def test_staff_and_superusers_are_gated_like_everyone() -> None:
    staff = make_user("staff@example.com", is_staff=True)
    root = users().create_superuser(email="root@example.com", password=PASSWORD)
    for user in (staff, root):
        assert_gated(signed_in(user).get(PLAIN))


def test_the_auth_mount_stays_open() -> None:
    user = make_user()
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    assert client.get(ME).status_code == 200
    assert client.get(STATUS).status_code == 200
    assert client.get("/api/auth/csrf/").status_code == 204
    assert client.post("/api/auth/refresh/", {"refresh": str(refresh)}).status_code == 200
    login = APIClient().post(
        "/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json"
    )
    assert login.status_code == 200
    assert client.post("/api/auth/logout/", {"refresh": login.json()["refresh"]}).status_code == 204
    assert terms.auth_mount() == "/api/auth/"


def test_the_accounts_views_stay_open_wherever_they_are_mounted(settings: Settings) -> None:
    from karni.accounts.api import views

    module = ModuleType("terms_urls_bare")
    module.__dict__["urlpatterns"] = [
        path("api/me/", views.MeView.as_view()),
        path("api/terms/", views.TermsView.as_view()),
        path("api/plain/", PlainView.as_view()),
    ]
    settings.ROOT_URLCONF = module
    client = signed_in(make_user())
    assert terms.auth_mount() is None
    assert client.get("/api/me/").status_code == 200
    assert client.get("/api/terms/").status_code == 200
    assert_gated(client.get(PLAIN))


def test_the_schema_stays_open() -> None:
    client = signed_in(make_user())
    assert client.get("/api/schema/", {"format": "json"}).status_code == 200


def test_an_exempt_prefix_stays_open(settings: Settings) -> None:
    client = signed_in(make_user())
    assert_gated(client.get("/api/open/"))
    settings.KARNI_TERMS = {**TERMS, "exempt": ["/api/open/"]}
    assert client.get("/api/open/").status_code == 200
    assert_gated(client.get(PLAIN))


def test_a_path_outside_paths_is_not_gated(settings: Settings) -> None:
    user = make_user("staff@example.com", is_staff=True, is_superuser=True)
    assert signed_in(user).get("/outside/").status_code == 200
    admin = Client()
    admin.force_login(user)
    assert admin.get("/admin/").status_code == 200
    settings.KARNI_TERMS = {**TERMS, "paths": ["/api/", "/admin/"]}
    gated = Client()
    gated.force_login(user)
    assert_gated(gated.get("/admin/"))
    # Karni's own admin pages follow "paths" like any other page.
    assert_gated(gated.get("/admin/karni_accounts/role/matrix/"))
    assert signed_in(user).get("/outside/").status_code == 200


def test_required_false_gates_nothing(settings: Settings) -> None:
    settings.KARNI_TERMS = {**TERMS, "required": False}
    client = signed_in(make_user())
    assert client.get(PLAIN).status_code == 200
    assert client.get(STATUS).json()["required"] is False
    assert accept(client).status_code == 201


def test_no_setting_gates_nothing(settings: Settings) -> None:
    settings.KARNI_TERMS = None
    remount(settings)
    client = signed_in(make_user())
    assert client.get(PLAIN).status_code == 200
    assert "terms" not in client.get(ME).json()


def test_a_new_version_asks_everyone_again(settings: Settings) -> None:
    user = make_user()
    client = signed_in(user)
    accept(client)
    assert client.get(PLAIN).status_code == 200
    settings.KARNI_TERMS = {**TERMS, "version": "2027-01"}
    assert_gated(client.get(PLAIN), version="2027-01")
    assert accept(client, VERSION).json()["code"] == "E246"
    assert accept(client, "2027-01").status_code == 201
    assert client.get(PLAIN).status_code == 200
    assert sorted(TermsAcceptance.objects.filter(user=user).values_list("version", flat=True)) == [
        "2026-11",
        "2027-01",
    ]


def _gate_request(user: Any, *, token: bool) -> HttpRequest:
    if token:
        access = RefreshToken.for_user(user).access_token
        request = RequestFactory().get(PLAIN, HTTP_AUTHORIZATION=f"Bearer {access}")
        request.user = AnonymousUser()
    else:
        request = RequestFactory().get(PLAIN)
        request.user = user
    return request


@pytest.mark.parametrize("token", [True, False], ids=["jwt", "session"])
def test_a_gated_request_costs_no_query_after_the_first(
    token: bool, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    user = make_user()
    gate = TermsGateMiddleware(lambda request: HttpResponse())
    view = PlainView.as_view()
    request = _gate_request(user, token=token)
    cache.clear()
    with django_assert_num_queries(1):
        assert gate.process_view(request, view, (), {}).status_code == 403  # type: ignore[union-attr]
    with django_assert_num_queries(0):
        assert gate.process_view(request, view, (), {}).status_code == 403  # type: ignore[union-attr]
    terms.accept(user, VERSION)
    with django_assert_num_queries(1):
        assert gate.process_view(request, view, (), {}) is None
    with django_assert_num_queries(0):
        assert gate.process_view(request, view, (), {}) is None
        assert terms.me_status(user) == {
            "required": True,
            "version": VERSION,
            "url": "/terms/",
            "accepted": True,
        }


def test_an_acceptance_is_cached_when_its_transaction_commits(
    django_capture_on_commit_callbacks: Any,
) -> None:
    user = make_user()
    key = terms.cache_key(user.pk, VERSION)
    assert terms.has_accepted(user.pk, VERSION) is False
    assert cache.get(key) is False
    with django_capture_on_commit_callbacks(execute=True):
        terms.accept(user, VERSION)
        assert cache.get(key) is None  # cleared at once
    assert cache.get(key) is True


# /me/


def test_me_carries_terms_only_while_the_setting_is_set(settings: Settings) -> None:
    user = make_user()
    client = signed_in(user)
    assert client.get(ME).json()["terms"] == {
        "required": True,
        "version": VERSION,
        "url": "/terms/",
        "accepted": False,
    }
    accept(client)
    assert client.get(ME).json()["terms"]["accepted"] is True
    login = APIClient().post("/api/auth/login/", {"email": user.email, "password": PASSWORD})
    assert login.json()["user"]["terms"]["accepted"] is True
    settings.KARNI_TERMS = None
    assert "terms" not in client.get(ME).json()


def _schema() -> tuple[dict[str, Any], list[str]]:
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator().get_schema(request=None, public=True)
    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    GENERATOR_STATS.reset()
    return schema, messages


def test_the_schema_has_the_terms_only_while_the_setting_is_set(settings: Settings) -> None:
    schema, messages = _schema()
    assert {STATUS, ACCEPT} <= set(schema["paths"])
    assert "terms" in schema["components"]["schemas"]["Me"]["properties"]
    assert "TermsStatus" in schema["components"]["schemas"]
    ours = ("karni/accounts", "TermsView", "TermsAccept")
    assert not [message for message in messages if any(part in message for part in ours)]
    settings.KARNI_TERMS = None
    remount(settings)
    schema, _ = _schema()
    assert not {STATUS, ACCEPT} & set(schema["paths"])
    assert "terms" not in schema["components"]["schemas"]["Me"]["properties"]


# the record


def test_an_acceptance_is_permanent() -> None:
    user = make_user()
    row, _ = terms.accept(user, VERSION)
    rows = TermsAcceptance.objects.filter(user=user)
    attempts = [
        lambda: row.save(),
        lambda: row.delete(),
        lambda: row.hard_delete(),
        lambda: row.restore(),
        lambda: rows.update(version="other"),
        lambda: rows.delete(),
        lambda: rows.hard_delete(),
        lambda: rows.restore(),
    ]
    for attempt in attempts:
        with pytest.raises(PermanentRecordError) as raised:
            attempt()
        assert raised.value.code == "E247"
        assert str(raised.value).startswith("E247: TermsAcceptance rows are permanent")
    lifted = TermsAcceptance.objects.without("soft_delete", reason="test: every row")
    with pytest.raises(PermanentRecordError):
        lifted.filter(user=user).delete()
    # bulk_update() runs in a transaction without a savepoint: give it one.
    with pytest.raises(PermanentRecordError), transaction.atomic():
        TermsAcceptance.objects.bulk_update([row], ["version"])
    assert get_code("E247") is not None
    assert TermsAcceptance.objects.get(pk=row.pk).version == VERSION


def test_one_row_per_user_and_version() -> None:
    user = make_user()
    TermsAcceptance.objects.create(user=user, version=VERSION)
    with pytest.raises(IntegrityError), transaction.atomic():
        TermsAcceptance.objects.create(user=user, version=VERSION)
    TermsAcceptance.objects.create(user=user, version="2027-01")


def test_a_users_rows_go_with_the_user_only() -> None:
    user = make_user()
    terms.accept(user, VERSION)
    user.delete()  # soft: the record stays
    assert TermsAcceptance.objects.filter(user_id=user.pk).count() == 1
    user.hard_delete()
    assert TermsAcceptance.objects.filter(user_id=user.pk).count() == 0


def test_the_permission_matrix_leaves_the_record_out() -> None:
    assert "karni_accounts.TermsAcceptance" in DEFAULT_MATRIX_EXCLUDE


# the admin


def test_the_admin_lists_acceptances_read_only_with_a_version_filter(admin_client: Any) -> None:
    from django.contrib import admin

    ada = make_user()
    grace = make_user("grace@example.com")
    terms.accept(ada, VERSION, ip="203.0.113.9")
    TermsAcceptance.objects.create(user=grace, version="2025-01")
    model_admin = admin.site._registry[TermsAcceptance]
    request = type("R", (), {"user": users().filter(is_superuser=True).first()})()
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False

    base = "/admin/karni_accounts/termsacceptance/"
    listing = admin_client.get(base)
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "ada@example.com" in html and "grace@example.com" in html
    filtered = admin_client.get(base, {"version": VERSION}).content.decode()
    assert "ada@example.com" in filtered and "grace@example.com" not in filtered
    assert admin_client.get(f"{base}add/").status_code == 403
    detail = admin_client.get(f"{base}{TermsAcceptance.objects.get(user=ada).pk}/change/")
    assert detail.status_code == 200 and 'name="_save"' not in detail.content.decode()
    row = TermsAcceptance.objects.get(user=ada)
    assert admin_client.get(f"{base}{row.pk}/delete/").status_code == 403
    assert admin_client.get(f"{base}import/").status_code == 403
    assert f"{base}import/" not in html


def test_the_admin_exports_the_record(admin_client: Any) -> None:
    ada = make_user()
    row, _ = terms.accept(ada, VERSION, ip="203.0.113.9", user_agent="ExampleApp/2.4.0")
    response = admin_client.post(
        "/admin/karni_accounts/termsacceptance/",
        {"action": "export_csv", "_selected_action": [str(row.pk)]},
    )
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(b"".join(response.streaming_content).decode())))
    header = rows[0]
    assert {"version", "accepted_at", "ip", "user_agent"} <= set(header)
    assert rows[1][header.index("version")] == VERSION
    assert rows[1][header.index("ip")] == "203.0.113.9"


def test_the_users_page_shows_their_acceptances(admin_client: Any, settings: Settings) -> None:
    user = make_user()
    terms.accept(user, VERSION)
    inline = "terms_acceptances-TOTAL_FORMS"
    page = admin_client.get(f"/admin/karni_accounts/user/{user.pk}/change/").content.decode()
    assert inline in page and VERSION in page
    settings.KARNI_TERMS = None
    page = admin_client.get(f"/admin/karni_accounts/user/{user.pk}/change/").content.decode()
    assert inline not in page
