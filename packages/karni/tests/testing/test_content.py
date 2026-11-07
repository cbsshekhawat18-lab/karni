"""``karni.testing.load_content``: a test loads content, its path read from the project root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import override_settings

from karni.testing import load_content
from karni.transfer.loading import LoadError
from tests.contentapp.models import Service

pytestmark = pytest.mark.django_db

CONTENT = {"contentapp.Service": [{"slug": "design", "title": "Design", "image": ""}]}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root holding content/site.json, and a working directory elsewhere."""
    root = tmp_path / "project"
    (root / "content").mkdir(parents=True)
    (root / "content" / "site.json").write_text(json.dumps(CONTENT), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # pytest run from another folder: the path still resolves
    return root


def test_a_relative_path_is_read_from_the_project_root(project: Path) -> None:
    with override_settings(BASE_DIR=project, MEDIA_ROOT=str(project / "media")):
        report = load_content("content/site.json")
    assert Service.objects.get().title == "Design"
    assert report.models["contentapp.Service"].created == 1
    # The default is the file karni design extract writes.
    with override_settings(BASE_DIR=project, MEDIA_ROOT=str(project / "media")):
        again = load_content()
    assert again.models["contentapp.Service"].unchanged == 1


def test_a_missing_file_names_the_path_unless_it_may_be_missing(tmp_path: Path) -> None:
    with override_settings(BASE_DIR=tmp_path):
        assert load_content("content/site.json", missing_ok=True) is None
        with pytest.raises(LoadError) as raised:
            load_content("content/site.json")
    assert raised.value.code == "E804"
    assert str(tmp_path / "content" / "site.json") in str(raised.value)
