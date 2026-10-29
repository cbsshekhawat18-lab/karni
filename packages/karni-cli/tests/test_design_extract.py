"""``karni design extract``: the design's content in the ``karni load`` format, read with a map."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli.design.analyze import analyze
from karni_cli.design.extract import MapError, check_map, extract, read_map
from karni_cli.main import app

from .test_make import fails, ok

DESIGNS = Path(__file__).parent / "fixtures" / "designs"


def _map(name: str, *, decided: bool = True) -> dict[str, Any]:
    data = analyze(DESIGNS / name, "website").draft_map(str(DESIGNS / name))
    if decided:
        _keep_decisions(data)
    return data


def _keep_decisions(data: dict[str, Any]) -> None:
    for model in data["models"]:
        for source in model.get("sources", []):
            for rule in source["values"].values():
                if isinstance(rule, dict):
                    rule.pop("decide", None)


def _rows(content: dict[str, list[dict[str, Any]]], label: str) -> dict[str, dict[str, Any]]:
    return {row["slug"]: row for row in content[label]}


def test_extract_writes_load_content_with_image_paths_relative_to_the_file(tmp_path: Path) -> None:
    output = tmp_path / "content" / "site.json"
    result = extract(DESIGNS / "school", _map("school"), output)
    assert result.problems == []
    assert list(result.content) == ["website.Teacher", "website.Course"]
    teachers = _rows(result.content, "website.Teacher")
    assert list(teachers) == ["mia-chen", "omar-haddad", "lena-berg"]
    assert teachers["mia-chen"]["position"] == 1
    photo = teachers["mia-chen"]["photo"]
    assert (
        not photo.startswith("/")
        and (output.parent / photo).resolve() == (DESIGNS / "school" / "img" / "mia.jpg").resolve()
    )
    courses = _rows(result.content, "website.Course")
    assert list(courses) == ["pottery", "drawing", "weaving", "printing"]  # the list's order
    pottery = courses["pottery"]
    assert pottery["title"] == "Wheel pottery" and pottery["position"] == 1
    assert pottery["weeks"] == 12 and pottery["price"] == "240"
    assert pottery["start"] == "2026-09-01" and pottery["level"] == "Beginner"
    assert pottery["tagline"] == "Shape clay ==by hand=="
    assert pottery["topics"] == ["Centring and opening", "Pulling walls", "Trimming and glazing"]
    assert pottery["teacher"] == "mia-chen" and pottery["related"] == ["drawing", "printing"]
    assert pottery["description"].startswith("Twelve evenings on the potter's wheel")
    gallery = pottery["courseimage_set"]
    assert [row["position"] for row in gallery] == [1, 2, 3]
    assert gallery[0]["caption"] == "Bowls from the spring class"
    assert gallery[0]["image"].endswith("img/pottery-1.jpg")
    assert [c for c in courses if courses[c].get("featured")] == ["pottery", "drawing", "weaving"]
    assert "summary" not in courses["printing"]  # not on the home page: left out, not empty


def test_rows_from_several_pages_merge_by_key(tmp_path: Path) -> None:
    result = extract(DESIGNS / "practice", _map("practice"), tmp_path / "site.json")
    doctors = _rows(result.content, "website.Doctor")
    ada = doctors["ada-okoro"]
    # The home page's card and the doctor's page are one row.
    assert ada["specialty"] == "Family medicine" and ada["position"] == 1
    assert ada["languages"] == ["English", "Yoruba"]
    assert ada["hours"] == [["Monday", "8:00 to 13:00"], ["Tuesday", "8:00 to 18:00"]]
    assert ada["bio"].count("\n\n") == 1 and ada["treatments"] == ["check-up", "vaccination"]
    # Two pages give the photo a different alt text: the first source's is kept, and said.
    assert any("photo_alt keeps" in problem for problem in result.problems)
    treatments = _rows(result.content, "website.Treatment")
    assert treatments["check-up"]["price"] == "45" and treatments["check-up"]["duration"] == 30
    assert treatments["physiotherapy"]["new"] is True and treatments["check-up"]["new"] is False


def test_a_source_that_only_adds_values_waits_for_the_rows(tmp_path: Path) -> None:
    data = _map("school")
    course = next(m for m in data["models"] if m["name"] == "Course")
    adding = [s for s in course["sources"] if s.get("create") is False]
    assert adding  # the home page's teasers show rows the course pages create
    course["sources"] = adding + [s for s in course["sources"] if s.get("create", True)]
    rows = _rows(
        extract(DESIGNS / "school", data, tmp_path / "site.json").content, "website.Course"
    )
    assert rows["pottery"]["summary"] == "Throw bowls and cups on the wheel."
    assert rows["pottery"]["featured"] is True and len(rows) == 4


def test_nested_rows_point_at_their_parent_and_pages_set_their_placement(tmp_path: Path) -> None:
    bakery = extract(DESIGNS / "patisserie", _map("patisserie"), tmp_path / "a.json").content
    items = _rows(bakery, "website.MenuItem")
    assert len(items) == 8 and items["rye-bread"]["menu"] == "breads"
    assert items["rye-bread"]["vegan"] is True and items["lemon-tart"]["allergens"] == [
        "gluten",
        "eggs",
        "nuts",
    ]
    assert items["flat-white"]["allergens"] == [] and items["flat-white"]["menu"] == "drinks"
    studio = extract(DESIGNS / "studio", _map("studio"), tmp_path / "b.json").content
    slides = _rows(studio, "website.Slide")
    assert slides["home-2"]["page"] == "home" and slides["about-1"]["page"] == "about"
    assert slides["home-1"]["heading"] == "Houses that ==listen== to their site"
    assert "heading" not in slides["about-1"]  # the captions are only on the home page
    members = _rows(studio, "website.Member")
    assert members["ola-nord"]["founder"] is True and members["ola-nord"]["awards"] == [
        "Wood award 2021",
        "Town prize 2019",
    ]
    assert (
        members["ola-nord"]["role"] == "Founder, architect"
        and "founder" not in members["theo-brandt"]
    )
    projects = _rows(studio, "website.Project")
    assert projects["lakehouse"]["types"] == ["houses", "interiors"]
    assert projects["library"]["facts"] == [["Area", "1,200 m²"], ["Year", "2023"]]
    assert [row["position"] for row in projects["lakehouse"]["projectimage_set"]] == [1, 2]


def test_open_decisions_and_maps_extract_cannot_follow_are_refused(tmp_path: Path) -> None:
    with pytest.raises(MapError) as caught:
        check_map(_map("school", decided=False))
    assert len(caught.value.pending) == 2 and "decision(s) left" in str(caught.value)
    data = _map("school")
    course = next(m for m in data["models"] if m["name"] == "Course")
    course["sources"][0]["values"]["nickname"] = "h1"
    course["sources"][0]["values"]["teacher"]["to"] = "Tutor"
    course["sources"][1]["values"]["oops"] = {"select": "p[", "list": True}
    with pytest.raises(MapError) as caught:
        check_map(data, "map.json")
    message = str(caught.value)
    assert message.startswith("map.json: 4 problem(s):")
    for part in (
        "Course.nickname (Course source 1): not a field of Course",
        "relation to 'Tutor', not a model of the map",
        "Course.oops (Course source 2): not a field of Course",
        "'p[': cannot read",
    ):
        assert part in message, part
    bad = tmp_path / "map.json"
    bad.write_text("{nope")
    with pytest.raises(MapError, match="not valid JSON at line 1"):
        read_map(bad)
    with pytest.raises(MapError, match="no such file"):
        read_map(tmp_path / "missing.json")


def test_the_maps_marker_goes_around_highlighted_words(tmp_path: Path) -> None:
    data = _map("school")
    assert data["marker"] == "=="
    data["marker"] = "**"
    rows = _rows(
        extract(DESIGNS / "school", data, tmp_path / "site.json").content, "website.Course"
    )
    assert rows["pottery"]["tagline"] == "Shape clay **by hand**"
    assert rows["drawing"]["title"] == "Life drawing"  # a field without highlight has no marks
    data["marker"] = " "
    with pytest.raises(MapError, match='"marker" is the text around highlighted words'):
        check_map(data)


def test_a_field_renamed_in_the_map_is_read_under_its_new_name(tmp_path: Path) -> None:
    data = _map("school")
    course = next(m for m in data["models"] if m["name"] == "Course")
    course["fields"]["lede"] = course["fields"].pop("intro")
    detail = course["sources"][0]["values"]
    detail["lede"] = detail.pop("intro")
    rows = _rows(
        extract(DESIGNS / "school", data, tmp_path / "site.json").content, "website.Course"
    )
    assert rows["weaving"]["lede"].startswith("Six Saturdays") and "intro" not in rows["weaving"]


def test_numbered_labels_and_decoration_every_item_has(tmp_path: Path) -> None:
    design = tmp_path / "design"
    design.mkdir()
    cards = "".join(
        f'<article class="offer"><span class="offer-label">{n:02d} — {name}</span>'
        f"<h3>{name} work</h3><p>{text}</p>"
        f'<a class="more" href="#">Read more <span class="arrow">→</span></a>'
        f'<p class="offer-note">{note} <span class="arrow">→</span></p></article>'
        for n, (name, text, note) in enumerate(
            [
                ("Plan", "We measure the room.", "Takes a day"),
                ("Build", "We build it.", "Takes a week"),
                ("Care", "We visit.", "Every spring"),
            ],
            start=1,
        )
    )
    page = (
        "<!DOCTYPE html><html><head><title>Studio</title></head><body><header>Studio</header>"
        f"<main><h1>Offers</h1><div class='offers'>{cards}</div></main></body></html>"
    )
    (design / "index.html").write_text(page)
    analysis = analyze(design, "website")
    (offer,) = analysis.models
    names = {f.name: f for f in offer.columns}
    # "01 — Plan": the number is the item's place in the list, the label the value.
    assert names["label"].type == "str:80" and offer.field_named("position") is not None
    # "→" closes every note: the template's, not the content's.
    assert "highlight" not in names["note"].note
    data = analysis.draft_map(str(design))
    rows = extract(design, data, tmp_path / "site.json").content["website.Offer"]
    assert [row["label"] for row in rows] == ["Plan", "Build", "Care"]
    assert [row["note"] for row in rows] == ["Takes a day", "Takes a week", "Every spring"]
    assert [row["position"] for row in rows] == [1, 2, 3]


# --- the commands ----------------------------------------------------------------


def test_analyze_prints_the_proposal_and_writes_a_draft_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    design = str(DESIGNS / "school")
    result = ok("design", "analyze", design, "--map", "content/map.json")
    assert (
        "Course: 4 row(s)" in result.output
        and "wrote the draft map content/map.json" in result.output
    )
    written = json.loads((tmp_path / "content" / "map.json").read_text())
    # The design folder, relative to the map file.
    relative = os.path.relpath(Path(design).resolve(), (tmp_path / "content").resolve())
    assert written["design"] == Path(relative).as_posix() and written["app"] == "website"
    fails("design", "analyze", design, "--map", "content/map.json", match="C123")
    ok("design", "analyze", design, "--map", "content/map.json", "--force")
    as_json = json.loads(ok("design", "analyze", design, "--json", "--app", "school").output)
    assert as_json["app"] == "school" and as_json["commands"][0].endswith(
        "--app school --order position"
    )
    fails("design", "analyze", str(tmp_path / "nope"), match="C111")


def test_extract_refuses_open_decisions_then_writes_the_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    design = str(DESIGNS / "school")
    ok("design", "analyze", design, "--map", "map.json")
    fails("design", "extract", design, "--map", "map.json", match="C122")
    data = json.loads((tmp_path / "map.json").read_text())
    _keep_decisions(data)
    (tmp_path / "map.json").write_text(json.dumps(data))
    dry = ok("design", "extract", design, "--map", "map.json", "--dry-run")
    assert "--dry-run: nothing written" in dry.output and not (tmp_path / "content").exists()
    first = ok("design", "extract", design, "--map", "map.json")
    assert "website.Course   4 row(s) (8 child row(s))" in first.output
    content = json.loads((tmp_path / "content" / "site.json").read_text())
    assert content["website.Course"][0]["slug"] == "pottery"
    second = ok("design", "extract", design, "--map", "map.json")
    assert "The content is unchanged since the last extract." in second.output
    (tmp_path / "bad.json").write_text('{"models": [{"name": "X"}]}')
    fails("design", "extract", design, "--map", "bad.json", match="C121")


def test_the_app_defaults_to_the_one_the_import_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".karni").mkdir()
    (tmp_path / ".karni" / "design.json").write_text(json.dumps({"version": 1, "app": "site"}))
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "content").mkdir()
    monkeypatch.chdir(tmp_path / "content")
    data = json.loads(ok("design", "analyze", str(DESIGNS / "practice"), "--json").output)
    assert data["app"] == "site" and data["commands"][0].endswith("--app site --order position")


def test_the_highlight_import_design_editable_recorded_is_the_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".karni").mkdir()
    record = {"version": 1, "app": "website", "editable": {"highlight": {"tag": "em", "class": ""}}}
    (tmp_path / ".karni" / "design.json").write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    data = json.loads(ok("design", "analyze", str(DESIGNS / "school"), "--json").output)
    assert data["highlight"]["configured"] == "em"
    text = ok("design", "analyze", str(DESIGNS / "school")).output
    assert "already wrote to KARNI_SITE_HIGHLIGHT: render them with {{ value|highlight }}" in text


def test_the_design_commands_are_listed() -> None:
    result = CliRunner().invoke(app, ["design", "--help"])
    assert result.exit_code == 0 and "analyze" in result.output and "extract" in result.output
