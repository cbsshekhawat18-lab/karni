"""``karni import design``: {% karni_seo %} where the design's head tags were, and sized images.

The college design has share tags in its head (one shared by every page, one
a page has of its own), a hero image loaded at once, cards loaded lazily, an
image with only a width, a picture with its own sources, a small badge and
an SVG logo. The bakery's images are not real image files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from io import BytesIO
from pathlib import Path

import pytest

from karni_cli.design import images, site

from .test_import_design import BAKERY, DESIGNS, project  # noqa: F401
from .test_make import ok

COLLEGE = DESIGNS / "college"


def img(markup: str, src: str) -> str:
    match = re.search(
        r"<img src=\"\{% static 'website/" + re.escape(src) + r"' %\}\"[^>]*>", markup
    )
    assert match is not None, src
    return match.group(0)


def test_karni_seo_takes_the_place_of_the_designs_head_tags() -> None:
    plan = site.plan(COLLEGE, "website")
    base = plan.templates["templates/website/base.html"]
    assert (
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  {% karni_seo %}<title>{% block title %}Hillside School of Arts{% endblock %}</title>\n"
        '  <meta name="description" content="{% block description %}{% endblock %}">\n'
        '  <meta name="twitter:card" content="summary_large_image">'
        "{% block seo %}{% endblock %}{% endkarni_seo %}\n"
        '  <meta name="theme-color" content="#228833">\n'
    ) in base
    # og:title is written from each page's title, the canonical link from its address.
    assert "og:title" not in base and "canonical" not in base
    home = plan.templates["templates/website/home.html"]
    assert (
        '{% block seo %}<meta property="og:image" content="{% static \'website/img/share.jpg\' %}">'
        "{% endblock %}\n"
    ) in home
    courses = plan.templates["templates/website/courses.html"]
    assert "{% static 'website/img/course-art.jpg' %}\">{% endblock %}" in courses
    assert "og:title" not in home + courses and "{% block head %}" not in home + courses


def test_a_design_without_share_tags_gets_the_tag_around_its_title() -> None:
    base = site.plan(BAKERY, "website").templates["templates/website/base.html"]
    assert (
        "  {% karni_seo %}<title>{% block title %}Crumb &amp; Co{% endblock %}</title>\n"
        '  <meta name="description" content="{% block description %}{% endblock %}">'
        "{% block seo %}{% endblock %}{% endkarni_seo %}\n"
        '  <link rel="icon" href="{% static \'website/img/logo.svg\' %}">'
    ) in base


def _bakery_with(tmp_path: Path, head: str = "", files: tuple[str, ...] = ()) -> Path:
    design = tmp_path / "design"
    shutil.copytree(BAKERY, design)
    for page in design.glob("*.html"):
        page.write_text(page.read_text().replace('  <link rel="icon"', head + '  <link rel="icon"'))
    for name in files:
        (design / name).write_bytes((design / "img" / "hero.jpg").read_bytes())
    return design


def test_a_share_image_every_page_has_is_the_sites_default(tmp_path: Path) -> None:
    design = _bakery_with(
        tmp_path, '  <meta property="og:image" content="img/share.jpg">\n', ("img/share.jpg",)
    )
    plan = site.plan(design, "website", editable=True)
    base = plan.templates["templates/website/base.html"]
    defaults = base.split("{% site_defaults ", 1)[1].split(" %}", 1)[0]
    assert 'share_image="website/img/share.jpg"' in defaults
    assert (
        'logo="website/img/logo.svg"' in defaults and 'favicon="website/img/logo.svg"' in defaults
    )
    # The template no longer holds the tag, so the client's upload replaces the design's.
    assert "og:image" not in base
    assert any("share image: the og:image every page has (img/share.jpg)" in n for n in (
        plan.editable.notes if plan.editable else []
    ))  # fmt: skip
    # A plain import keeps the tag inside {% karni_seo %} as the default.
    plain = site.plan(design, "website").templates["templates/website/base.html"]
    assert '<meta property="og:image" content="{% static \'website/img/share.jpg\' %}">' in plain


def test_an_unused_image_named_for_sharing_is_the_default_share_image(tmp_path: Path) -> None:
    design = _bakery_with(tmp_path, files=("img/og-image.png",))
    base = site.plan(design, "website", editable=True).templates["templates/website/base.html"]
    assert 'share_image="website/img/og-image.png"' in base
    # Two images named for sharing: no guess.
    two = _bakery_with(tmp_path / "two", files=("img/og-image.png", "img/share.jpg"))
    base = site.plan(two, "website", editable=True).templates["templates/website/base.html"]
    assert "share_image=" not in base


def test_images_get_their_size_and_smaller_copies() -> None:
    plan = site.plan(COLLEGE, "website")
    home = plan.templates["templates/website/home.html"]
    hero = img(home, "img/hero.jpg")
    assert 'width="1600" height="900" data-karni-image="natural"' in hero
    widths = [320, 480, 640, 800, 960, 1280, 1600]
    srcset = ", ".join(f"{{% static 'website/img/hero.jpg.{w}w.webp' %}} {w}w" for w in widths)
    # The copies below its width, and the whole picture in WebP.
    assert f'srcset="{srcset}"' in hero
    assert 'sizes="(max-width: 1600px) 100vw, 1600px"' in hero
    # A card loads lazily: the browser picks the copy that fits the card.
    card = img(home, "img/course-art.jpg")
    assert 'width="1200" height="800" data-karni-image srcset=' in card
    assert 'sizes="auto, (max-width: 1200px) 100vw, 1200px"' in card
    assert "course-music.png.900w.webp' %} 900w\"" in img(home, "img/course-music.png")
    # The designer's width stays, the height follows.
    teacher = img(home, "img/teacher.jpg")
    assert 'width="320" alt="Our head teacher" height="320" data-karni-image srcset=' in teacher
    assert 'sizes="(max-width: 320px) 100vw, 320px"' in teacher
    assert "teacher.jpg.640w.webp' %} 640w\"" in teacher
    # Small, or with sources of its own: sized, no copies.
    badge = img(home, "img/badge.jpg")
    assert badge.endswith('width="200" height="100" data-karni-image="natural">')
    campus = img(home, "img/campus.jpg")
    assert "srcset" not in campus and 'width="1000" height="500"' in campus
    logo = img(plan.templates["templates/website/base.html"], "img/logo.svg")
    assert logo.endswith('width="160" height="40" data-karni-image="natural">')
    assert plan.copies == {
        "img/hero.jpg": [320, 480, 640, 800, 960, 1280, 1600],
        "img/course-art.jpg": [320, 480, 640, 800, 960, 1200],
        "img/course-music.png": [320, 480, 640, 800, 900],
        "img/teacher.jpg": [320, 480, 640],
    }
    assert plan.design["images"]["copies"]["img/teacher.jpg"] == [320, 480, 640]
    assert (
        "images: 21 smaller WebP copies of 4 images for their srcset, and width and height on "
        "every image of the design."
    ) in plan.notes


def test_without_pillow_images_are_sized_without_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "pillow_available", lambda: False)
    plan = site.plan(COLLEGE, "website")
    home = plan.templates["templates/website/home.html"]
    assert "srcset=\"{% static 'website/img/hero" not in home
    assert 'width="1600" height="900" data-karni-image="natural"' in img(home, "img/hero.jpg")
    assert plan.copies == {}
    assert (
        "images: 4 image(s) are wider than 320 pixels and could load smaller copies. Install "
        "Pillow where karni runs (pip install pillow) and import again to write them."
    ) in plan.notes


def test_an_image_whose_size_cannot_be_read_is_reported() -> None:
    plan = site.plan(BAKERY, "website")
    assert (
        "images: the size of 1 could not be read from its file, so it has no width and height "
        "(karni check --seo reports it): about.html:29: img/oven.jpg"
    ) in plan.notes


def test_the_import_writes_the_copies_once(project: Path) -> None:  # noqa: F811
    from PIL import Image

    result = ok("import", "design", str(COLLEGE), "--app", "website")
    assert "wrote    21 smaller WebP image copies under website/static/website/" in result.output
    static = project / "website" / "static" / "website" / "img"
    copy = Image.open(BytesIO((static / "hero.jpg.640w.webp").read_bytes()))
    assert (copy.format, copy.size) == ("WEBP", (640, 360))
    assert (static / "course-music.png.320w.webp").is_file()
    assert not (static / "badge.jpg.320w.webp").exists()
    record = json.loads((project / ".karni" / "design.json").read_text())
    assert record["images"]["copies"]["img/hero.jpg"] == [320, 480, 640, 800, 960, 1280, 1600]
    full = Image.open(BytesIO((static / "hero.jpg.1600w.webp").read_bytes()))
    assert (full.format, full.size) == ("WEBP", (1600, 900))
    stamp = (static / "hero.jpg.640w.webp").stat().st_mtime_ns
    os.utime(static / "hero.jpg.640w.webp", ns=(stamp - 10**9, stamp - 10**9))
    again = ok("import", "design", str(COLLEGE), "--app", "website")
    assert "smaller WebP image copies" not in again.output
    assert (static / "hero.jpg.640w.webp").stat().st_mtime_ns == stamp - 10**9
    # The page's head is the tag's: the base template renders it.
    base = (project / "website" / "templates" / "website" / "base.html").read_text()
    assert base.count("{% karni_seo %}") == 1
