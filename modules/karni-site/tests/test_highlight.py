"""One convention for highlighted words: ``KARNI_SITE_HIGHLIGHT`` for blocks and fields alike."""

from __future__ import annotations

import pytest
from django.template import Context, Template, TemplateSyntaxError
from django.test import override_settings

from karni_site.sanitize import apply_marks, escape_marks, from_editing, to_editing
from karni_site.text import highlight, markup

ACCENT = {"marker": "==", "tag": "span", "class": "accent"}


def render(text: str, **context: object) -> str:
    return Template("{% load karni_site %}" + text).render(Context(context))


def test_without_a_spec_the_filter_uses_the_setting() -> None:
    value = "Custom homes, ==crafted for place=="
    # The default convention: ==words== as <mark>.
    assert render("{{ v|highlight }}", v=value) == "Custom homes, <mark>crafted for place</mark>"
    with override_settings(KARNI_SITE_HIGHLIGHT=ACCENT):
        assert render("{{ v|highlight }}", v=value) == (
            'Custom homes, <span class="accent">crafted for place</span>'
        )


def test_a_spec_names_the_markup_and_the_marker_stays_the_settings() -> None:
    assert (
        render('{{ v|highlight:"em" }}', v="Rooms for ==reading==") == "Rooms for <em>reading</em>"
    )
    assert render('{{ v|highlight:"strong.a.b" }}', v="==x== and ==y==") == (
        '<strong class="a b">x</strong> and <strong class="a b">y</strong>'
    )
    with override_settings(KARNI_SITE_HIGHLIGHT={"marker": "**", "tag": "mark", "class": ""}):
        assert render('{{ v|highlight:"em" }}', v="a **b** ==c==") == "a <em>b</em> ==c=="
        assert render("{{ v|highlight }}", v="a **b**") == "a <mark>b</mark>"


def test_everything_else_is_escaped_and_an_empty_spec_drops_the_marks() -> None:
    assert render("{{ v|highlight }}", v='<b>"x"</b> ==&==') == (
        "&lt;b&gt;&quot;x&quot;&lt;/b&gt; <mark>&amp;</mark>"
    )
    assert render('{{ v|highlight:"" }}', v="Shape clay ==by hand==") == "Shape clay by hand"
    assert render("{{ v|highlight }}", v=None) == ""
    assert highlight("no marks") == "no marks"
    with override_settings(KARNI_SITE_HIGHLIGHT={"marker": "", "tag": "mark", "class": ""}):
        assert render("{{ v|highlight }}", v="==kept as typed==") == "==kept as typed=="


def test_a_backslash_before_the_marker_keeps_it_in_fields_and_blocks_alike() -> None:
    value = r"a \== b ==c=="
    assert render("{{ v|highlight }}", v=value) == "a == b <mark>c</mark>"
    assert apply_marks(value, "==", "<i>", "</i>") == "a == b <i>c</i>"
    assert escape_marks("x == y", "==") == r"x \== y"
    # An edited block: the literal marker survives the round trip as text.
    html = from_editing(value)
    assert html == "a == b <mark>c</mark>"
    assert to_editing(html) == value
    assert from_editing(to_editing(html)) == html


def test_a_spec_that_is_not_markup_is_refused() -> None:
    with pytest.raises(ValueError, match="span.accent"):
        markup('span onclick="x"')
    with pytest.raises(TemplateSyntaxError, match="SITE003"):
        render('{{ v|highlight:"<script>" }}', v="==x==")
