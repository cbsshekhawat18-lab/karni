"""karni_site.tagref lists exactly the tags and filters the libraries register."""

from __future__ import annotations

import json

import pytest
from django.template import engines

from karni_site import tagref


def _library(name: str) -> object:
    return engines["django"].engine.template_libraries[name]


def test_every_registered_tag_and_filter_has_an_entry() -> None:
    library = _library("karni_site")
    registered = {(name, "tag") for name in library.tags} | {
        (name, "filter") for name in library.filters
    }
    listed = {(tag.name, tag.kind) for tag in tagref.TAGS}
    assert listed == registered


def test_karni_forms_tags_are_in_the_site_library_too() -> None:
    assert set(_library("karni_forms").tags) <= {tag.name for tag in tagref.TAGS}


@pytest.mark.parametrize(
    "written",
    ["image", "{% image %}", "{% image obj.photo alt='' %}", " IMAGE ", "image"],
)
def test_lookup_reads_a_tag_however_it_is_written(written: str) -> None:
    found = tagref.lookup(written)
    assert found is not None and found.name == "image"


def test_lookup_reads_filters_and_end_tags() -> None:
    assert tagref.lookup("|highlight:'em'") == tagref.lookup("highlight")
    assert tagref.lookup("{% endeditable %}") == tagref.lookup("editable")
    assert tagref.lookup("endfor") is None
    assert tagref.lookup("nope") is None


def test_karni_seo_says_how_it_finds_the_row() -> None:
    entry = tagref.lookup("karni_seo")
    assert entry is not None
    assert "get_absolute_url()" in entry.text and "class Karni: seo" in entry.text


def test_explain_prints_text_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert tagref.main(["--explain", "{% get_menu %}"]) == 0
    assert capsys.readouterr().out.startswith("get_menu  (a karni-site template tag")
    assert tagref.main(["--explain", "image", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["anchor"] == "seo-by-default"
    assert tagref.main(["--explain", "nope"]) == 1


def test_the_markdown_table_has_a_row_per_entry() -> None:
    rows = tagref.markdown()
    assert len(rows) == 2 + len(tagref.TAGS)
    assert rows[2].startswith("| `{% karni_seo %}` |")
    assert all(row.count(" | ") == 2 for row in rows[2:])
