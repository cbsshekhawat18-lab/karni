"""The site's address in a design: the clear cases become site.address, the rest stay text."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from karni_cli.design import site
from karni_cli.design.editable import _address_parts
from karni_cli.design.parse import parse

PAGE = """<!doctype html><html><head><title>{title}</title></head><body>
<header><a href="index.html">Home</a> <a href="contact.html">Contact</a></header>
<main>{main}</main>
<footer><div class="col"><h4>Bakehouse</h4>{footer}
<p><a href="tel:+441234000111">01234 000 111</a></p></div></footer>
</body></html>
"""


def _design(tmp_path: Path, footer: str, contact: str, home: str = "<p>Fresh bread.</p>") -> Path:
    design = tmp_path / "design"
    design.mkdir()
    (design / "index.html").write_text(PAGE.format(title="Home", main=home, footer=footer))
    (design / "contact.html").write_text(PAGE.format(title="Contact", main=contact, footer=footer))
    return design


def _lines(plan: site.SitePlan, needle: str) -> list[str]:
    return [
        f"{name}: {line.strip()}"
        for name, text in plan.templates.items()
        for line in text.splitlines()
        if needle in line
    ]


@pytest.mark.parametrize(
    ("markup", "parts"),
    [
        ("<p>12 Harbour Street, Easton, EA1 2BD</p>", ["12 Harbour Street", "Easton", "EA1 2BD"]),
        (
            "<address>221B Baker Street<br>London NW1 6XE</address>",
            ["221B Baker Street", "London NW1 6XE"],
        ),
        ("<p>Rue de Rivoli 10, 75001 Paris</p>", ["Rue de Rivoli 10", "75001 Paris"]),
        (
            "<span>Calle Mayor 5<br/>28013 Madrid<br>España</span>",
            ["Calle Mayor 5", "28013 Madrid", "España"],
        ),
    ],
)
def test_a_postal_address(markup: str, parts: list[str]) -> None:
    node = next(iter(parse(markup).root.elements()))
    assert _address_parts(node, markup) == parts


@pytest.mark.parametrize(
    "markup",
    [
        "<p>We opened in 1998, on Harbour Street. Come and see us.</p>",  # a sentence
        "<p>Mon–Fri 8:00–18:00, Sat 9:00–13:00</p>",  # opening hours
        "<p>hello@bakehouse.example, 01234 000 111</p>",  # an email
        "<p>12 Harbour Street</p>",  # one part only
        "<p>Bread, cakes, coffee</p>",  # no number
        '<p>12 <a href="map.html">Harbour Street</a>, Easton</p>',  # other markup
    ],
)
def test_text_that_is_not_an_address(markup: str) -> None:
    node = next(iter(parse(markup).root.elements()))
    assert _address_parts(node, markup) is None


def test_the_footer_and_the_contact_page_share_site_address(tmp_path: Path) -> None:
    design = _design(
        tmp_path,
        footer="<p>12 Harbour Street, Easton, EA1 2BD</p>",
        contact="<h1>Visit</h1><address>12 Harbour Street<br>Easton<br>EA1 2BD</address>",
    )
    plan = site.plan(design, "website", editable=True)
    base = plan.templates["templates/website/base.html"]
    assert 'address="12 Harbour Street\\nEaston\\nEA1 2BD"' in base  # one line per part
    assert '<p>{{ site.address_lines|join:", " }}</p>' in base  # the design's commas
    contact = plan.templates["templates/website/contact.html"]
    assert "<address>{{ site.address|linebreaksbr }}</address>" in contact  # its line breaks
    assert "Harbour Street" not in base.split("{% site_defaults", 1)[1].split("%}", 1)[1]
    note = next(n for n in plan.editable.notes if n.startswith("address:"))
    assert "the layout shared by every page and contact.html:" in note


def test_an_address_beside_the_phone_link_alone(tmp_path: Path) -> None:
    design = _design(tmp_path, footer="<p>Rue de Rivoli 10, 75001 Paris</p>", contact="<h1>Hi</h1>")
    plan = site.plan(design, "website", editable=True)
    assert (
        'address="Rue de Rivoli 10\\n75001 Paris"' in plan.templates["templates/website/base.html"]
    )


def test_a_lone_postal_looking_line_stays_text(tmp_path: Path) -> None:
    design = _design(tmp_path, footer="<p>Open daily</p>", contact="<p>Unit 4, 12 Mill Lane</p>")
    plan = site.plan(design, "website", editable=True)
    assert not _lines(plan, "site.address")
    assert "Unit 4, 12 Mill Lane" in plan.templates["templates/website/contact.html"]


def test_two_addresses_stay_text_and_the_report_says_so(tmp_path: Path) -> None:
    design = _design(
        tmp_path,
        footer="<p>12 Harbour Street, Easton</p>",
        contact="<address>4 Mill Lane<br>Weston</address>",
    )
    plan = site.plan(design, "website", editable=True)
    assert not _lines(plan, "site.address")
    assert 'address="' not in plan.templates["templates/website/base.html"]
    note = next(n for n in plan.editable.notes if n.startswith("address:"))
    assert "show different addresses, so they stay text blocks" in note
    assert re.search(
        r"\{% editable \"[^\"]+\" %\}4 Mill Lane", plan.templates["templates/website/contact.html"]
    )
