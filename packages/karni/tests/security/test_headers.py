"""Security headers by default: karni.security.SecurityHeadersMiddleware.

Every response carries a Content-Security-Policy (report-only while DEBUG is
on) and a Permissions-Policy. The pages Django serves keep working: the
admin, the API docs, the welcome page, and anything a view extends.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from pytest_django import Settings

from karni.conf.validation import validate_settings
from karni.exceptions import KarniImproperlyConfigured
from karni.security import DEFAULT_CSP, csp_directives, permissions_policy, script_hash
from karni.security.headers import THEME_SCRIPT, render_csp
from karni.welcome.page import SCRIPT
from karni.welcome.page import THEME_SCRIPT as WELCOME_THEME_SCRIPT

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.security.urls")]

ENFORCED = "Content-Security-Policy"
REPORT_ONLY = "Content-Security-Policy-Report-Only"


def _policy(response: Any, header: str = ENFORCED) -> dict[str, list[str]]:
    value = response.headers[header]
    policy: dict[str, list[str]] = {}
    for part in value.split(";"):
        name, *sources = part.split()
        policy[name] = sources
    return policy


# --- the default policy -------------------------------------------------------


def test_an_enforced_policy_with_debug_off(client: Client, settings: Settings) -> None:
    settings.DEBUG = False
    response = client.get("/plain/")
    assert REPORT_ONLY not in response.headers
    assert _policy(response) == {name: list(sources) for name, sources in DEFAULT_CSP.items()}
    assert _policy(response)["script-src"] == ["'self'", script_hash(THEME_SCRIPT)]
    assert _policy(response)["frame-ancestors"] == ["'none'"]


def test_report_only_while_debug_is_on(client: Client, settings: Settings) -> None:
    settings.DEBUG = True
    response = client.get("/plain/")
    assert ENFORCED not in response.headers
    assert _policy(response, REPORT_ONLY)["default-src"] == ["'self'"]


@pytest.mark.parametrize(
    ("debug", "report_only", "header"),
    [
        (True, False, ENFORCED),
        (False, True, REPORT_ONLY),
        (False, None, ENFORCED),
        (True, None, REPORT_ONLY),
    ],
)
def test_the_report_only_setting_wins_over_debug(
    client: Client, settings: Settings, debug: bool, report_only: bool | None, header: str
) -> None:
    settings.DEBUG = debug
    settings.KARNI_CSP_REPORT_ONLY = report_only
    response = client.get("/plain/")
    assert header in response.headers
    assert ({ENFORCED, REPORT_ONLY} - {header}).isdisjoint(response.headers)


def test_api_responses_carry_it_too(client: Client) -> None:
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert ENFORCED in response.headers
    assert "Permissions-Policy" in response.headers


def test_django_sends_the_referrer_policy_and_nosniff(client: Client) -> None:
    response = client.get("/plain/")
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


# --- KARNI_CSP ----------------------------------------------------------------


def test_karni_csp_adds_sources(client: Client, settings: Settings) -> None:
    settings.KARNI_CSP = {
        "font-src": ["https://fonts.gstatic.com"],
        "style-src": "https://fonts.googleapis.com",
        "report-uri": ["/csp-report/"],
    }
    policy = _policy(client.get("/plain/"))
    assert policy["font-src"] == ["'self'", "data:", "https://fonts.gstatic.com"]
    assert policy["style-src"] == ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
    assert policy["report-uri"] == ["/csp-report/"]


def test_none_removes_a_directive(client: Client, settings: Settings) -> None:
    settings.KARNI_CSP = {"form-action": None}
    assert "form-action" not in _policy(client.get("/plain/"))


def test_adding_to_none_replaces_it(client: Client, settings: Settings) -> None:
    settings.KARNI_CSP = {"frame-ancestors": ["https://partner.example"]}
    policy = _policy(client.get("/plain/"))
    assert policy["frame-ancestors"] == ["https://partner.example"]
    assert policy["object-src"] == ["'none'"]


def test_karni_csp_none_turns_the_header_off(client: Client, settings: Settings) -> None:
    settings.KARNI_CSP = None
    response = client.get("/plain/")
    assert ENFORCED not in response.headers and REPORT_ONLY not in response.headers
    assert "Permissions-Policy" in response.headers


def test_frame_ancestors_follow_x_frame_options(client: Client, settings: Settings) -> None:
    settings.X_FRAME_OPTIONS = "SAMEORIGIN"
    assert _policy(client.get("/plain/"))["frame-ancestors"] == ["'self'"]


@pytest.mark.parametrize(
    ("extra", "origins"),
    [
        (
            {"AWS_STORAGE_BUCKET_NAME": "media", "AWS_S3_REGION_NAME": "eu-west-1"},
            ["https://media.s3.amazonaws.com", "https://media.s3.eu-west-1.amazonaws.com"],
        ),
        ({"AWS_S3_CUSTOM_DOMAIN": "cdn.example.com"}, ["https://cdn.example.com"]),
        (
            {"AWS_STORAGE_BUCKET_NAME": "media", "AWS_S3_ENDPOINT_URL": "https://r2.example.net"},
            ["https://r2.example.net", "https://media.r2.example.net"],
        ),
    ],
)
def test_media_on_s3_is_allowed(
    settings: Settings, extra: dict[str, str], origins: list[str]
) -> None:
    settings.KARNI_STORAGE = "s3"
    for name, value in extra.items():
        setattr(settings, name, value)
    directives = csp_directives()
    assert directives is not None
    assert directives["img-src"] == ["'self'", "data:", "blob:", *origins]
    assert directives["media-src"] == ["'self'", *origins]


# --- Permissions-Policy -------------------------------------------------------


def test_permissions_policy_switches_powerful_features_off(client: Client) -> None:
    value = client.get("/plain/").headers["Permissions-Policy"]
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in value


def test_permissions_policy_setting(client: Client, settings: Settings) -> None:
    settings.KARNI_PERMISSIONS_POLICY = {
        "geolocation": ["self", "https://maps.example.com"],
        "usb": None,
        "fullscreen": ["*"],
    }
    value = client.get("/plain/").headers["Permissions-Policy"]
    assert 'geolocation=(self "https://maps.example.com")' in value
    assert "usb=" not in value
    assert "fullscreen=(*)" in value
    settings.KARNI_PERMISSIONS_POLICY = None
    assert permissions_policy() is None
    assert "Permissions-Policy" not in client.get("/plain/").headers


# --- per page -----------------------------------------------------------------


def test_view_decorators_and_a_header_the_view_set(client: Client) -> None:
    mapped = _policy(client.get("/map/"))
    assert mapped["img-src"][-1] == "https://tiles.example.com"
    assert mapped["frame-src"] == ["https://maps.example.com"]
    exempt = client.get("/exempt/").headers
    assert ENFORCED not in exempt and REPORT_ONLY not in exempt
    own = client.get("/own/").headers
    assert own[ENFORCED] == "default-src 'none'"
    assert REPORT_ONLY not in own


def test_sources_added_while_the_response_is_built(client: Client) -> None:
    policy = _policy(client.get("/rendering/"))
    assert policy["script-src"][-1] == script_hash("run()")
    assert policy["style-src"][-1] == "https://fonts.example.com"
    both = _policy(client.get("/both/"))
    assert both["img-src"][-2:] == ["https://cdn.example.com", "https://tiles.example.com"]
    # Only that response: the next page has the default policy.
    assert script_hash("run()") not in _policy(client.get("/plain/"))["script-src"]


def test_only_admin_pages_allow_eval(client: Client) -> None:
    admin = client.get("/staff-area/login/")
    assert admin.status_code == 200
    assert "'unsafe-eval'" in _policy(admin)["script-src"]
    assert "'unsafe-eval'" not in _policy(client.get("/plain/"))["script-src"]


def test_the_swagger_page_may_load_its_cdn(client: Client) -> None:
    response = client.get("/api/docs/")
    assert response.status_code == 200
    policy = _policy(response)
    assert "https://cdn.jsdelivr.net" in policy["script-src"]
    assert "'unsafe-inline'" in policy["script-src"]  # its start-up script is inline
    # Browsers ignore 'unsafe-inline' next to a hash, so the theme script's hash goes.
    assert not any(source.startswith("'sha256-") for source in policy["script-src"])
    assert "https://cdn.jsdelivr.net" in policy["style-src"]
    assert "https://cdn.jsdelivr.net" in policy["img-src"]
    # Every script and stylesheet the page loads is from an allowed origin.
    html = response.content.decode()
    for url in re.findall(r'(?:src|href)="(https://[^"]+)"', html):
        assert url.startswith("https://cdn.jsdelivr.net/")


def test_the_split_swagger_page_needs_no_inline_script(client: Client) -> None:
    policy = _policy(client.get("/api/docs-split/"))
    assert "https://cdn.jsdelivr.net" in policy["script-src"]
    assert "'unsafe-inline'" not in policy["script-src"]


def test_the_redoc_page_may_load_its_cdn_fonts_and_worker(client: Client) -> None:
    policy = _policy(client.get("/api/redoc/"))
    assert "https://cdn.jsdelivr.net" in policy["script-src"]
    assert "https://fonts.googleapis.com" in policy["style-src"]
    assert "https://fonts.gstatic.com" in policy["font-src"]
    assert "https://cdn.redoc.ly" in policy["img-src"]
    assert policy["worker-src"] == ["'self'", "blob:"]


def test_the_welcome_page_runs_exactly_its_own_scripts(client: Client, settings: Settings) -> None:
    settings.DEBUG = True
    response = client.get("/")
    assert response.status_code == 200
    policy = _policy(response, REPORT_ONLY)
    inline = re.findall(r"<script>(.*?)</script>", response.content.decode(), flags=re.DOTALL)
    assert len(inline) == 2
    for source in inline:
        assert script_hash(source) in policy["script-src"]
    assert script_hash(WELCOME_THEME_SCRIPT) in policy["script-src"]
    assert script_hash(SCRIPT) in policy["script-src"]
    assert "'unsafe-inline'" not in policy["script-src"]


def test_the_theme_script_is_karni_uis() -> None:
    """The default policy's hash allows @karni/ui's pre-paint script, character for character."""
    source = Path(__file__).resolve().parents[3] / "karni-ui" / "src" / "theme" / "script.ts"
    if not source.is_file():
        pytest.skip("@karni/ui's source is not next to this package")
    text = source.read_text(encoding="utf-8")
    key = re.search(r'THEME_STORAGE_KEY = "([^"]+)"', text)
    script = re.search(r"KARNI_THEME_SCRIPT = `([^`]+)`", text)
    assert key is not None and script is not None
    assert script.group(1).replace("${THEME_STORAGE_KEY}", key.group(1)) == THEME_SCRIPT


def test_adding_unsafe_inline_drops_hashes_and_nonces() -> None:
    from karni.security.headers import merge_directives

    base = {"script-src": ["'self'", "'sha256-abc='", "'nonce-xyz'"], "style-src": ["'self'"]}
    merged = merge_directives(base, {"script-src": ["'unsafe-inline'"]})
    assert merged["script-src"] == ["'self'", "'unsafe-inline'"]
    assert merge_directives(base, {"script-src": ["https://cdn.example"]})["script-src"] == [
        "'self'",
        "'sha256-abc='",
        "'nonce-xyz'",
        "https://cdn.example",
    ]
    # A hash added next to 'unsafe-inline' would switch it off in browsers: it is left out.
    inline = {"script-src": ["'self'", "'unsafe-inline'"]}
    added = merge_directives(inline, {"script-src": ["'unsafe-hashes'", "'sha256-def='"]})
    assert added["script-src"] == ["'self'", "'unsafe-inline'", "'unsafe-hashes'"]


def test_render_csp_joins_directives() -> None:
    assert render_csp({"default-src": ["'self'"], "upgrade-insecure-requests": []}) == (
        "default-src 'self'; upgrade-insecure-requests"
    )


# --- settings -----------------------------------------------------------------


def test_karni_settings_puts_the_middleware_after_djangos(make_settings: Any) -> None:
    middleware = make_settings()["MIDDLEWARE"]
    index = middleware.index("django.middleware.security.SecurityMiddleware")
    assert middleware[index + 1] == "karni.security.SecurityHeadersMiddleware"


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("KARNI_CSP", "default-src 'self'", "must be a dict"),
        ("KARNI_CSP", {"Script_Src": ["'self'"]}, "is not a directive name"),
        ("KARNI_CSP", {"script-src": [1]}, "must be a list of strings"),
        ("KARNI_PERMISSIONS_POLICY", ["camera"], "must be a dict"),
        ("KARNI_PUBLIC_CREATE_RATE", "ten an hour", "is not a valid throttle rate"),
    ],
)
def test_validation_rejects_bad_values(
    make_settings: Any, setting: str, value: Any, message: str
) -> None:
    with pytest.raises(KarniImproperlyConfigured, match=message):
        validate_settings({**make_settings(), setting: value})


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("KARNI_CSP", None),
        ("KARNI_CSP", {"font-src": "https://fonts.gstatic.com", "form-action": None}),
        ("KARNI_PERMISSIONS_POLICY", None),
        ("KARNI_PUBLIC_CREATE_RATE", None),
        ("KARNI_PUBLIC_CREATE_RATE", ""),
    ],
)
def test_validation_accepts_the_documented_values(
    make_settings: Any, setting: str, value: Any
) -> None:
    validate_settings({**make_settings(), setting: value})
