"""``karni import design``: the design package (parse, rewrite, compare) and the command.

Three designs that differ: a bakery (a shared header and footer, a stub
redirect page, an inline script, a handler attribute, a form posting to
another origin), a one-page portfolio (anchors, srcset, a picture, a style
block, JSON-LD) and a clinic with Bootstrap classes, nested folders, a page
whose header differs and a 404 page.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli.commands import ui as ui_command
from karni_cli.design import compare, parse, rewrite
from karni_cli.design.rewrite import Mapped, Rewriter
from karni_cli.main import app

from .conftest import TEMPLATE
from .test_make import fails, ok

DESIGNS = Path(__file__).parent / "fixtures" / "designs"
BAKERY, PORTFOLIO, CLINIC = DESIGNS / "bakery", DESIGNS / "portfolio", DESIGNS / "clinic"


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (the copied images are not text)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Import Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "import_check"
    monkeypatch.chdir(root)
    return root


# --- parse --------------------------------------------------------------------


@pytest.mark.parametrize("page", sorted(DESIGNS.rglob("*.html")), ids=lambda p: p.name)
def test_tokens_cover_every_page_byte_for_byte(page: Path) -> None:
    source = page.read_text(encoding="utf-8")
    doc = parse.parse(source)
    assert "".join(token.text(source) for token in doc.tokens) == source
    for node in doc.root.iter():
        if node.parent is not None:
            assert node.parent.start <= node.start <= node.end <= node.parent.end, node.tag
    assert doc.html is not None and doc.head is not None and doc.body is not None


def test_the_tree_is_loose_but_exact() -> None:
    source = '<ul>\n<li>one<li>two</ul><p>a<p>b</div><img src="x.png"><br>tail'
    doc = parse.parse(source)
    ul = doc.root.find("ul")
    assert ul is not None and [li.text(source) for li in ul.elements()] == ["<li>one", "<li>two"]
    paragraphs = doc.root.find_all("p")
    # <p> closes on a sibling <p>; a stray </div> closes nothing; <img> and <br> are children.
    assert [p.text(source) for p in paragraphs] == ["<p>a", '<p>b</div><img src="x.png"><br>tail']
    img = doc.root.find("img")
    assert img is not None and img.children == [] and img.attr(source, "src") == "x.png"
    assert doc.root.text(source) == source  # the stray </div> is in the span, not a node
    script = parse.parse("<script>if (a < b) {}</script>").root.find("script")
    assert script is not None and script.inner_text("<script>if (a < b) {}</script>") == (
        "if (a < b) {}"
    )


def test_attributes_know_where_their_values_are() -> None:
    text = """<a href="x.html?q=1#f" class='a b' disabled data-x=1 TITLE="&amp;">"""
    found = {attr.name: attr for attr in parse.attributes(text)}
    assert list(found) == ["href", "class", "disabled", "data-x", "title"]
    href = found["href"]
    assert text[href.value_start : href.value_end] == "x.html?q=1#f" and href.quote == '"'
    assert found["class"].quote == "'" and found["class"].value == "a b"
    assert found["disabled"].value is None and found["data-x"].quote == ""
    assert found["title"].value == "&"  # decoded
    assert parse.attributes('<img src="a.png"/>')[0].value == "a.png"


# --- rewrite ------------------------------------------------------------------


def test_page_names_and_routes() -> None:
    cases = {
        "index.html": ("home", ""),
        "about.html": ("about", "about/"),
        "services/web.html": ("services_web", "services/web/"),
        "blog/index.html": ("blog", "blog/"),
        "2024.html": ("page_2024", "2024/"),
        "render.html": ("render_page", "render/"),
        "Our Team.htm": ("our_team", "Our-Team/"),
    }
    for source, (name, route) in cases.items():
        assert (rewrite.page_view_name(source), rewrite.page_route(source)) == (name, route)
    assert rewrite.page_view_name("about.html", {"about"}) == "about_2"


def test_references_are_classified() -> None:
    mapped = Mapped(
        "site",
        {"index.html": "home", "about.html": "about", "services/index.html": "services"},
        {"css/a.css", "img/x.png"},
        redirects={"old.html": "about.html"},
    )

    def kind(value: str, page_dir: str = "") -> tuple[str, str, str, str]:
        ref = mapped.resolve(value, page_dir)
        return ref.kind, ref.path, ref.query, ref.fragment

    assert kind("about.html?x=1#team") == ("page", "about.html", "?x=1", "#team")
    assert kind("../about.html", "services") == ("page", "about.html", "", "")
    assert kind("/about.html") == ("page", "about.html", "", "")
    assert kind("services/") == ("page", "services/index.html", "", "")
    assert kind("services") == ("page", "services/index.html", "", "")
    assert kind("about") == ("page", "about.html", "", "")
    assert kind("./") == ("page", "index.html", "", "")
    assert kind("old.html#x") == ("page", "old.html", "", "#x")
    assert mapped.view_name("old.html") == "about"
    assert kind("css/a.css?v=2") == ("asset", "css/a.css", "?v=2", "")
    assert kind("../img/x.png", "services") == ("asset", "img/x.png", "", "")
    assert kind("missing.html")[0] == "missing" and kind("../../x.png", "a")[0] == "missing"
    assert kind("#top")[0] == "inert" and kind("mailto:a@b.c")[0] == "inert"
    assert kind("")[0] == "empty" and kind("?q=1")[0] == "inert"
    external = mapped.resolve("https://cdn.example.com/lib.js?x=1", "")
    assert (external.kind, external.origin) == ("external", "https://cdn.example.com")
    assert mapped.resolve("//cdn.example.com/x", "").origin == "https://cdn.example.com"


def _rewriter(page_dir: str = "") -> Rewriter:
    mapped = Mapped(
        "site",
        {"index.html": "home", "about.html": "about"},
        {"img/a.jpg", "img/a@2x.jpg", "fonts/x.woff2", "css/base.css"},
    )
    return Rewriter(mapped, page_dir)


def _tag(rewriter: Rewriter, text: str) -> str:
    doc = parse.parse(text)
    node = doc.root.elements()[0]
    return rewriter.tag(node, text)


def test_tags_are_rewritten_in_place() -> None:
    rewriter = _rewriter()
    assert _tag(rewriter, '<a href="about.html#team">') == (
        "<a href=\"{% url 'site:about' %}#team\">"
    )
    assert _tag(rewriter, "<a href='index.html?x=1'>") == (
        """<a href='{% url "site:home" %}?x=1'>"""
    )
    assert _tag(rewriter, '<img src="img/a.jpg" srcset="img/a.jpg 1x, img/a@2x.jpg 2x">') == (
        "<img src=\"{% static 'site/img/a.jpg' %}\" srcset=\"{% static 'site/img/a.jpg' %} 1x, "
        "{% static 'site/img/a@2x.jpg' %} 2x\">"
    )
    assert _tag(rewriter, '<div style="background: url(&quot;img/a.jpg&quot;) no-repeat">') == (
        "<div style=\"background: url(&quot;{% static 'site/img/a.jpg' %}&quot;) no-repeat\">"
    )
    assert _tag(rewriter, '<button onclick="go(&quot;x&quot;)">') == (
        '<button onclick="{% csp_hash attribute %}go(&quot;x&quot;){% endcsp_hash %}">'
    )
    assert _tag(rewriter, '<meta property="og:image" content="img/a.jpg">') == (
        '<meta property="og:image" content="{% static \'site/img/a.jpg\' %}">'
    )
    assert _tag(rewriter, '<meta name="x" content="plain text">') == (
        '<meta name="x" content="plain text">'
    )
    assert _tag(rewriter, '<p data-tpl="{{ x }}" title="{% y %}">') == (
        '<p data-tpl="{% templatetag openvariable %} x {% templatetag closevariable %}" '
        'title="{% templatetag openblock %} y {% templatetag closeblock %}">'
    )
    assert _tag(rewriter, '<a href="nowhere.html">') == '<a href="nowhere.html">'
    assert [problem.why for problem in rewriter.problems] == [
        "nowhere.html is not a page or a file of the design, so the link was kept as written"
    ]
    assert rewriter.used_files == {"img/a.jpg", "img/a@2x.jpg"} and rewriter.links == {
        "about.html",
        "index.html",
    }
    nested = _rewriter("services")
    assert _tag(nested, '<link rel="stylesheet" href="../css/base.css">') == (
        '<link rel="stylesheet" href="{% static \'site/css/base.css\' %}">'
    )


def test_css_blocks_and_other_origins() -> None:
    rewriter = _rewriter()
    css = '@import url("css/base.css");\n@font-face { src: url(fonts/x.woff2); }\n.a { background: url("img/a.jpg"); }\n.b { background: url(https://cdn.example.com/bg.png); }'
    assert rewriter.css(css, 0, attribute=False) == (
        "@import url(\"{% static 'site/css/base.css' %}\");\n"
        "@font-face { src: url({% static 'site/fonts/x.woff2' %}); }\n"
        ".a { background: url(\"{% static 'site/img/a.jpg' %}\"); }\n"
        ".b { background: url(https://cdn.example.com/bg.png); }"
    )
    assert rewriter.policy.sources == {"img-src": {"https://cdn.example.com"}}
    _tag(rewriter, '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">')
    _tag(rewriter, '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    _tag(rewriter, '<script src="https://cdn.example.com/lib.js"></script>')
    _tag(rewriter, '<link rel="stylesheet" href="https://cdn.example.com/lib.css">')
    _tag(rewriter, '<link rel="preload" as="font" href="https://fonts.example.com/a.woff2">')
    _tag(rewriter, '<iframe src="https://maps.example.com/embed"></iframe>')
    _tag(rewriter, '<form action="https://forms.example.com/x">')
    _tag(rewriter, '<a href="https://elsewhere.example.com/">')
    assert rewriter.policy.tag() == (
        '{% csp_allow "font-src https://cdn.example.com https://fonts.example.com '
        'https://fonts.gstatic.com" "form-action https://forms.example.com" '
        '"frame-src https://maps.example.com" "img-src https://cdn.example.com" '
        '"script-src https://cdn.example.com" "style-src https://cdn.example.com '
        'https://fonts.googleapis.com" %}'
    )
    assert rewrite.Policy().tag() == ""


def test_template_syntax_in_a_design_is_escaped() -> None:
    assert rewrite.escape_template_syntax("a {{ b }} {% c %} {# d #}") == (
        "a {% templatetag openvariable %} b {% templatetag closevariable %} "
        "{% templatetag openblock %} c {% templatetag closeblock %} "
        "{% templatetag opencomment %} d {% templatetag closecomment %}"
    )
    assert rewrite.srcset_parts("a.jpg 1x,b.jpg 2x, c.jpg") == [
        ("", "a.jpg", " 1x"),
        ("", "b.jpg", " 2x"),
        (" ", "c.jpg", ""),
    ]


# --- compare ------------------------------------------------------------------


def _blocks(source: str) -> list[compare.Block]:
    doc = parse.parse(source)
    return compare.blocks(doc.body_or_root(), source)[0]


def test_signatures_ignore_state_attributes_whitespace_and_comments() -> None:
    one = '<nav>\n  <!-- x -->\n  <a href="a.html" class="link active" aria-current="page">A</a>\n</nav>'
    two = '<nav><a href="a.html" class="link">A</a></nav>'
    three = '<nav><a href="b.html" class="link">A</a></nav>'

    def sig(text: str) -> str:
        return _blocks(text)[0].signature

    assert sig(one) == sig(two) != sig(three)
    assert compare.block_name(_blocks(one)[0].node, one, "") == "nav"
    section = '<!-- ===== Our Story ===== -->\n<section class="story" id="about-us">x</section>'
    block = _blocks(section)[0]
    assert compare.block_name(block.node, section, block.lead(section)) == "our-story"
    assert compare.block_name(block.node, section, "") == "about-us"
    assert (
        compare.block_name(
            _blocks('<section class="cta big">x</section>')[0].node,
            '<section class="cta big">x</section>',
            "",
        )
        == "cta"
    )


def _page(header: str, body: str, footer: str = "<footer>f</footer>") -> str:
    return f"<html><body>\n{header}\n{body}\n{footer}\n</body></html>"


def test_layout_finds_the_shared_prefix_suffix_partials_and_overrides() -> None:
    header = '<header><a href="a.html" class="{active}">A</a></header>'
    cta = '<section class="cta">Call us</section>'
    sources = {
        "index.html": _page(header.format(active=""), "<main>home</main>\n" + cta),
        "a.html": _page(header.format(active="on"), "<main>a</main>\n" + cta),
        "b.html": _page(header.format(active=""), "<main>b</main>"),
        "odd.html": _page('<header class="slim">x</header>', "<main>odd</main>"),
        "bare.html": _page("", "<main>bare</main>"),
    }
    blocks = {key: _blocks(text) for key, text in sources.items()}
    layout = compare.layout(blocks, sources, list(sources))
    assert [g.name for g in layout.prefix] == ["header"]
    assert [g.name for g in layout.suffix] == ["footer"]
    assert [g.name for g in layout.partials] == ["cta"]
    header_group = layout.prefix[0]
    assert set(header_group.instances) == {"index.html", "a.html", "b.html"}
    assert header_group.reference == "index.html"
    assert layout.pages["odd.html"].overrides["header"] is not None  # its own, slim header
    assert layout.pages["bare.html"].overrides["header"] is None  # none at all
    assert "header" not in layout.pages["index.html"].overrides
    assert layout.pages["index.html"].content[1] == "cta"
    assert [b.name for b in layout.pages["b.html"].content] == ["main"]  # type: ignore[union-attr]
    variations = compare.element_variations(header_group, sources)
    assert list(variations) == [1]  # the <a>, not the <header>
    assert variations[1].class_tokens == {"on": {"a.html"}}
    # One page alone shares nothing.
    alone = compare.layout({"index.html": blocks["index.html"]}, sources, ["index.html"])
    assert alone.prefix == [] and alone.suffix == [] and alone.partials == []


def test_generalize_tag_reproduces_each_marker_on_its_pages() -> None:
    def patterns(pages: set[str]) -> list[str]:
        return [f"s:{p.removesuffix('.html')}" for p in sorted(pages)]

    everyone = {"a.html", "b.html", "c.html"}

    def variation(**kwargs: object) -> compare.Variation:
        return compare.Variation(pages=set(everyone), **kwargs)  # type: ignore[arg-type]

    # A marker-only class attribute comes and goes with the attribute.
    text, problems = compare.generalize_tag(
        '<a href="x" class="active">',
        variation(class_tokens={"active": {"a.html"}}, has_class=True),
        patterns,
    )
    assert (text, problems) == (
        '<a href="x"{% ifactive "s:a" %} class="active"{% endifactive %}>',
        [],
    )
    # A token among common ones stays in place.
    text, _ = compare.generalize_tag(
        '<a class="nav-link active" href="x">',
        variation(
            class_tokens={"nav-link": set(everyone), "active": {"a.html", "b.html"}}, has_class=True
        ),
        patterns,
    )
    assert text == '<a class="nav-link{% ifactive "s:a" "s:b" %} active{% endifactive %}" href="x">'
    # First token varying, more follow.
    text, _ = compare.generalize_tag(
        '<li class="open item">',
        variation(class_tokens={"open": {"c.html"}, "item": set(everyone)}, has_class=True),
        patterns,
    )
    assert text == '<li class="{% ifactive "s:c" %}open {% endifactive %}item">'
    # The reference has no class at all: the attribute is added for the pages that have one.
    text, _ = compare.generalize_tag(
        "<a href='x'/>",
        variation(class_tokens={"current": {"b.html"}}, has_class=True),
        patterns,
    )
    assert text == """<a href='x'{% ifactive "s:b" %} class="current"{% endifactive %}/>"""
    # Overlapping page sets: one attribute that is empty elsewhere.
    text, _ = compare.generalize_tag(
        "<a>",
        variation(class_tokens={"x": {"a.html", "b.html"}, "y": {"a.html"}}, has_class=True),
        patterns,
    )
    assert (
        text
        == '<a class="{% ifactive "s:a" "s:b" %}x{% endifactive %}{% ifactive "s:a" %} y{% endifactive %}">'
    )
    # aria-current present on some pages, in place or added.
    text, _ = compare.generalize_tag(
        '<a href="x" aria-current="page" >',
        variation(attributes={"aria-current": ("page", {"a.html"})}),
        patterns,
    )
    assert text == '<a href="x"{% ifactive "s:a" %} aria-current="page"{% endifactive %} >'
    text, _ = compare.generalize_tag(
        '<a href="x">', variation(attributes={"aria-current": ("page", {"a.html"})}), patterns
    )
    assert text == '<a href="x"{% ifactive "s:a" %} aria-current="page"{% endifactive %}>'
    # A value that differs between pages cannot be a marker: kept, reported.
    text, problems = compare.generalize_tag(
        '<a aria-expanded="true">',
        variation(attributes={"aria-expanded": (None, {"a.html", "b.html"})}),
        patterns,
    )
    assert text == '<a aria-expanded="true">' and problems and "aria-expanded" in problems[0]


def test_site_name_and_diff() -> None:
    assert compare.site_name(["Home — Studio", "About — Studio", "Studio — Contact"]) == "Studio"
    assert compare.site_name(["Studio | Home", "Studio | About"]) == "Studio"
    assert compare.site_name(["Only page"]) == "Only page"
    assert compare.site_name(["A - B", "C - D"]) == "A - B"
    old = {
        "pages": [
            {"source": "index.html", "title": "Home", "sections": [{"name": "hero", "hash": "1"}]},
            {"source": "gone.html", "title": "Gone", "sections": []},
        ],
        "shared": [{"name": "header", "hash": "h1"}],
        "partials": [],
        "assets": {"files": {"a.css": {"sha256": "x"}, "old.png": {"sha256": "y"}}},
        "redirects": [{"source": "r.html", "to": "home"}],
    }
    new = {
        "pages": [
            {
                "source": "index.html",
                "title": "Home!",
                "sections": [{"name": "hero", "hash": "2"}, {"name": "cta", "hash": "3"}],
            },
            {"source": "new.html", "route": "/new/", "sections": []},
        ],
        "shared": [{"name": "header", "hash": "h2"}],
        "partials": [{"name": "band", "hash": "b"}],
        "assets": {"files": {"a.css": {"sha256": "z"}, "new.png": {"sha256": "n"}}},
        "redirects": [{"source": "r.html", "to": "about"}],
    }
    assert compare.diff(old, new) == [
        "page new.html: added (/new/)",
        "page gone.html: removed from the design",
        "page index.html: title changed to 'Home!'",
        "page index.html: section 'cta' added",
        "page index.html: section 'hero' changed",
        "shared 'header': changed",
        "partial 'band': added",
        "asset new.png: added",
        "asset old.png: removed from the design",
        "asset a.css: changed",
        "redirect r.html: now goes to about",
    ]


# --- the command --------------------------------------------------------------


def _design_json(project: Path) -> Any:
    return json.loads((project / ".karni" / "design.json").read_text())


def test_import_the_bakery(project: Path) -> None:
    result = ok("import", "design", str(BAKERY), "--app", "website")
    out = result.output
    assert "imported 4 page(s), 1 redirect(s), 0 partial(s), 7 file(s) copied." in out
    assert "shared by every page, in base.html: header (<header>, 4 of 4 pages), footer" in out
    assert "redirect: /specials/ -> menu (from specials.html)" in out
    assert 'current page: the design marks it with class="active", now {% ifactive %}' in out
    assert "copied but unused by any page or stylesheet (1): img/unused.png" in out
    assert "not mapped" not in out
    site_dir = project / "website"
    templates = site_dir / "templates" / "website"
    base = (templates / "base.html").read_text()
    assert base.startswith(
        '{% load static karni_site %}{% csp_allow "font-src https://fonts.gstatic.com" '
        '"style-src https://fonts.googleapis.com" %}<!DOCTYPE html>\n'
    )
    assert "<title>{% block title %}Crumb &amp; Co{% endblock %}</title>" in base
    assert '<meta name="description" content="{% block description %}{% endblock %}">' in base
    assert '<link rel="icon" href="{% static \'website/img/logo.svg\' %}">' in base
    assert "defer></script>{% block head %}{% endblock %}\n</head>" in base
    assert '  <!-- HEADER -->\n  {% block header %}<header class="top">' in base
    assert (
        '<a href="{% url \'website:about\' %}"{% ifactive "website:about" %} class="active"'
        "{% endifactive %}>About</a>"
    ) in base
    assert "<a href=\"{% url 'website:contact' %}?topic=order\"" in base
    assert "</header>{% endblock %}{% block content %}{% endblock %}\n\n  <!-- FOOTER -->" in base
    assert "<a href=\"{% url 'website:menu' %}#cakes\">Cakes</a>" in base
    assert '<a href="https://maps.example.com/crumb">Find us</a>' in base
    home = (templates / "home.html").read_text()
    assert home.startswith(
        '{% extends "website/base.html" %}{% load static karni_site %}\n'
        "{% block title %}Crumb & Co — Bakery{% endblock %}\n"
        "{% block description %}Sourdough, cakes and coffee in the old town.{% endblock %}\n"
        "{% block content %}\n\n  <!-- HERO -->\n"
    )
    assert (
        "style=\"background-image: url(&quot;{% static 'website/img/hero.jpg' %}&quot;)\"" in home
    )
    assert (
        '<script>{% csp_hash %}document.documentElement.classList.add("js");{% endcsp_hash %}'
        "</script>"
    ) in home
    about = (templates / "about.html").read_text()
    assert "<code>{% templatetag openvariable %} flour {% templatetag closevariable %}" in about
    contact = (templates / "contact.html").read_text()
    assert '{% block content %}{% csp_allow "form-action https://forms.example.com" %}' in contact
    assert 'onclick="{% csp_hash attribute %}history.back(){% endcsp_hash %}"' in contact
    assert not (templates / "specials.html").exists()
    views = (site_dir / "views.py").read_text()
    assert views.count("def ") == 4 and 'render(request, "website/menu.html")' in views
    urls = (site_dir / "urls.py").read_text()
    assert "from django.views.generic import RedirectView\n" in urls
    assert (
        '    path("specials/", RedirectView.as_view(pattern_name="website:menu", '
        'permanent=True, query_string=True), name="specials"),\n    # karni:urls\n'
    ) in urls
    assert 'path("menu/", views.menu, name="menu"),' in urls
    pages = (site_dir / "tests" / "test_pages.py").read_text()
    assert (
        'PAGES = [\n    "/",\n    "/about/",\n    "/contact/",\n    "/menu/",\n    # karni:pages\n]'
        in pages
    )
    static = site_dir / "static" / "website"
    assert (static / "css" / "site.css").read_bytes() == (BAKERY / "css" / "site.css").read_bytes()
    assert (static / "img" / "unused.png").is_file() and (static / "js" / "app.js").is_file()
    assert (static / "site.css").is_file()  # karni make site's own file is kept
    record = _design_json(project)
    assert record["version"] == 1 and record["app"] == "website"
    assert record["site"] == {"name": "Crumb & Co"}
    assert [s["name"] for s in record["shared"]] == ["header", "footer"]
    assert record["redirects"] == [
        {"source": "specials.html", "route": "/specials/", "name": "specials", "to": "menu"}
    ]
    assert record["active"] == {"class": ["active"], "attributes": {}}
    assert record["assets"]["unused"] == ["img/unused.png"]
    assert record["assets"]["files"]["css/site.css"]["used"] is True
    menu = next(p for p in record["pages"] if p["source"] == "menu.html")
    assert menu["route"] == "/menu/" and menu["name"] == "menu"
    assert menu["sections"][0]["heading"] == "Menu" and menu["sections"][0]["name"] == "menu"
    assert "website/templates/website/base.html" in record["files"]
    assert "website/static/website/img/hero.jpg" in record["files"]
    # The site app came from `karni make site`: wired, with karni-site.
    config = (project / "config" / "urls.py").read_text()
    assert 'path("", include("website.urls")),' in config and "handler500 = " in config
    assert '"karni_site"' in (project / "config" / "settings.py").read_text()


def test_a_second_import_reports_changes_and_keeps_edits(project: Path, tmp_path: Path) -> None:
    ok("import", "design", str(BAKERY), "--app", "website")
    before = snapshot(project)
    again = ok("import", "design", str(BAKERY))  # the app comes from design.json
    assert snapshot(project) == before
    assert "nothing to change" in again.output and "changes since" not in again.output
    about = project / "website" / "templates" / "website" / "about.html"
    about.write_text(about.read_text() + "{# edited by the project #}\n")
    version2 = tmp_path / "bakery-v2"
    shutil.copytree(BAKERY, version2)
    index = version2 / "index.html"
    index.write_text(index.read_text().replace("<h2>Today</h2>", "<h2>Today at the counter</h2>"))
    (version2 / "about.html").write_text(
        (version2 / "about.html").read_text().replace("Two bakers", "Three bakers")
    )
    (version2 / "img" / "unused.png").unlink()
    (version2 / "img" / "new.png").write_bytes(b"\x89PNG new")
    before = snapshot(project)
    diff = ok("import", "design", str(version2), "--diff")
    assert snapshot(project) == before
    assert "changes since the last import (4):" in diff.output
    for line in (
        "  - page about.html: section 'story' changed",
        "  - page index.html: section 'intro' changed",
        "  - asset img/new.png: added",
        "  - asset img/unused.png: removed from the design",
        "(--diff: nothing written)",
    ):
        assert line in diff.output, line
    applied = ok("import", "design", str(version2))
    assert "modified website/templates/website/home.html" in applied.output
    assert "copied   website/static/website/img/new.png" in applied.output
    assert (
        "kept, edited since the last import (1): website/templates/website/about.html. "
        "Re-run with --force to replace them."
    ) in applied.output
    assert "Today at the counter" in (project / "website/templates/website/home.html").read_text()
    assert about.read_text().endswith("{# edited by the project #}\n")
    # The kept file stays flagged: its recorded hash is the one of the last import.
    assert "about.html: section 'story' changed" not in ok("import", "design", str(version2)).output
    assert "kept, edited since the last import (1)" in ok("import", "design", str(version2)).output
    forced = ok("import", "design", str(version2), "--force")
    assert "modified website/templates/website/about.html" in forced.output
    assert "Three bakers" in about.read_text() and "edited by the project" not in about.read_text()
    # The removed asset is still in the project (never deleted), and reported as removed once.
    assert (project / "website/static/website/img/unused.png").is_file()


def test_import_the_clinic_with_nested_folders_an_odd_header_and_a_404_page(
    project: Path,
) -> None:
    result = ok("import", "design", str(CLINIC), "--app", "website")
    out = result.output
    assert "imported 5 page(s), 0 redirect(s), 0 partial(s), 7 file(s) copied." in out
    assert (
        "shared by every page, in base.html: header (<header>, 5 of 6 pages), cta (<section>, "
        "6 of 6 pages), footer (<footer>, 6 of 6 pages), script (<script>, 6 of 6 pages)"
    ) in out
    assert "header: team.html keep their own in a block override" in out
    assert 'marks it with class="active", aria-current="page"' in out
    assert "copied but unused by any page or stylesheet (1): img/old-logo.png" in out
    templates = project / "website" / "templates"
    base = (templates / "website" / "base.html").read_text()
    assert (
        '<body{% ifactive "website:home" %} class="page-home"{% endifactive %}'
        '{% ifactive "website:team" "/services/*" %} class="page-inner"{% endifactive %}>'
    ) in base
    assert (
        '<a class="nav-link{% ifactive "/services/*" %} active{% endifactive %}" '
        'href="{% url \'website:services\' %}"{% ifactive "/services/*" %} aria-current="page"'
        "{% endifactive %}>Services</a>"
    ) in base
    assert '{% block cta %}<section class="cta bg-primary text-white py-5">' in base
    assert (
        "{% block script %}<script src=\"{% static 'website/js/bootstrap.bundle.min.js' %}\"></script>{% endblock %}"
        in base
    )
    team = (templates / "website" / "team.html").read_text()
    assert '{% block header %}<header class="navbar navbar-dark bg-dark slim">' in team
    dental = (templates / "website" / "services_dental.html").read_text()
    assert "<a href=\"{% url 'website:home' %}\">Back home</a>" in dental
    eyes = (templates / "website" / "services_eyes.html").read_text()
    assert "<a href=\"{% url 'website:services' %}#list\">all services</a>" in eyes
    not_found = (templates / "404.html").read_text()
    assert not_found.startswith('{% extends "website/base.html" %}{% load static karni_site %}\n')
    assert "{% block title %}Not found — Elm Street Clinic{% endblock %}" in not_found
    urls = (project / "website" / "urls.py").read_text()
    for line in (
        'path("services/", views.services, name="services"),',
        'path("services/dental/", views.services_dental, name="services_dental"),',
        'path("team/", views.team, name="team"),',
    ):
        assert line in urls, line
    assert "404" not in urls
    pages = (project / "website" / "tests" / "test_pages.py").read_text()
    assert '"/services/eyes/",' in pages and "/404" not in pages
    record = _design_json(project)
    assert record["error_pages"] == [{"source": "404.html", "template": "404.html"}]
    assert record["active"] == {"class": ["active"], "attributes": {"aria-current": "page"}}
    # fonts.css is reached through clinic.css's @import, and the font through fonts.css.
    assert record["assets"]["files"]["fonts/clinic.woff2"]["used"] is True
    assert record["assets"]["unused"] == ["img/old-logo.png"]
    static = project / "website" / "static" / "website"
    assert (static / "services").exists() is False and (static / "fonts" / "clinic.woff2").is_file()


def test_import_a_one_page_portfolio(project: Path) -> None:
    result = ok("import", "design", str(PORTFOLIO), "--app", "website")
    assert "imported 1 page(s), 0 redirect(s), 0 partial(s), 7 file(s) copied." in result.output
    assert "no header or footer shared by every page" in result.output
    assert "unused" not in result.output
    base = (project / "website/templates/website/base.html").read_text()
    assert '<html lang="en" class="no-js">' in base
    assert '<meta property="og:image" content="{% static \'website/img/shot-2x.jpg\' %}">' in base
    assert (
        ".hero { background: url(\"{% static 'website/img/bg.png' %}\") center / cover; }" in base
    )
    assert '<script type="application/ld+json">{"@context"' in base and "csp_hash" not in base
    assert '<body class="home">{% block content %}{% endblock %}\n</body>' in base
    home = (project / "website/templates/website/home.html").read_text()
    assert '<a href="#work">Work</a>' in home
    assert "<a href=\"{% url 'website:home' %}#top\">Top</a>" in home
    assert '<source srcset="{% static \'website/img/hero.webp\' %}" type="image/webp">' in home
    assert (
        "srcset=\"{% static 'website/img/shot-1x.jpg' %} 1x, {% static 'website/img/shot-2x.jpg' %} 2x\""
    ) in home
    assert (project / "website/views.py").read_text().count("def ") == 1


def test_import_into_a_site_app_the_project_already_edited(project: Path) -> None:
    ok("make", "site", "website")
    base = project / "website" / "templates" / "website" / "base.html"
    base.write_text(base.read_text().replace("<header>", '<header class="mine">'))
    result = ok("import", "design", str(BAKERY), "--app", "website")
    assert (
        "kept, edited since the last import (1): website/templates/website/base.html"
        in result.output
    )
    assert 'class="mine"' in base.read_text()
    # The untouched placeholders were replaced.
    assert "Crumb" in (project / "website/templates/website/home.html").read_text()
    forced = ok("import", "design", str(BAKERY), "--force")
    assert "modified website/templates/website/base.html" in forced.output


def test_import_errors_and_dry_run(project: Path, tmp_path: Path) -> None:
    fails("import", "design", str(tmp_path / "nowhere"), "--app", "website", match="C111")
    empty = tmp_path / "empty"
    empty.mkdir()
    fails("import", "design", str(empty), "--app", "website", match="has no .html page")
    ok("make", "app", "events")
    ok("make", "app", "shop")
    fails("import", "design", str(BAKERY), match="Which app?")
    before = snapshot(project)
    result = ok("import", "design", str(BAKERY), "--app", "website", "--dry-run")
    assert snapshot(project) == before
    assert "would create website/templates/website/base.html" in result.output
    assert "would copy website/static/website/css/site.css" in result.output
    assert "(dry run: nothing written)" in result.output
    assert not (project / "website").exists()


def test_the_import_hands_the_design_css_to_ui_detect(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, list[str], bool]] = []

    def detect_from_css(root: Path, css: list[Path], *, dry_run: bool) -> str:
        calls.append((root, [p.name for p in css], dry_run))
        return "themed from css/site.css"

    monkeypatch.setattr(ui_command, "detect_from_css", detect_from_css, raising=False)
    result = ok("import", "design", str(BAKERY), "--app", "website")
    assert calls == [(project, ["site.css"], False)]
    assert "staff app theme: themed from css/site.css" in result.output


def test_the_staff_app_and_admin_take_the_design_colours(
    project: Path, tmp_path: Path
) -> None:
    design = tmp_path / "branded"
    shutil.copytree(BAKERY, design)
    css = design / "css" / "site.css"
    css.write_text(":root { --brand: #8a3b12; }\n" + css.read_text(encoding="utf-8"), encoding="utf-8")

    dry = ok("import", "design", str(design), "--app", "website", "--dry-run")
    assert "staff app theme: would write src/karni-theme.css" in dry.output
    assert not (project / "frontend" / "src" / "karni-theme.css").exists()

    result = ok("import", "design", str(design), "--app", "website")
    assert "staff app theme: wrote src/karni-theme.css" in result.output
    theme = (project / "frontend" / "src" / "karni-theme.css").read_text(encoding="utf-8")
    assert "#8a3b12" in theme


def test_an_edited_theme_is_kept_on_import(project: Path) -> None:
    theme = project / "frontend" / "src" / "karni-theme.css"
    theme.write_text(":root { --karni-color-primary: #123456; }\n", encoding="utf-8")
    result = ok("import", "design", str(BAKERY), "--app", "website")
    assert "staff app theme: kept src/karni-theme.css" in result.output
    assert "--force" in result.output
    assert "#123456" in theme.read_text(encoding="utf-8")


def test_a_project_without_a_frontend_is_not_themed(project: Path) -> None:
    shutil.rmtree(project / "frontend")
    result = ok("import", "design", str(BAKERY), "--app", "website")
    assert "staff app theme" not in result.output
