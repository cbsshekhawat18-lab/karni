"""``{{ value|highlight:"span.accent" }}``: highlighted words back in the design's markup."""

from __future__ import annotations

import pytest
from django.template import Context, Template, TemplateSyntaxError

from karni_site.text import highlight, markup


def render(text: str, **context: object) -> str:
    return Template("{% load karni_site %}" + text).render(Context(context))


def test_marked_words_get_the_markup_the_spec_names() -> None:
    value = "Custom homes, *crafted for place*"
    assert render('{{ v|highlight:"span.accent" }}', v=value) == (
        'Custom homes, <span class="accent">crafted for place</span>'
    )
    assert render("{{ v|highlight }}", v="Rooms for *reading*") == "Rooms for <em>reading</em>"
    assert render('{{ v|highlight:"strong.a.b" }}', v="*x* and *y*") == (
        '<strong class="a b">x</strong> and <strong class="a b">y</strong>'
    )


def test_everything_else_is_escaped_and_an_empty_spec_drops_the_marks() -> None:
    assert render('{{ v|highlight:"em" }}', v='<b>"x"</b> *&*') == (
        "&lt;b&gt;&quot;x&quot;&lt;/b&gt; <em>&amp;</em>"
    )
    assert render('{{ v|highlight:"" }}', v="Shape clay *by hand*") == "Shape clay by hand"
    assert render('{{ v|highlight:"em" }}', v=r"5 \* 3 is *fifteen*") == "5 * 3 is <em>fifteen</em>"
    assert render('{{ v|highlight:"em" }}', v=None) == ""
    assert highlight("no marks", "em") == "no marks"


def test_a_spec_that_is_not_markup_is_refused() -> None:
    with pytest.raises(ValueError, match="span.accent"):
        markup('span onclick="x"')
    with pytest.raises(TemplateSyntaxError, match="SITE003"):
        render('{{ v|highlight:"<script>" }}', v="*x*")
