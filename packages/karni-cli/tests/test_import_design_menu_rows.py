"""karni import design --editable --map: a menu of a model's detail pages lists its rows.

A footer list whose links are exactly the treatments' detail pages, each by its
title, is seeded as the Treatment rows (``data-karni-children-from``), so a
treatment the client adds appears in it. A list that leaves one out, adds
another page or names a page otherwise keeps the design's links.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from karni_cli.design.analyze import analyze
from karni_cli.design.site import plan

TREATMENTS = {"cleaning": "Cleaning", "implants": "Implants", "whitening": "Whitening"}
NAV = (
    '<ul class="nav"><li><a href="index.html">Home</a></li>'
    '<li><a href="contact.html">Contact</a></li></ul>'
)


def _links(pairs: list[tuple[str, str]]) -> str:
    return "".join(f'<li><a href="{href}">{text}</a></li>' for href, text in pairs)


def _design(root: Path, footer: list[tuple[str, str]], header: str = NAV) -> Path:
    design = root / "design"
    (design / "treatments").mkdir(parents=True)

    def layout(up: str = "") -> str:
        """The shared layout, its links written from a page ``up`` folders below the root."""
        menu = _links([(up + href, text) for href, text in footer])
        nav = header.replace('href="', 'href="' + up)
        return (
            '<html lang="en"><head><title>{title}</title></head><body>'
            f"<header><nav>{nav}</nav></header><main>{{main}}</main>"
            f'<footer><ul class="footer-links">{menu}</ul></footer></body></html>'
        )

    cards = "".join(
        f'<article class="card"><h3>{title}</h3>'
        f'<a class="more" href="treatments/{slug}.html">Read more</a></article>'
        for slug, title in TREATMENTS.items()
    )
    (design / "index.html").write_text(
        layout().format(title="Home", main=f'<section class="list">{cards}</section>')
    )
    (design / "contact.html").write_text(
        layout().format(title="Contact", main="<h1>Contact</h1><p>Write to us.</p>")
    )
    for slug, title in TREATMENTS.items():
        main = f'<h1>{title}</h1><p class="lead">All about {title.lower()} here.</p>'
        (design / "treatments" / f"{slug}.html").write_text(
            layout("../").replace("{main}", main).replace("{title}", title)
        )
    return design


def _every_treatment(prefix: str = "") -> list[tuple[str, str]]:
    return [(f"{prefix}treatments/{slug}.html", title) for slug, title in TREATMENTS.items()]


def _plan(design: Path) -> Any:
    content_map = analyze(design, "website").draft_map(str(design))
    assert any(m["name"] == "Treatment" for m in content_map["models"])
    return plan(design, "website", editable=True, content_map=content_map)


def _seed(result: Any, name: str) -> str:
    return str(result.templates[f"templates/website/menus/{name}.html"])


def test_a_list_of_every_detail_page_is_seeded_as_the_rows(tmp_path: Path) -> None:
    result = _plan(_design(tmp_path, _every_treatment()))
    names = [n for n in result.editable.menus if n.startswith("footer")]
    assert len(names) == 1
    seed = _seed(result, names[0])
    assert '<ul data-karni-children-from="website.Treatment" class="footer-links">' in seed
    assert any(
        f"menu {names[0]!r} lists the Treatment rows" in note and "3 detail pages" in note
        for note in result.editable.notes
    )
    # the header's links are other pages: its seed keeps them
    assert "data-karni-children-from" not in _seed(result, "header")


def test_a_submenu_of_every_detail_page_is_marked(tmp_path: Path) -> None:
    header = (
        '<ul class="nav"><li><a href="index.html">Home</a></li>'
        '<li><a href="index.html#list">Treatments</a><ul class="sub">'
        + _links(_every_treatment())
        + "</ul></li></ul>"
    )
    result = _plan(_design(tmp_path, _every_treatment(), header=header))
    seed = _seed(result, "header")
    assert '<ul class="nav">' in seed
    assert '<ul data-karni-children-from="website.Treatment" class="sub">' in seed


@pytest.mark.parametrize(
    "footer",
    [
        _every_treatment()[:2],  # one left out
        [*_every_treatment(), ("contact.html", "Contact")],  # another page too
        [(href, "Our " + text) for href, text in _every_treatment()],  # other words
        [*_every_treatment(), _every_treatment()[0]],  # one twice
    ],
    ids=["one-left-out", "another-page", "other-words", "twice"],
)
def test_only_an_exact_list_of_the_detail_pages_follows_the_rows(
    tmp_path: Path, footer: list[tuple[str, str]]
) -> None:
    result = _plan(_design(tmp_path, footer))
    for name in result.editable.menus:
        assert "data-karni-children-from" not in _seed(result, name)
    assert not any("rows (its links" in note for note in result.editable.notes)


def test_without_a_map_menus_keep_their_links(tmp_path: Path) -> None:
    design = _design(tmp_path, _every_treatment())
    result = plan(design, "website", editable=True)
    for name in result.editable.menus:
        assert "data-karni-children-from" not in _seed(result, name)
