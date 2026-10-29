"""A definition list with the same terms on every detail page: one typed field per term.

``<dl><dt>Duration</dt><dd>45 minutes</dd>...</dl>`` on each treatment page is
``duration:int``, ``price:decimal:10:2`` and ``visits:int``, read with
``"term"``. The list stays one ``json`` field when the terms differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from karni_cli.design.analyze import analyze, infer_type
from karni_cli.design.extract import check_map, extract

FACTS = {
    "cleaning": ("Cleaning", "45 minutes", "From $80", "1 visit"),
    "implants": ("Implants", "90 minutes", "From $1,900", "3 visits"),
    "whitening": ("Whitening", "60 minutes", "From $250", "2 visits"),
}


def _design(root: Path, terms: dict[str, tuple[str, ...]] | None = None) -> Path:
    """A home page listing three treatments, each with a detail page and its facts."""
    design = root / "design"
    (design / "treatments").mkdir(parents=True)
    cards = "".join(
        f'<article class="card"><h3>{title}</h3><a class="more" href="treatments/{slug}.html">'
        "Read more</a></article>"
        for slug, (title, *_rest) in FACTS.items()
    )
    (design / "index.html").write_text(
        f'<html lang="en"><body><main><section class="list">{cards}</section></main></body></html>'
    )
    for slug, (title, duration, price, visits) in FACTS.items():
        labels = (terms or {}).get(slug, ("Duration", "Price", "Visits"))
        rows = "".join(
            f"<dt>{label}</dt><dd>{value}</dd>"
            for label, value in zip(labels, (duration, price, visits), strict=True)
        )
        (design / "treatments" / f"{slug}.html").write_text(
            f'<html lang="en"><body><main><h1>{title}</h1><p class="lead">All about {title}.</p>'
            f'<dl class="facts">{rows}</dl></main></body></html>'
        )
    return design


def _treatment(data: dict[str, Any]) -> dict[str, Any]:
    return next(m for m in data["models"] if m["name"] == "Treatment")


def test_the_same_terms_on_every_page_are_one_typed_field_each(tmp_path: Path) -> None:
    design = _design(tmp_path)
    analysis = analyze(design, "website")
    model = next(m for m in analysis.models if m.name == "Treatment")
    types = {f.name: f.type for f in model.columns}
    assert types["duration"] == "int" and types["visits"] == "int"
    assert types["price"] == "decimal:10:2"
    assert "json" not in types.values()
    visits = next(f for f in model.columns if f.name == "visits")
    assert "visit{{ value|pluralize }}" in visits.note

    data = analysis.draft_map(str(design))
    detail = next(s for s in _treatment(data)["sources"] if "pages" in s)
    assert detail["values"]["duration"] == {"select": "dl.facts", "term": "Duration"}
    assert detail["values"]["price"] == {"select": "dl.facts", "term": "Price"}
    check_map(data)

    rows = {
        row["slug"]: row
        for row in extract(design, data, tmp_path / "site.json").content["website.Treatment"]
    }
    assert rows["cleaning"]["duration"] == 45 and rows["cleaning"]["visits"] == 1
    assert rows["implants"]["price"] == "1900" and rows["implants"]["visits"] == 3


def test_terms_that_differ_between_pages_stay_one_json_field(tmp_path: Path) -> None:
    design = _design(tmp_path, {"implants": ("Duration", "Cost", "Sessions")})
    model = next(m for m in analyze(design, "website").models if m.name == "Treatment")
    types = {f.name: f.type for f in model.columns}
    assert "json" in types.values()
    assert "duration" not in types and "visits" not in types


def test_term_matches_ignore_case_and_spaces(tmp_path: Path) -> None:
    design = _design(tmp_path)
    data = analyze(design, "website").draft_map(str(design))
    detail = next(s for s in _treatment(data)["sources"] if "pages" in s)
    detail["values"]["duration"] = {"select": "dl.facts", "term": "  duration "}
    detail["values"]["visits"] = {"select": "dl.facts", "term": "No such term"}
    rows = {
        row["slug"]: row
        for row in extract(design, data, tmp_path / "site.json").content["website.Treatment"]
    }
    assert rows["whitening"]["duration"] == 60
    assert "visits" not in rows["whitening"]  # a term the list lacks reads nothing


def test_one_unit_written_singular_and_plural_is_a_number() -> None:
    assert infer_type("text", ["1 visit", "2 visits", "6 visits"])[0] == "int"
    assert 'stor{{ value|pluralize:"y,ies" }}' in infer_type("text", ["1 story", "3 stories"])[1]
    assert infer_type("text", ["12 weeks", "8 weeks"]) == (
        "int",
        "the text around the number ('weeks') stays in the template",
    )
    assert infer_type("text", ["1 day", "2 weeks"])[0].startswith("str")
