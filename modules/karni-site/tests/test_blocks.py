"""{% editable %} and {% editable_image %}: defaults, editing, sanitising, caching."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.template import Context, Template, TemplateSyntaxError
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from pytest_django import Settings

from karni_site import blocks
from karni_site.images import replace_image, validate_image
from karni_site.models import Block
from karni_site.sanitize import from_editing, sanitize, to_editing

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def render(source: str, request: Any = None, **context: Any) -> str:
    template = Template("{% load static karni_site %}" + source)
    return template.render(Context({"request": request, **context}))


def test_the_template_is_the_default_and_the_first_render_stores_it() -> None:
    source = '{% editable "home.intro" %}Bread <b>worth</b> the walk.{% endeditable %}'
    assert render(source) == "Bread <b>worth</b> the walk."
    block = Block.objects.get(key="home.intro")
    assert (block.page, block.kind, block.html, block.default_html) == (
        "home",
        "text",
        "Bread <b>worth</b> the walk.",
        "Bread <b>worth</b> the walk.",
    )
    assert not block.edited
    # A second block of the page comes after it in the admin's order.
    render('{% editable "home.outro" %}Bye{% endeditable %}')
    assert Block.objects.get(key="home.outro").position == 1


def test_an_edited_block_shows_the_edit_and_an_untouched_one_follows_the_template() -> None:
    render('{% editable "about.story" %}Two bakers.{% endeditable %}')
    render('{% editable "about.team" %}Ada and Bo.{% endeditable %}')
    story = Block.objects.get(key="about.story")
    story.html = "Three bakers, <em>one</em> oven."
    story.save()
    assert render('{% editable "about.story" %}Two bakers.{% endeditable %}') == (
        "Three bakers, <em>one</em> oven."
    )
    # The designer's new version changes the untouched block, not the edited one.
    assert render('{% editable "about.team" %}Ada, Bo and Cy.{% endeditable %}') == (
        "Ada, Bo and Cy."
    )
    team = Block.objects.get(key="about.team")
    assert team.html == team.default_html == "Ada, Bo and Cy."
    assert render('{% editable "about.story" %}Four bakers.{% endeditable %}') == (
        "Three bakers, <em>one</em> oven."
    )
    assert Block.objects.get(key="about.story").default_html == "Two bakers."


def test_a_page_renders_its_blocks_with_the_request(client: Client) -> None:
    page = client.get("/contact/").content.decode()
    assert '<h1>Visit <span class="accent">the bakery</span></h1>' in page
    title = Block.objects.get(key="contact.hero.title")
    title.html = "Come and <b>see</b> us"
    title.save()
    assert "<h1>Come and <b>see</b> us</h1>" in client.get("/contact/").content.decode()


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ("Hi<script>alert(1)</script> there", "Hi there"),
        ("<style>body{display:none}</style>Plain", "Plain"),
        ('<b onclick="steal()">bold</b>', "<b>bold</b>"),
        ('<a href="javascript:alert(1)">x</a>', "<a>x</a>"),
        ('<a href=" jav&#x09;ascript:alert(1)">x</a>', "<a>x</a>"),
        ('<a href="data:text/html,<b>x</b>">x</a>', "<a>x</a>"),
        ('<img src="x" onerror="steal()">text', "text"),
        (
            '<a href="/menu/#cakes" title="Cakes" class="btn">Cakes</a>',
            '<a href="/menu/#cakes" title="Cakes">Cakes</a>',
        ),
        (
            '<a href="https://example.com" target="_blank">out</a>',
            '<a href="https://example.com" target="_blank" rel="noopener noreferrer">out</a>',
        ),
        ("<p>one</p><div>two</div>", "onetwo"),
        ("<svg><text>drawn</text></svg>kept", "kept"),
        ("<b>open", "<b>open</b>"),
        ("a &amp; b &lt;c&gt;", "a &amp; b &lt;c&gt;"),
        ('<mark>bright</mark> <mark class="x">dim</mark>', "<mark>bright</mark> <mark>dim</mark>"),
        ("<!-- note -->line<br/>next", "line<br>next"),
    ],
)
def test_sanitising_keeps_the_safe_subset(dirty: str, clean: str) -> None:
    assert sanitize(dirty) == clean
    assert sanitize(clean) == clean  # idempotent


def test_an_edit_is_cleaned_when_it_is_saved() -> None:
    render('{% editable "home.note" %}Hello{% endeditable %}')
    block = Block.objects.get(key="home.note")
    block.html = '<b onmouseover="x()">Hi</b><script>evil()</script> <a href="javascript:x">y</a>'
    block.save()
    block.refresh_from_db()
    assert block.html == "<b>Hi</b> <a>y</a>"
    assert render('{% editable "home.note" %}Hello{% endeditable %}') == "<b>Hi</b> <a>y</a>"


def test_the_highlight_convention_is_a_setting(settings: Settings) -> None:
    assert to_editing("Work across <mark>every scale</mark><br>\n  now") == (
        "Work across ==every scale==\nnow"
    )
    assert from_editing("Work across ==every scale==\nnow") == (
        "Work across <mark>every scale</mark><br>\nnow"
    )
    settings.KARNI_SITE_HIGHLIGHT = {"marker": "*", "tag": "span", "class": "accent"}
    assert from_editing("Work across *every scale*") == (
        'Work across <span class="accent">every scale</span>'
    )
    assert to_editing('Work <span class="accent">here</span> <span>plain</span>') == (
        "Work *here* <span>plain</span>"
    )
    assert sanitize('<span class="accent">a</span><span class="other">b</span><mark>c</mark>') == (
        '<span class="accent">a</span>bc'
    )


def test_a_page_of_blocks_is_one_cache_read(settings: Settings) -> None:
    request = RequestFactory().get("/")
    source = "".join(
        f'{{% editable "home.part_{n}" %}}Part {n}{{% endeditable %}}' for n in range(5)
    )
    render(source, request)  # stores the five blocks
    render(source, RequestFactory().get("/"))  # reads the page's blocks into the cache
    request = RequestFactory().get("/")
    with CaptureQueriesContext(connection) as queries:
        rendered = render(source, request)
    assert rendered == "Part 0Part 1Part 2Part 3Part 4"
    assert len(queries) == 0
    # A save clears the page's entry, and the next render reads it once.
    block = Block.objects.get(key="home.part_3")
    block.html = "Changed"
    block.save()
    with CaptureQueriesContext(connection) as queries:
        rendered = render(source, RequestFactory().get("/"))
    assert "Changed" in rendered and len(queries) == 1


def test_nothing_is_stored_when_seeding_is_off(settings: Settings) -> None:
    settings.KARNI_SITE_SEED_ON_RENDER = False
    assert render('{% editable "home.quiet" %}Quiet{% endeditable %}') == "Quiet"
    assert not Block.objects.filter(key="home.quiet").exists()


def test_a_deleted_block_comes_back_from_the_template() -> None:
    render('{% editable "home.gone" %}Default{% endeditable %}')
    block = Block.objects.get(key="home.gone")
    block.html = "Edited"
    block.save()
    block.delete()  # soft: the template's default is shown and stored again
    assert render('{% editable "home.gone" %}Default{% endeditable %}') == "Default"
    assert Block.objects.get(key="home.gone").html == "Default"


def test_keys_are_checked_when_the_template_compiles() -> None:
    for bad in (
        '{% editable "Home Intro" %}x{% endeditable %}',
        "{% editable %}x{% endeditable %}",
        '{% editable_image "home.x" big %}x{% endeditable_image %}',
    ):
        with pytest.raises(TemplateSyntaxError, match="SITE003"):
            render(bad)
    assert render("{% editable key %}x{% endeditable %}", key="home.var") == "x"
    with pytest.raises(TemplateSyntaxError, match="SITE003"):
        render("{% editable key %}x{% endeditable %}", key="Bad Key")


IMG = (
    '<picture><source srcset="/static/a.webp" type="image/webp">'
    '<img class="hero" src="/static/a.jpg" srcset="/static/a-2x.jpg 2x" alt="A lake" '
    'loading="lazy"></picture>'
)


def test_an_image_keeps_the_designs_markup_until_a_picture_is_uploaded() -> None:
    source = '{% editable_image "home.hero" %}' + IMG + "{% endeditable_image %}"
    assert render(source) == IMG
    block = Block.objects.get(key="home.hero")
    assert (block.kind, block.default_src, block.alt, block.default_alt) == (
        "image",
        "/static/a.jpg",
        "A lake",
        "A lake",
    )
    block.image = SimpleUploadedFile("dawn.png", PNG)
    block.alt = "A lake at dawn"
    block.save()
    shown = render(source)
    assert "<source" not in shown and "srcset" not in shown
    assert 'class="hero"' in shown and 'loading="lazy"' in shown
    assert f'src="{block.image.url}"' in shown and 'alt="A lake at dawn"' in shown
    block.image.delete(save=False)


def test_only_the_alt_text_can_change_too() -> None:
    source = (
        '{% editable_image "home.oven" %}<img src="/static/oven.jpg" alt="Oven">'
        "{% endeditable_image %}"
    )
    render(source)
    block = Block.objects.get(key="home.oven")
    block.alt = "The wood oven"
    block.save()
    assert render(source) == '<img src="/static/oven.jpg" alt="The wood oven">'


def test_a_url_block_holds_a_bare_address_for_a_style_attribute() -> None:
    source = (
        '<div style="background: url(&quot;{% editable_image "home.band" url %}'
        '/static/band.png{% endeditable_image %}&quot;)"></div>'
    )
    assert render(source) == '<div style="background: url(&quot;/static/band.png&quot;)"></div>'
    block = Block.objects.get(key="home.band")
    block.image = SimpleUploadedFile("band.png", PNG)
    block.save()
    assert f"url(&quot;{block.image.url}&quot;)" in render(source)
    block.image.delete(save=False)


def test_uploads_must_be_images_of_an_allowed_type(settings: Settings) -> None:
    validate_image(SimpleUploadedFile("ok.png", PNG))
    with pytest.raises(ValidationError, match="not a PNG image"):
        validate_image(SimpleUploadedFile("fake.png", b"<html>not an image</html>"))
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(ValidationError, match="Upload an image"):
        validate_image(SimpleUploadedFile("logo.svg", svg))
    settings.KARNI_SITE_IMAGE_TYPES = ["svg"]
    validate_image(SimpleUploadedFile("logo.svg", svg))


def test_replace_image_changes_only_the_address_and_alt() -> None:
    assert replace_image('<img data-src="/a.jpg" src="/blank.gif" class="lazy">', "/b.png") == (
        '<img data-src="/b.png" src="/b.png" class="lazy">'
    )
    assert replace_image('<img src="/a.jpg"/>', "/b.png", 'Say "hi"') == (
        '<img src="/b.png" alt="Say &quot;hi&quot;" />'
    )
    assert replace_image("/static/a.png", "/media/b.png") == "/media/b.png"


def test_a_database_that_cannot_be_read_shows_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db import DatabaseError

    def fail(page: str) -> Any:
        raise DatabaseError("down")

    monkeypatch.setattr(blocks, "load_page", fail)
    assert render('{% editable "home.down" %}Still here{% endeditable %}') == "Still here"
