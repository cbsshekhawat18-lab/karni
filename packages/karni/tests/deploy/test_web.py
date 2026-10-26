"""``manage.py karni_publish_web``: the Caddyfile, the headers snippet and the staff app."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from karni.deploy import web

PRODUCTION = {
    "DEBUG": False,
    "SECURE_HSTS_SECONDS": 31536000,
    "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
    "SECURE_HSTS_PRELOAD": True,
    "KARNI_CSP": {"img-src": ["https://images.example.com"]},
    "KARNI_CSP_REPORT_ONLY": None,
}


def _build(folder: Path, script: str) -> Path:
    (folder / "assets").mkdir(parents=True)
    (folder / "assets" / script).write_text("console.log(1)")
    (folder / "index.html").write_text(f'<script src="/app/assets/{script}"></script>')
    return folder


@pytest.mark.django_db
@override_settings(**PRODUCTION)
def test_the_snippet_carries_the_policy_a_django_page_gets() -> None:
    page = Client().get("/health/", secure=True)
    headers = web.security_headers()
    assert headers["Content-Security-Policy"] == page["Content-Security-Policy"]
    assert "https://images.example.com" in headers["Content-Security-Policy"]
    assert headers["Permissions-Policy"] == page["Permissions-Policy"]
    assert headers["Strict-Transport-Security"] == page["Strict-Transport-Security"]
    for name in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert headers[name] == page[name]
    snippet = web.caddy_headers(headers)
    assert snippet.count("(karni_headers) {") == 1
    assert f'\t\tContent-Security-Policy "{headers["Content-Security-Policy"]}"' in snippet


def test_quotes_in_a_value_are_escaped() -> None:
    assert 'X-Test "say \\"hi\\""' in web.caddy_headers({"X-Test": 'say "hi"'})


def test_publish_writes_everything_and_keeps_an_earlier_build(tmp_path: Path) -> None:
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("{$DOMAIN} {\n}\n")
    root = tmp_path / "web"
    day = 86400.0
    first = _build(tmp_path / "build1", "index-aaa.js")
    web.publish(root, app=first, caddyfile=caddyfile, headers={"X-A": "1"}, now=10 * day)
    second = _build(tmp_path / "build2", "index-bbb.js")
    result = web.publish(root, app=second, caddyfile=caddyfile, headers={"X-A": "1"}, now=11 * day)
    assert (root / "Caddyfile").read_text() == caddyfile.read_text()
    assert "X-A" in (root / web.HEADERS_FILE).read_text()
    app = root / web.APP_DIR
    assert "index-bbb.js" in (app / "index.html").read_text()
    # A browser holding yesterday's index.html still loads its script ...
    assert (app / "assets" / "index-aaa.js").is_file()
    assert not result.skipped
    # ... until the earlier build is a week older than the newest.
    web.publish(root, app=second, caddyfile=caddyfile, headers={}, now=18.5 * day)
    assert not (app / "assets" / "index-aaa.js").exists()
    assert (app / "assets" / "index-bbb.js").is_file()
    seen = json.loads((app / web.SEEN_FILE).read_text())
    assert set(seen) == {"index.html", "assets/index-bbb.js"}


def test_a_project_without_a_staff_app_or_caddyfile_is_skipped(tmp_path: Path) -> None:
    result = web.publish(tmp_path / "web", app=tmp_path / "none", caddyfile=None, headers={})
    assert len(result.skipped) == 2
    assert (tmp_path / "web" / web.HEADERS_FILE).is_file()


@pytest.mark.django_db
def test_the_command(tmp_path: Path) -> None:
    out = io.StringIO()
    build = _build(tmp_path / "dist", "main-ccc.js")
    call_command(
        "karni_publish_web",
        root=str(tmp_path / "web"),
        app=str(build),
        caddyfile="",
        stdout=out,
    )
    assert "published:" in out.getvalue() and "skipped:" in out.getvalue()
    assert (tmp_path / "web" / "app" / "assets" / "main-ccc.js").is_file()
