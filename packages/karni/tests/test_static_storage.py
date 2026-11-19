"""KARNI_STATIC_STORAGE: plain names, or fingerprinted ones a browser may keep for a year.

The manifest storage is run for real: ``collectstatic`` over a small folder of files, then
``{% static %}`` in a template (in a tag and in a data attribute), a stylesheet's
``url(...)``, and a name the manifest does not hold.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

import environ
import pytest
from django.core.management import call_command
from django.template import Context, Template
from django.templatetags.static import static
from django.test import override_settings

from karni.conf.base import STATIC_STORAGES, _storages
from karni.exceptions import KarniImproperlyConfigured

PLAIN = "django.contrib.staticfiles.storage.StaticFilesStorage"
MANIFEST = "karni.storage.static.ManifestStaticStorage"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_the_names_choose_the_static_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARNI_STATIC_STORAGE", raising=False)
    env = environ.Env()
    assert _storages(env)["staticfiles"]["BACKEND"] == PLAIN, "unchanged by default"
    assert _storages(env, static="manifest")["staticfiles"]["BACKEND"] == MANIFEST
    assert _storages(env, static="myapp.storage.Mine")["staticfiles"]["BACKEND"] == (
        "myapp.storage.Mine"
    )
    monkeypatch.setenv("KARNI_STATIC_STORAGE", "manifest")
    assert _storages(environ.Env())["staticfiles"]["BACKEND"] == MANIFEST
    with pytest.raises(KarniImproperlyConfigured, match="E510"):
        _storages(env, static="hashed")
    assert set(STATIC_STORAGES) == {"plain", "manifest"}


def test_karni_settings_reads_it_before_the_call(make_settings) -> None:
    ns = make_settings("prod", preset={"KARNI_STATIC_STORAGE": "manifest"})
    assert ns["STORAGES"]["staticfiles"]["BACKEND"] == MANIFEST
    assert ns["STORAGES"]["default"]["BACKEND"].endswith("FileSystemStorage")


@pytest.fixture
def collected(tmp_path: Path) -> Iterator[Path]:
    source = tmp_path / "source" / "site"
    (source / "img").mkdir(parents=True)
    (source / "img" / "wave.png").write_bytes(PNG)
    (source / "site.css").write_text(
        'body { background: url("img/wave.png"); }\n@font-face { src: url("fonts/gone.woff2"); }\n'
    )
    (source / "data.json").write_text('{"tides": 2}\n')
    root = tmp_path / "static"
    with override_settings(
        DEBUG=False,
        STATIC_ROOT=str(root),
        STATIC_URL="/static/",
        STATICFILES_DIRS=[str(tmp_path / "source")],
        STATICFILES_FINDERS=["django.contrib.staticfiles.finders.FileSystemFinder"],
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": MANIFEST},
        },
    ):
        call_command("collectstatic", interactive=False, verbosity=0)
        yield root


def test_static_names_carry_the_content_hash(collected: Path) -> None:
    assert (collected / "staticfiles.json").is_file()
    css = static("site/site.css")
    assert re.fullmatch(r"/static/site/site\.[0-9a-f]{12}\.css", css)
    page = Template(
        "{% load static %}<link href=\"{% static 'site/site.css' %}\">"
        "<div data-image=\"{% static 'site/img/wave.png' %}\"></div>"
    ).render(Context())
    assert css in page
    assert re.search(r'data-image="/static/site/img/wave\.[0-9a-f]{12}\.png"', page)
    # The originals stay too: an address written by hand still answers.
    assert (collected / "site" / "data.json").is_file()
    assert (collected / "site" / "site.css").is_file()


def test_a_stylesheet_points_at_the_hashed_files(collected: Path) -> None:
    hashed = (collected / static("site/site.css").removeprefix("/static/")).read_text()
    assert re.search(r'url\("img/wave\.[0-9a-f]{12}\.png"\)', hashed)
    # A font the design does not ship is kept as written, and collectstatic did not fail.
    assert 'url("fonts/gone.woff2")' in hashed


def test_a_file_missing_from_the_manifest_gets_its_plain_name(
    collected: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="karni.storage"):
        assert static("site/not-collected.js") == "/static/site/not-collected.js"
    assert "not in the manifest" in caplog.text
