"""SITE001 and SITE002: what the site's templates rely on."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pytest_django import Settings

from karni_site import checks


def test_a_wired_project_passes() -> None:
    assert checks.run_checks() == []
    assert {"website:home", "website:about", "website:service_web"} <= set(checks.url_names())


def test_the_request_processor_is_required(settings: Settings) -> None:
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["OPTIONS"]["context_processors"] = [
        p
        for p in templates[0]["OPTIONS"]["context_processors"]
        if p != "django.template.context_processors.request"
    ]
    settings.TEMPLATES = templates
    (failure,) = checks.run_checks()
    assert failure.startswith("SITE001: add 'django.template.context_processors.request'")


def test_the_site_processor_and_the_redirect_middleware_are_required(settings: Settings) -> None:
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["OPTIONS"]["context_processors"].remove("karni_site.context_processors.site")
    settings.TEMPLATES = templates
    settings.MIDDLEWARE = [
        m for m in settings.MIDDLEWARE if m != "karni_site.middleware.RedirectMiddleware"
    ]
    site, middleware = checks.run_checks()
    assert site.startswith("SITE004: add 'karni_site.context_processors.site'")
    assert middleware.startswith("SITE005: add 'karni_site.middleware.RedirectMiddleware'")


def test_one_key_with_two_defaults_is_reported(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text(
        '{% load karni_site %}{% editable "home.intro" %}Hello\n  there{% endeditable %}\n'
        '{% editable "home.same" %}Shared{% endeditable %}'
    )
    (tmp_path / "b.html").write_text(
        '{% load karni_site %}{% editable "home.intro" %}Hello there{% endeditable %}\n'
        '{% editable "home.same" %}Shared{% endeditable %}\n'
        '{% editable "home.intro" %}Goodbye{% endeditable %}\n'
        '{% editable_image "home.same" %}<img src="x.png" alt="">{% endeditable_image %}'
    )
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["DIRS"] = [tmp_path]
    settings.TEMPLATES = templates
    failures = checks.run_checks()
    assert [f.split(": block")[0] for f in failures] == [
        f"SITE008: {tmp_path / 'b.html'}:3",
        f"SITE008: {tmp_path / 'b.html'}:4",
    ]
    assert f"than at {tmp_path / 'a.html'}:1" in failures[0]


def test_unknown_url_names_in_ifactive_are_reported(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "nav.html").write_text(
        "{% load karni_site %}\n"
        '<a{% ifactive "website:about" %} class="on"{% endifactive %}>About</a>\n'
        '<a{% ifactive "website:abuot" "/x/" %} class="on"{% endifactive %}>Typo</a>\n'
        '<a{% ifactive "website:service_*" names %} class="on"{% endifactive %}>Many</a>\n'
        '<a{% ifactive "shop:*" %} class="on"{% endifactive %}>None</a>\n'
    )
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["DIRS"] = [tmp_path]
    settings.TEMPLATES = templates
    failures = checks.run_checks()
    assert [f.split(": {%")[0] for f in failures] == [
        f"SITE002: {tmp_path / 'nav.html'}:3",
        f"SITE002: {tmp_path / 'nav.html'}:5",
    ]
    assert "'website:abuot'" in failures[0] and "'shop:*'" in failures[1]


def test_nothing_is_checked_when_the_app_is_not_installed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.apps import apps

    monkeypatch.setattr(apps, "is_installed", lambda name: False)
    assert checks.run_checks() == []
