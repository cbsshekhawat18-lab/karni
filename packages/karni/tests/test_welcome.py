"""The welcome page: live, DEBUG-only, gone the moment the project owns "/", and leak-free."""

from __future__ import annotations

import importlib
import re
from typing import Any

import django
import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory
from django.urls import clear_url_caches

from karni.checks import check_welcome_route
from karni.seeding import DEMO_LOGIN
from karni.welcome import inventory, status
from karni.welcome.views import WelcomeView

pytestmark = pytest.mark.django_db

_SENSITIVE = re.compile(
    r"SECRET|PASSWORD|TOKEN|KEY|DSN|DATABASE|REDIS|BROKER|EMAIL_HOST|AWS|STRIPE|RAZORPAY|CACHES",
    re.I,
)


def _use_urlconf(settings: Any, name: str, *, debug: bool) -> None:
    """Point the test at ``name`` with ``DEBUG`` set first, so ``welcome_urls()`` sees it."""
    settings.DEBUG = debug
    importlib.reload(importlib.import_module(name))
    settings.ROOT_URLCONF = name
    clear_url_caches()


@pytest.fixture
def first_boot(settings: Any) -> None:
    """A fresh scaffold's shape: DEBUG on, nothing answers "/" but the welcome route."""
    settings.CELERY_BROKER_URL = "redis://127.0.0.1:1/0"  # nothing listens there
    settings.KARNI_FRONTEND_URL = "http://127.0.0.1:1/"
    _use_urlconf(settings, "tests.welcome_urls", debug=True)


def test_renders_at_the_root_on_a_fresh_scaffold(first_boot: None, client: Any) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert response["Cache-Control"] == "no-store"
    html = response.content.decode()
    assert "Karni is running" in html
    assert f"Django {django.get_version()}" in html
    assert "<svg" in html  # the mark, inline
    assert len(response.content) < 50_000
    for external in ("<script src", "<link ", "@import", "fonts.googleapis", "cdn."):
        assert external not in html
    assert client.head("/").status_code == 200


def test_wears_the_karni_ui_brand(first_boot: None, client: Any) -> None:
    """The tokens are inlined, the page reads only them, dark mode is the `dark` class."""
    from karni.admin.theme import tokens_css
    from karni.welcome.page import CSS, THEME_SCRIPT

    html = client.get("/").content.decode()
    assert f"<style>{tokens_css()}</style>" in html
    assert html.index("<script>") < html.index("</head>")  # theme set before first paint
    assert "prefers-color-scheme: dark" in THEME_SCRIPT and "'dark'" in THEME_SCRIPT
    assert "@media (prefers-color-scheme" not in CSS  # no second dark palette
    # Every colour is a token, except the mark's orange as the one highlight.
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", CSS) == ["#FB5D08"]
    assert not re.search(r"\b(?:rgb|hsl|oklch)a?\(", CSS)


def test_is_a_404_with_debug_off(settings: Any, client: Any) -> None:
    _use_urlconf(settings, "tests.welcome_urls", debug=False)
    assert client.get("/").status_code == 404  # the route is not even mounted
    with pytest.raises(Http404):  # and the view refuses on its own
        WelcomeView.as_view()(RequestFactory().get("/"))


def test_disappears_once_the_project_owns_the_root(settings: Any, client: Any) -> None:
    _use_urlconf(settings, "tests.welcome_own_root_urls", debug=True)
    response = client.get("/")
    assert response.status_code == 200
    assert response.content == b"my own home"


def test_every_status_check_reports_both_states(
    first_boot: None, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_key = {item.key: item for item in status.run_checks()}
    assert [*by_key] == [
        "database",
        "migrations",
        "superuser",
        "seed",
        "redis",
        "celery",
        "frontend",
    ]
    assert by_key["database"].ok and by_key["migrations"].ok
    assert not by_key["superuser"].ok and by_key["superuser"].fix == "karni createsuperuser"
    assert not by_key["seed"].ok and by_key["seed"].fix == "karni seed"
    assert not by_key["redis"].ok and by_key["redis"].fix == "docker compose up -d redis"
    assert not by_key["celery"].ok and by_key["celery"].fix == "karni worker"
    assert not by_key["frontend"].ok and by_key["frontend"].fix == "cd frontend && npm run dev"
    for item in by_key.values():
        assert item.ok or item.fix, f"{item.key}: a cross must carry its fix"

    html = client.get("/").content.decode()  # the page shows the cross and the command
    assert "✗" in html
    for fix in (
        "karni createsuperuser",
        "karni seed",
        "docker compose up -d redis",
        "karni worker",
    ):
        assert fix in html
    assert "cd frontend &amp;&amp; npm run dev" in html

    user_model = get_user_model()
    user_model.objects.create_superuser(email="root@example.com", password="a-strong-password-123")
    user_model.objects.create_user(email=DEMO_LOGIN, password="a-strong-password-123")
    monkeypatch.setattr(status, "_redis_ping", lambda url: True)
    monkeypatch.setattr(status, "check_celery", lambda: (True, "1 worker(s) replied"))
    monkeypatch.setattr(status, "_http_alive", lambda url: True)
    flipped = status.run_checks()
    assert all(item.ok for item in flipped), [item.key for item in flipped if not item.ok]
    assert all(not item.fix or item.ok for item in flipped)
    html = client.get("/").content.decode()
    assert "✗" not in html and "✓" in html


def test_renders_with_models_and_their_links_resolve(first_boot: None, client: Any) -> None:
    found = inventory.models()
    assert found, "the test apps register models"
    html = client.get("/").content.decode()
    assert f"{len(found)} models" in html
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    client.force_login(root)
    for link in found:
        assert link.name in html
        if link.admin_url:
            assert link.admin_url in html
            assert client.get(link.admin_url).status_code == 200
        if link.api_url:
            assert link.api_url in html
            assert client.get(link.api_url).status_code in {200, 401, 403}
    assert any(link.admin_url for link in found) and any(link.api_url for link in found)


def test_renders_with_zero_models(first_boot: None, client: Any, settings: Any) -> None:
    settings.KARNI_CONTEXT_SKIP_APPS = frozenset(cfg.label for cfg in apps.get_app_configs())
    assert inventory.models() == []
    html = client.get("/").content.decode()
    assert "No models yet" in html
    assert 'id="first-model"' in html and "make migrate &amp;&amp; karni types" in html


def test_renders_with_the_frontend_dev_server_stopped(first_boot: None, client: Any) -> None:
    html = client.get("/").content.decode()  # KARNI_FRONTEND_URL points at a closed port
    assert "Frontend dev server running" in html and "cd frontend" in html
    assert "http://127.0.0.1:1/" in html  # the link stays; only the status is a cross


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _string_leaves(item)]
    if isinstance(value, list | tuple | set | frozenset):
        return [leaf for item in value for leaf in _string_leaves(item)]
    return []


def test_no_settings_value_leaks_into_the_html(
    first_boot: None, client: Any, settings: Any
) -> None:
    html = client.get("/").content.decode()
    leaked = []
    for name in dir(settings):
        if not name.isupper() or not _SENSITIVE.search(name):
            continue
        for leaf in _string_leaves(getattr(settings, name)):
            # Values shorter than this are words like "json" that any page may contain.
            if len(leaf) >= 8 and leaf in html:
                leaked.append(f"{name}: {leaf!r}")
    assert leaked == [], leaked
    assert settings.SECRET_KEY not in html
    assert settings.CELERY_BROKER_URL not in html
    assert settings.CACHES["default"]["LOCATION"] not in html
    assert str(settings.MEDIA_ROOT) not in html
    assert "redis://" not in html and "postgres" not in html.lower()


def test_the_production_check_catches_a_hand_mounted_route(settings: Any) -> None:
    _use_urlconf(settings, "tests.welcome_prod_urls", debug=False)
    messages = check_welcome_route()
    assert [message.id for message in messages] == ["karni.E505"]
    assert "DEBUG is False" in messages[0].msg
    _use_urlconf(settings, "tests.welcome_urls", debug=False)
    assert check_welcome_route() == []  # welcome_urls() mounted nothing
    settings.DEBUG = True
    assert check_welcome_route() == []  # development: nothing to report


def test_media_urls_serve_uploads_only_in_debug_with_local_storage(settings: Any) -> None:
    from karni.welcome import media_urls

    local = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    settings.STORAGES = local
    settings.MEDIA_URL = "/media/"
    settings.MEDIA_ROOT = "/nonexistent/media"
    settings.DEBUG = False
    assert media_urls() == []
    settings.DEBUG = True
    (route,) = media_urls()
    assert route.pattern.regex.match("media/covers/pic.png")
    settings.STORAGES = {"default": {"BACKEND": "karni.storage.S3Storage"}}
    assert media_urls() == []
