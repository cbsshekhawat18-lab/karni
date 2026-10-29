"""``karni design analyze``: selectors, values, the scan, and models from four designs that differ.

* practice: a clinic in plain CSS, doctor cards on the home page linking to a
  folder of doctor pages, treatments with prices and durations, a list of
  treatments on each doctor page (a decision).
* patisserie: a bakery in Bootstrap markup, menu sections holding cards with
  prices, allergens and a "Vegan" badge, three of the cards again on the home
  page (a decision), testimonials that stay page copy.
* school: courses in a folder (BEM classes), a gallery with captions on each
  course page, the teacher linked by an anchor, a hand-picked "You may also
  like" list (a decision), dates, prices and lengths in weeks.
* studio: a slider whose pictures and captions are two lists, the same
  slider on another page, filter buttons whose keys the projects' data
  attribute names, projects with a gallery and facts, a founder's card styled
  on its own above the members' cards (a decision).
"""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from karni_cli.design import values
from karni_cli.design.analyze import Analysis, Model, analyze, infer_type, parse_value
from karni_cli.design.parse import parse
from karni_cli.design.scan import scan
from karni_cli.design.select import (
    SelectorError,
    Target,
    parse_place,
    parse_selector,
    select,
    write_selector,
)

DESIGNS = Path(__file__).parent / "fixtures" / "designs"


def _analysis(name: str) -> Analysis:
    return analyze(DESIGNS / name, "website", label=name)


def _model(analysis: Analysis, name: str) -> Model:
    return next(m for m in analysis.models if m.name == name)


def _types(model: Model) -> dict[str, str]:
    return {f.name: f.type + ("?" if f.optional else "") for f in model.columns}


# --- selectors ------------------------------------------------------------------


SNIPPET = (
    '<div id="a" class="x"><section class="s"><h2>T</h2><p class="p">1</p><p>2</p>'
    '<img src="i.png" alt="A"></section><ul><li data-k="a b">x</li><li>y</li></ul></div>'
)


def test_selectors_are_scoped_to_their_root() -> None:
    doc = parse(SNIPPET)
    root = doc.root

    def texts(selector: str, under: object = root) -> list[str]:
        return [n.plain_text(SNIPPET) for n in select(under, selector, SNIPPET)]  # type: ignore[arg-type]

    assert texts("h2") == ["T"] and texts(".s > p") == ["1", "2"]
    assert texts("p:nth-of-type(2)") == ["2"] and texts("p.p") == ["1"]
    assert texts("[data-k]") == ["x"] and texts('[data-k~="b"]') == ["x"]
    assert texts("li:last-of-type") == ["y"] and texts("#a section h2") == ["T"]
    assert texts("h1, h2, li:first-of-type") == ["T", "x"]
    assert texts("section:has(img) h2") == ["T"] and texts("div:has(.missing) h2") == []
    assert [n.tag for n in select(root, "> div", SNIPPET)] == ["div"]
    section = select(root, "section", SNIPPET)[0]
    # An ancestor above the root does not count: the map's places are relative.
    assert texts("div h2", section) == [] and texts("> h2", section) == ["T"]
    for bad in ("", "a >", ":has(a", "p[", "1abc"):
        with pytest.raises(SelectorError):
            parse_selector(bad)


def test_places_name_an_attribute_or_the_root_itself() -> None:
    doc = parse(SNIPPET)
    li = select(doc.root, "li", SNIPPET)[0]
    image = parse_place("img@src")
    assert image.attribute == "src" and str(image) == "img@src"
    assert [n.tag for n in parse_place(":scope").nodes(li, SNIPPET)] == ["li"]
    own = parse_place("@data-k")
    assert own.selector is None and own.nodes(li, SNIPPET)[0].attr(SNIPPET, "data-k") == "a b"
    with pytest.raises(SelectorError, match="nothing after @"):
        parse_place("img@")


def test_the_selector_writer_finds_the_shortest_exact_selector() -> None:
    source = (DESIGNS / "studio" / "index.html").read_text()
    doc = parse(source)
    projects = select(doc.root, "article.project", source)
    assert write_selector([Target(doc.root, tuple(projects), source)]) == "article.project"
    # The project's own picture, not the gallery's: a child of the item.
    own = [Target(p, (select(p, "img", source)[0],), source) for p in projects]
    assert write_selector(own) == "> img"
    gallery = [
        Target(p, tuple(select(p, ".project__gallery img", source)), source) for p in projects
    ]
    assert write_selector(gallery) == "div.project__gallery > img"
    # One element is an h1 on the first slide and an h2 on the others.
    captions = select(doc.root, "div.hero__caption", source)
    headings = [Target(c, (select(c, "h1, h2", source)[0],), source) for c in captions]
    assert write_selector(headings) == "h1, h2"
    # A section anchor is tried before a path of positions.
    title = select(doc.root, "#work h2", source)
    assert write_selector([Target(doc.root, tuple(title), source)], ["section:has(.filters)"]) in (
        "section.work > h2",
        "section:has(.filters) h2",
    )


# --- values ---------------------------------------------------------------------


def test_numbers_prices_and_dates_are_read_only_when_the_whole_text_is_one() -> None:
    assert values.price("€4.50") == (Decimal("4.50"), "EUR", "|")
    assert values.price("From $12") == (Decimal(12), "USD", "From |")
    assert values.price("4,50 €")[0] == Decimal("4.50")  # type: ignore[index]
    assert values.price("1,200 USD")[0] == Decimal(1200)  # type: ignore[index]
    assert values.price("12 weeks") is None
    assert values.number("12 weeks") == (Decimal(12), "", " weeks")
    assert values.number("Twelve weeks") is None
    assert str(values.date("14 March 2026")) == "2026-03-14"
    assert str(values.date("March 14, 2026")) == "2026-03-14"
    assert str(values.date("Tue 3 March 2026")) == "2026-03-03"
    assert str(values.date("2026-09-01")) == "2026-09-01"
    assert values.date("1 September") is None and values.date("soon") is None
    assert infer_type("text", ["€4.50", "€6"])[0] == "decimal:10:2"
    assert infer_type("text", ["12 weeks", "8 weeks"]) == (
        "int",
        "the text around the number ('weeks') stays in the template",
    )
    assert infer_type("text", ["1 September 2026", "8 October 2026"])[0] == "date"
    assert infer_type("text", ["Short", "Also short"])[0] == "str:80"
    assert infer_type("text", ["a\nb"])[0] == "text"
    assert parse_value("text", "int", "12 weeks") == 12
    assert parse_value("text", "decimal:10:2", "€4.50") == "4.50"
    assert parse_value("text", "date", "8 September 2026") == "2026-09-08"
    assert parse_value("text", "str:80", "") is None


def test_thousands_separators_and_the_pages_decimal_mark() -> None:
    # Without a language a number reads the English way: a lone comma before three
    # digits groups thousands, a point is the decimal mark.
    assert values.number("4,000")[0] == Decimal(4000)  # type: ignore[index]
    assert values.number("12,500 patients") == (Decimal(12500), "", " patients")
    assert values.number("1,234,567")[0] == Decimal(1234567)  # type: ignore[index]
    assert values.number("1 234")[0] == Decimal(1234)  # type: ignore[index]
    assert values.number("1\u202f234")[0] == Decimal(1234)  # type: ignore[index]
    assert values.number("1'234'567")[0] == Decimal(1234567)  # type: ignore[index]
    assert values.number("4.9")[0] == Decimal("4.9")  # type: ignore[index]
    assert values.number("1,234.5")[0] == Decimal("1234.5")  # type: ignore[index]
    assert values.number("1.234,5")[0] == Decimal("1234.5")  # type: ignore[index]
    # A page in a language with a decimal comma: "4.000" groups, "4,5" is four and a half.
    comma = values.decimal_mark("de-DE")
    assert comma == "," and values.decimal_mark("de-CH") == "." and values.decimal_mark("") is None
    assert values.number("4.000", comma)[0] == Decimal(4000)  # type: ignore[index]
    assert values.number("4,5", comma)[0] == Decimal("4.5")  # type: ignore[index]
    assert values.number("1.234.567,89", comma)[0] == Decimal("1234567.89")  # type: ignore[index]
    assert parse_value("text", "int", "4,000") == 4000
    assert parse_value("text", "int", "4.000", ",") == 4000
    assert parse_value("text", "decimal:10:2", "1.234,5", ",") == "1234.5"
    assert infer_type("text", ["4,000", "25", "1,200"])[0] == "int"
    assert infer_type("text", ["4.000", "25"], ",")[0] == "int"


def test_names_and_keys_come_from_the_markups_words() -> None:
    assert values.words("team-card__photoWide") == ["team", "card", "photo", "wide"]
    assert values.snake("Key services") == "key_services"
    assert values.pascal("menu section") == "MenuSection"
    assert values.singular("categories") == "category" and values.singular("classes") == "class"
    assert values.plural("category") == "categories" and values.plural("related") == "related"
    assert values.slugify("Café & Crème — été") == "cafe-creme-ete"
    assert len(values.slugify("word " * 30)) <= 50
    utility = ("col-md-4", "py-5", "text-muted", "md:w-1/2", "is-active", "d-flex")
    assert all(values.is_utility_class(token) for token in utility)
    assert not any(values.is_utility_class(t) for t in ("card-title", "project-kicker", "lede"))


def test_text_keeps_highlighted_words_between_the_sites_marker() -> None:
    source = (
        '<h2>Custom homes, <span class="accent">crafted for place</span></h2>'
        '<a>Learn more <span class="arrow">→</span></a><p>A<br>B == C *</p>'
    )
    doc = parse(source)
    heading, link, paragraph = (select(doc.root, tag, source)[0] for tag in ("h2", "a", "p"))
    # KARNI_SITE_HIGHLIGHT's default marker: a client types the same in an editable block.
    assert values.HIGHLIGHT_MARKER == "=="
    assert values.text_of(heading, source) == (
        "Custom homes, ==crafted for place==",
        ["span.accent"],
    )
    assert values.text_of(link, source, drop=["span.arrow"])[0] == "Learn more"
    # A marker the text holds is escaped with a backslash, as karni_site reads it.
    assert values.text_of(paragraph, source)[0] == "A\nB \\== C *"
    assert values.text_of(heading, source, highlight=False)[0] == "Custom homes, crafted for place"
    assert values.text_of(paragraph, source, highlight=False)[0] == "A\nB == C *"
    assert values.text_of(heading, source, marker="**")[0] == "Custom homes, **crafted for place**"
    assert values.unmark("a \\== b ==c==") == "a == b c"


# --- the scan -------------------------------------------------------------------


def test_the_scan_finds_items_their_values_and_the_lists_inside_them() -> None:
    source = (DESIGNS / "studio" / "index.html").read_text()
    found = scan(parse(source).body_or_root(), source)
    by_step = {c.step: c for c in found.collections}
    projects = by_step["article.project"]
    assert len(projects.items) == 4
    first = projects.items[0]
    keys = {slot.key: slot for slot in first.slots}
    assert keys[((), "data", "data-types")].value == "houses interiors"
    assert keys[((), "id", "id")].value == "p-lakehouse"
    facts = keys[(("div.project__more", "dl.project__facts"), "pairs", "")]
    assert facts.pairs == (("Area", "140 m²"), ("Year", "2024"))
    text = keys[(("div.project__more", "p"), "text", "")]
    assert text.run and text.value.count("\n\n") == 1 and len(text.elements) == 2
    # Every project's gallery is a list, the one with a single picture too.
    galleries = [c for item in projects.items for c in item.collections]
    assert [len(c.items) for c in galleries] == [2, 1, 2, 1]
    # The first slide's is-shown class is state: the three pictures are one list.
    assert len(by_step["img"].items) == 3


def test_siblings_with_their_own_classes_are_values_not_a_list() -> None:
    source = (DESIGNS / "practice" / "treatments.html").read_text()
    found = scan(parse(source).body_or_root(), source)
    treatments = next(c for c in found.collections if c.step == "div.treatment")
    assert len(treatments.items) == 4 and not treatments.items[0].collections
    paths = {slot.path for slot in treatments.items[0].slots if slot.kind == "text"}
    assert ("p.treatment__price",) in paths and ("p.treatment__duration",) in paths


# --- the analysis ---------------------------------------------------------------


def test_a_clinic_with_doctor_cards_and_doctor_pages() -> None:
    analysis = _analysis("practice")
    assert [m.name for m in analysis.models] == ["Doctor", "Treatment"]
    doctor = _model(analysis, "Doctor")
    assert doctor.family is not None and len(doctor.family.pages) == 3
    assert doctor.rows == 3  # the home page's cards are the same rows as the doctor pages
    types = _types(doctor)
    assert types["title"] == "str:80" and types["slug"] == "slug:title"
    assert types["photo"] == "image" and types["bio"] == "text"
    assert types["languages"] == "json" and types["hours"] == "json"
    assert types["description"].startswith("str:")
    assert types["treatments"] == "m2m:Treatment?"
    assert {e.key for e in doctor.entities} == {"ada-okoro", "ben-lim", "cara-diaz"}
    treatment = _model(analysis, "Treatment")
    assert _types(treatment) == {
        "title": "str:80",
        "slug": "slug:title",
        "text": "str:120",
        "price": "decimal:10:2",
        "duration": "int",
        "new": "bool",
        "position": "int",
    }
    assert {e.key for e in treatment.entities} == {
        "check-up",
        "vaccination",
        "physiotherapy",
        "travel-advice",
    }
    price = next(f for f in treatment.fields if f.name == "price")
    assert "EUR" in price.note
    (decision,) = analysis.decisions
    assert (decision.model, decision.field) == ("Doctor", "treatments")
    assert "hand-picked" in decision.question and "nothing derives" in decision.evidence


def test_a_bakery_menu_in_bootstrap_markup() -> None:
    analysis = _analysis("patisserie")
    assert [m.name for m in analysis.models] == ["Menu", "MenuItem"]
    menu, item = (_model(analysis, name) for name in ("Menu", "MenuItem"))
    assert [e.key for e in menu.entities] == ["breads", "cakes", "drinks"]
    assert item.rows == 8
    types = _types(item)
    assert types["menu"] == "fk:Menu?"  # each card sits in one menu section
    assert types["price"] == "decimal:10:2" and types["vegan"] == "bool"
    assert types["allergens"] == "json" and types["image"] == "image"
    # Utility classes never name a field.
    assert not {"col", "mb", "card", "fw", "bold", "list_inline"} & set(types)
    (decision,) = analysis.decisions
    assert (decision.model, decision.field) == ("MenuItem", "featured")
    assert "3 of 8" in decision.evidence
    assert [(c.where, c.step) for c in analysis.page_copy] == [
        ("index.html", "blockquote.blockquote")
    ]


def test_a_school_with_courses_a_gallery_a_teacher_and_a_hand_picked_list() -> None:
    analysis = _analysis("school")
    assert [m.name for m in analysis.models] == ["Teacher", "Course", "CourseImage"]
    course = _model(analysis, "Course")
    assert course.family is not None and course.family.folder == "courses"
    types = _types(course)
    assert types["weeks"] == "int" and types["start"] == "date"
    assert types["price"] == "decimal:10:2" and types["topics"] == "json"
    assert types["teacher"] == "fk:Teacher?"
    # A hand-picked list of the same model is one-way: "self" would be symmetrical.
    assert types["related"] == "m2m:website.Course?"
    tagline = next(f for f in course.fields if f.name == "tagline")
    assert tagline.highlight == ["em"] and "{{ value|highlight }}" in tagline.note
    # One markup for the site: the advice proposes KARNI_SITE_HIGHLIGHT for it.
    assert analysis.highlight is not None
    assert analysis.highlight.setting() == {"marker": "==", "tag": "em", "class": ""}
    assert analysis.highlight.uses == {"em": ["Course.tagline"]}
    assert "teacher_2" not in types  # "Taught by Mia Chen" is the relation's text
    image = _model(analysis, "CourseImage")
    assert image.parent is course and image.accessor == "courseimage_set"
    assert _types(image) == {
        "course": "fk:Course",
        "image": "image",
        "image_alt": "str:80",
        "caption": "str:80",
        "position": "int",
    }
    assert {(d.model, d.field) for d in analysis.decisions} == {
        ("Course", "related"),
        ("Course", "featured"),
    }
    commands = analysis.commands()
    assert [c.split()[3] for c in commands] == ["Teacher", "Course", "CourseImage"]
    assert commands[2].endswith("--order position --key position")
    assert "related" not in commands[1]  # a decision is not in the command until answered
    assert commands[1].startswith("karni make model Course title:str:80 slug:slug:title ")


def test_a_studio_with_sliders_filters_and_galleries() -> None:
    analysis = _analysis("studio")
    names = [m.name for m in analysis.models]
    assert names == ["Slide", "Member", "ProjectType", "Project", "ProjectImage"]
    slide = _model(analysis, "Slide")
    assert slide.kind == "pages" and slide.rows == 5
    types = _types(slide)
    assert types["page"] == "choice:home|about"
    # The captions are a second list in the slider's block: the same rows.
    assert types["heading"] == "str:80?" and types["caption"] == "str:80"
    assert any("item by item" in note for note in slide.notes)
    assert [e.key for e in slide.entities][:3] == ["home-1", "home-2", "home-3"]
    project = _model(analysis, "Project")
    types = _types(project)
    # data-types names the filter buttons' data-filter keys: a relation, not tags.
    assert types["types"] == "m2m:ProjectType?" and types["facts"] == "json"
    assert {e.key for e in project.entities} == {"lakehouse", "loft", "library", "kiosk"}
    assert _model(analysis, "ProjectImage").rows == 6
    assert not analysis.page_copy
    # A founder's card styled on its own, with a member's values and more: one more row?
    member = _model(analysis, "Member")
    assert member.rows == 4 and {e.key for e in member.entities} >= {"ola-nord", "ines-aalto"}
    types = _types(member)
    assert types["founder"] == "bool" and types["awards"] == "json" and types["role"] == "str:80"
    (decision,) = analysis.decisions
    assert (decision.model, decision.field) == ("Member", "founder")
    assert "div.founder__card" in decision.question
    assert "founder:bool awards:json" in decision.choices[0]
    founder_only = {f.name for f in member.columns if f.decide}
    assert founder_only == {"founder", "awards", "image_alt", "text"}
    assert all(name not in analysis.commands()[1] for name in founder_only)


_LAYOUT = """<!doctype html><html lang="{lang}"><head><title>{title}</title>
<meta name="description" content="{title} page."></head><body>
<header class="top"><a href="index.html">Home</a> <a href="about.html">About</a></header>
<main>{main}</main>
<footer class="bottom"><p>Made by hand.</p></footer></body></html>"""


def _site(tmp_path: Path, main: str, lang: str = "en") -> Path:
    design = tmp_path / "design"
    design.mkdir()
    (design / "img").mkdir()
    for index in range(1, 4):
        (design / "img" / f"p{index}.jpg").write_bytes(b"\xff\xd8\xff")
    (design / "index.html").write_text(_LAYOUT.format(lang=lang, title="Home", main=main))
    about = "<section class='story'><h1>About us</h1><p>A small team.</p></section>"
    (design / "about.html").write_text(_LAYOUT.format(lang=lang, title="About", main=about))
    return design


SLIDES = "".join(
    f'<div class="slide"><img src="img/p{i}.jpg" alt="Picture {i}"><h2>Heading {i}</h2>'
    f"<p>Line {i} of the slider.</p></div>"
    for i in range(1, 4)
)


@pytest.mark.parametrize(
    ("main", "figure"),
    [
        # A clinic: the slider and the figures in sections of their own.
        (
            f'<section class="hero">{SLIDES}</section><section class="numbers">'
            + "".join(
                f'<div class="number"><strong>{n}</strong><span>{label}</span></div>'
                for n, label in (("25", "years in town"), ("4,000", "patients"), ("4.9", "rating"))
            )
            + "</section>",
            "div.number",
        ),
        # A bakery in plain divs, no sections at all: only the figures say what they are.
        (
            f'<div class="carousel">{SLIDES}</div><div class="facts">'
            + "".join(
                f'<p class="fact"><b>{n}</b> <i>{label}</i></p>'
                for n, label in (("12", "ovens"), ("98%", "local flour"), ("10k+", "loaves a week"))
            )
            + "</div>",
            "p.fact",
        ),
    ],
)
def test_a_row_of_figures_is_page_copy_not_a_model(tmp_path: Path, main: str, figure: str) -> None:
    analysis = analyze(_site(tmp_path, main), "website")
    (slide,) = analysis.models
    assert set(_types(slide)) == {"title", "slug", "image", "image_alt", "text", "position"}
    assert not any("item by item" in note for note in slide.notes)
    copy = next(c for c in analysis.page_copy if c.step == figure)
    assert copy.items == 3 and copy.reason.startswith("figures")


def test_a_list_with_pictures_or_inner_lists_is_not_figures(tmp_path: Path) -> None:
    # A portfolio's projects: a year and a title, but a picture each: rows.
    projects = "".join(
        f'<article class="project"><img src="img/p{i}.jpg" alt="Project {i}">'
        f"<span class='year'>202{i}</span><h3>Project {i}</h3></article>"
        for i in range(1, 4)
    )
    # Price plans: a price and a name, and a list of what each includes: rows too.
    plans = "".join(
        f'<div class="plan"><h3>Plan {name}</h3><p class="price">€{price}</p>'
        f"<ul><li>{name} feature one</li><li>{name} feature two</li></ul></div>"
        for name, price in (("Basic", 9), ("Plus", 19), ("Team", 49))
    )
    analysis = analyze(
        _site(tmp_path, f"<section class='work'>{projects}</section>"
              f"<section class='pricing'>{plans}</section>"),
        "website",
    )  # fmt: skip
    assert {m.name for m in analysis.models} >= {"Project", "Plan"}
    assert not any(c.reason.startswith("figures") for c in analysis.page_copy)


def test_a_sliders_captions_in_the_same_section_are_still_its_rows(tmp_path: Path) -> None:
    pictures = "".join(f'<img class="shot" src="img/p{i}.jpg" alt="Shot {i}">' for i in (1, 2, 3))
    captions = "".join(f'<p class="caption">Caption number {i}</p>' for i in (1, 2, 3))
    main = (
        f'<section class="gallery"><div class="shots">{pictures}</div>'
        f'<div class="captions">{captions}</div></section>'
    )
    analysis = analyze(_site(tmp_path, main), "website")
    (model,) = analysis.models
    assert any("item by item" in note for note in model.notes)
    assert "Caption number 1" in {f.example for f in model.columns}


def test_figures_on_a_page_in_german_read_its_numbers(tmp_path: Path) -> None:
    cards = "".join(
        f'<article class="haus"><img src="img/p{i}.jpg" alt="Haus {i}"><h3>Haus {i}</h3>'
        f"<p class='flaeche'>{area} m²</p></article>"
        for i, area in ((1, "1.250"), (2, "980"), (3, "2.400"))
    )
    analysis = analyze(_site(tmp_path, f"<section>{cards}</section>", lang="de"), "website")
    (model,) = analysis.models
    assert _types(model)["flaeche"] == "int"


def test_a_detail_page_that_lists_the_rows_pointing_back_holds_no_field(tmp_path: Path) -> None:
    design = tmp_path / "design"
    (design / "venues").mkdir(parents=True)
    (design / "img").mkdir()
    page = (
        "<!doctype html><html><head><title>{0}</title></head><body><main>{1}</main></body></html>"
    )
    venues = (
        ("studio", "The studio", "e1"),
        ("hall", "The hall", "e2"),
        ("yard", "The yard", "e3"),
    )
    for key, title, event in venues:
        (design / "img" / f"{key}.jpg").write_bytes(b"\xff\xd8\xff")
        body = (
            f'<h1>{title}</h1><img class="photo" src="../img/{key}.jpg" alt="{title}">'
            f"<p class='about'>All about {title.lower()}, a place to meet.</p>"
            f'<section class="coming"><h2>Coming up</h2><ul><li>'
            f'<a href="../events.html#{event}">Event at {key}</a></li></ul></section>'
        )
        (design / "venues" / f"{key}.html").write_text(page.format(title, body))
    cards = "".join(
        f'<a class="venue" href="venues/{key}.html"><img src="img/{key}.jpg" alt="{title}">'
        f"<h3>{title}</h3></a>"
        for key, title, _ in venues
    )
    (design / "index.html").write_text(page.format("Venues", cards))
    events = "".join(
        f'<article class="event" id="{event}"><h3>Event at {key}</h3>'
        f'<time datetime="2026-0{n}-01">1 {month} 2026</time><span class="where">{key}</span></article>'
        for n, ((key, _, event), month) in enumerate(zip(venues, ("May", "June", "July")), start=5)
    )
    (design / "events.html").write_text(page.format("Events", events))
    analysis = analyze(design, "website")
    event = _model(analysis, "Event")
    assert _types(event)["venue"] == "fk:Venue?"
    venue = _model(analysis, "Venue")
    assert not any(f.target is event for f in venue.fields if f.kind == "relation")
    assert any("loop over venue.event_set.all" in note for note in venue.notes)


def test_names_come_from_the_markup_not_from_a_list(tmp_path: Path) -> None:
    design = tmp_path / "design"
    shutil.copytree(DESIGNS / "school", design)
    (design / "courses").rename(design / "workshops")
    for page in design.rglob("*.html"):
        text = page.read_text()
        for old, new in (("courses/", "workshops/"), ("teacher", "mentor")):
            text = text.replace(old, new)
        page.write_text(text)
    (design / "teachers.html").rename(design / "mentors.html")
    for page in design.rglob("*.html"):
        page.write_text(page.read_text().replace("teachers.html", "mentors.html"))
    names = [m.name for m in analyze(design, "website").models]
    assert names == ["Mentor", "Workshop", "WorkshopImage"]


def test_the_analysis_as_json_is_stable_and_holds_the_draft_map() -> None:
    first = json.dumps(_analysis("school").to_dict(), sort_keys=False)
    second = json.dumps(_analysis("school").to_dict(), sort_keys=False)
    assert first == second
    data = json.loads(first)
    assert list(data) == [
        "version",
        "design",
        "app",
        "pages",
        "models",
        "decisions",
        "page_copy",
        "commands",
        "highlight",
        "notes",
        "map",
    ]
    assert data["highlight"]["setting"] == {"marker": "==", "tag": "em", "class": ""}
    assert data["map"]["marker"] == "=="
    course = next(m for m in data["models"] if m["name"] == "Course")
    assert course["detail_pages"][0].startswith("courses/")
    related = next(f for f in course["fields"] if f["name"] == "related")
    assert related["decide"] and related["to"] == "Course"
    mapped = next(m for m in data["map"]["models"] if m["name"] == "Course")
    detail = mapped["sources"][0]
    assert detail["key"] == {"from": "page"} and detail["values"]["title"] == "h1.course__title"
    assert "start" not in detail["values"]  # the course pages do not show it, the list does
    listing = next(s for s in mapped["sources"] if s.get("page") == "courses.html")
    assert listing["key"]["from"] == "link" and listing["position"] is True
    assert listing["values"]["start"] == "time.course-list__start@datetime"
    child = next(m for m in data["map"]["models"] if m["name"] == "CourseImage")
    assert child["parent"] == "Course" and child["key"] == "position"
    assert detail["values"]["courseimage_set"]["rows"]["caption"] == "figcaption"


def test_highlighted_words_get_one_setting_for_the_whole_site() -> None:
    text = _analysis("school").render()
    assert "Highlighted words (kept as ==words==, one convention):" in text
    assert (
        'Course.tagline set words apart with <em>. Set `KARNI_SITE_HIGHLIGHT = {"marker": "==", '
        '"tag": "em", "class": ""}` in config/settings.py: then {{ value|highlight }} renders '
        "them, and a client types ==words== for the same in an editable block."
    ) in text
    # The markup karni import design --editable wrote: nothing to set, the filter needs no
    # argument for the fields that use it, and names its own markup for any other.
    told = analyze(DESIGNS / "school", "website", highlight="em").render()
    assert "the markup karni import design --editable already wrote" in told
    other = analyze(DESIGNS / "school", "website", highlight="span.accent")
    tagline = next(f for f in _model(other, "Course").fields if f.name == "tagline")
    assert 'render with {{ value|highlight:"em" }}' in tagline.note
    assert 'KARNI_SITE_HIGHLIGHT renders <span class="accent">' in other.render()
    assert _analysis("practice").highlight is None


def test_the_human_report_lists_models_decisions_and_commands() -> None:
    text = _analysis("patisserie").render()
    assert text.startswith("Design patisserie: 3 page(s), 2 model(s) proposed from the markup.")
    for line in (
        "MenuItem: 8 row(s), on index.html, menu.html",
        "Decide (1), the markup cannot tell:",
        "Left in the templates (page copy, not models):",
        "Commands (models others point at come first):",
        "  karni make model Menu title:str:80 slug:slug:title",
    ):
        assert line in text, line
