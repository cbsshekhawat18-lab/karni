"""{% karni_seo %}: the page's tags from the admin, the view, the row, the template, the site."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from django.template import Context, RequestContext, Template, TemplateSyntaxError
from django.test import Client, RequestFactory
from django.urls import resolve
from pytest_django import Settings

from karni_site import jsonld, metadata, views
from karni_site.models import OpeningHours, PageSeo, SiteSettings, SocialLink
from tests.seo_helpers import seo_site, upload  # noqa: F401
from tests.testapp.models import Project

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("seo_site")]


def head(html: str) -> str:
    return html.split("<head>", 1)[1].split("</head>", 1)[0]


def meta(html: str, key: str) -> str | None:
    match = re.search(rf'<meta (?:name|property)="{re.escape(key)}" content="([^"]*)">', html)
    return match.group(1) if match else None


def script(html: str) -> dict[str, Any]:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert match is not None
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def test_the_designs_own_tags_are_the_defaults() -> None:
    page = Client().get("/").content.decode()
    tags = head(page)
    assert tags.count("<title>") == 1 and "<title>Crumb &amp; Co, the bakery</title>" in tags
    assert meta(page, "description") == "Sourdough, cakes and coffee in the old town."
    assert '<link rel="canonical" href="http://testserver/">' in tags
    assert meta(page, "og:title") == "Crumb &amp; Co, the bakery"
    assert meta(page, "og:url") == "http://testserver/"
    assert meta(page, "og:site_name") == "Crumb &amp; Co"
    assert meta(page, "og:type") == "website"
    # The template's own og:image is the share image, made absolute.
    assert meta(page, "og:image") == "http://testserver/static/seo/share.jpg"
    assert meta(page, "twitter:card") == "summary_large_image"
    assert meta(page, "twitter:title") == "Crumb &amp; Co, the bakery"
    # A tag the tag does not cover stays, after the generated ones.
    assert tags.index('name="theme-color"') > tags.index("application/ld+json")
    assert 'name="robots"' not in tags
    # One per page: the design's og:image was replaced, not repeated.
    assert tags.count('property="og:image"') == 1


def test_the_admin_entry_wins_over_everything(settings: Settings) -> None:
    PageSeo.objects.create(
        route="seo:about",
        title="Our bakers",
        description="Meet the people behind the oven.",
        share_image=upload("team.jpg", 1600, 900),
        noindex=True,
    )
    page = Client().get("/about/").content.decode()
    assert "<title>Our bakers</title>" in page
    assert meta(page, "description") == "Meet the people behind the oven."
    assert '<meta name="robots" content="noindex">' in page
    image = meta(page, "og:image")
    assert image is not None and image.startswith("http://testserver/media/karni_site/images/")
    assert meta(page, "twitter:card") == "summary_large_image"


def test_a_row_gives_its_page_title_description_and_image(
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        Project.objects.create(
            title="Wedding cake",
            slug="wedding",
            summary="<p>A three tier <b>cake</b> for a summer wedding in the hills, "
            + "with fruit and flowers from the garden of the family farm. " * 4
            + "</p>",
            photo=upload("cake.jpg", 2000, 1000),
        )
    page = Client().get("/projects/wedding/").content.decode()
    assert "<title>Wedding cake | Crumb &amp; Co</title>" in page
    description = meta(page, "description")
    assert description is not None and description.startswith("A three tier cake for a summer")
    assert len(description) <= 160 and description.endswith("…")
    # The share image is the copy closest above 1200 pixels, with its size.
    image = meta(page, "og:image")
    assert image is not None and image.endswith("cake.jpg.1280w.webp")
    assert (meta(page, "og:image:width"), meta(page, "og:image:height")) == ("1280", "640")


def test_a_title_that_names_the_site_is_not_given_it_twice(settings: Settings) -> None:
    Project.objects.create(title="Crumb & Co at the market", slug="market")
    page = Client().get("/projects/market/").content.decode()
    assert "<title>Crumb &amp; Co at the market</title>" in page
    settings.KARNI_SITE_TITLE_FORMAT = "{site}: {title}"
    Project.objects.create(title="Bread school", slug="school")
    page = Client().get("/projects/school/").content.decode()
    assert "<title>Crumb &amp; Co: Bread school</title>" in page


def request(path: str) -> Any:
    found = RequestFactory().get(path)
    found.resolver_match = resolve(path)
    return found


def render(source: str, context: dict[str, Any] | None = None, path: str = "/about/") -> str:
    template = Template("{% load karni_site %}" + source)
    return template.render(RequestContext(request(path), context or {}))


def test_the_sites_settings_are_the_last_default() -> None:
    SiteSettings.objects.create(name="Elm Street Clinic", tagline="Family care, six days a week.")
    page = render("{% karni_seo %}{% endkarni_seo %}")
    assert "<title>Elm Street Clinic</title>" in page
    assert meta(page, "description") == "Family care, six days a week."
    assert meta(page, "twitter:card") == "summary"


def test_the_templates_share_image_and_logo_are_defaults_until_one_is_uploaded(
    django_capture_on_commit_callbacks: Any,
) -> None:
    source = (
        '{% site_defaults name="Elm Street Clinic" share_image="website/img/share.jpg" '
        'logo="website/img/logo.png" favicon="/favicon.ico" %}{% karni_seo %}{% endkarni_seo %}'
    )
    page = render(source)
    assert meta(page, "og:image") == "http://testserver/static/website/img/share.jpg"
    assert meta(page, "twitter:card") == "summary_large_image"
    who = script(page)["@graph"][1]
    assert who["logo"] == "http://testserver/static/website/img/logo.png"
    assert who["image"] == "http://testserver/static/website/img/share.jpg"
    row = SiteSettings.objects.get()
    # The file fields stay the client's: empty until an upload.
    assert not row.share_image and not row.logo and not row.favicon
    assert row.seeded["static"] == {
        "share_image": "website/img/share.jpg",
        "logo": "website/img/logo.png",
        "favicon": "/favicon.ico",
    }
    with django_capture_on_commit_callbacks(execute=True):
        row.share_image = upload("summer.jpg", 1600, 900)
        row.save()
    page = render(source)
    assert "/media/" in (meta(page, "og:image") or "") and "summer" in (
        meta(page, "og:image") or ""
    )
    assert script(page)["@graph"][1]["logo"].endswith("/static/website/img/logo.png")
    with pytest.raises(TemplateSyntaxError, match="a static path for favicon, logo, share_image"):
        Template('{% load karni_site %}{% site_defaults banner="x.jpg" %}')


def test_a_view_passes_its_own_values() -> None:
    page = render(
        "{% karni_seo %}<title>Template title</title>{% endkarni_seo %}",
        {"seo": {"title": "From the view", "description": "Chosen by the view.", "noindex": True}},
    )
    assert "<title>From the view</title>" in page and "Template title" not in page
    assert meta(page, "description") == "Chosen by the view."
    assert '<meta name="robots" content="noindex">' in page


def test_the_error_pages_are_hidden_and_have_no_canonical() -> None:
    response = views.page_not_found(request("/about/"), None, template_name="seo/404.html")
    page = response.content.decode()
    assert response.status_code == 404
    assert "<title>Page not found</title>" in page
    assert '<meta name="robots" content="noindex">' in page
    assert 'rel="canonical"' not in page and 'property="og:url"' not in page


def test_karni_seo_class_names_the_fields() -> None:
    class Event:
        class Karni:
            seo = {"title": "headline", "description": "teaser", "type": "article"}

        headline = "Harvest fair"
        teaser = "Stalls, music and bread."
        title = "not this one"

    assert metadata.object_values(Event()) == {
        "title": "Harvest fair",
        "description": "Stalls, music and bread.",
        "type": "article",
    }

    class Wrong:
        class Karni:
            seo = {"heading": "title"}

    with pytest.raises(Exception, match="SITE019"):
        metadata.object_values(Wrong())


def test_the_page_object_is_found_by_its_address() -> None:
    project = Project.objects.create(title="Rye", slug="rye")
    other = Project.objects.create(title="Spelt", slug="spelt")
    context = Context({"project": project, "others": [other], "featured": other})
    assert metadata.page_object(context, request("/projects/rye/")) == project
    assert metadata.page_object(Context({"object": other}), request("/about/")) == other
    assert metadata.page_object(Context({"featured": other}), request("/about/")) is None


def test_a_failure_shows_the_templates_own_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> None:
        raise RuntimeError("no")

    monkeypatch.setattr(metadata, "resolve", broken)
    page = render('{% karni_seo %}<title>Kept</title><meta name="x" content="y">{% endkarni_seo %}')
    assert page == '<title>Kept</title><meta name="x" content="y">'


def test_karni_seo_takes_nothing() -> None:
    with pytest.raises(TemplateSyntaxError, match="SITE019"):
        Template("{% load karni_site %}{% karni_seo title %}{% endkarni_seo %}")


def test_tags_it_does_not_cover_stay_in_place() -> None:
    page = render(
        '{% karni_seo %}\n  <title>A</title>\n  <meta name="twitter:site" content="@crumb">\n'
        '  <meta property="og:title" content="Old"><link rel="canonical" href="/elsewhere/">'
        "{% endkarni_seo %}"
    )
    assert '<meta name="twitter:site" content="@crumb">' in page
    assert 'content="Old"' not in page
    assert '<link rel="canonical" href="http://testserver/elsewhere/">' in page
    assert page.startswith('\n  <title>A</title>\n  <link rel="canonical"')


# JSON-LD


@pytest.fixture
def business() -> SiteSettings:
    site = SiteSettings.objects.create(
        name="Crumb </script> Co",
        tagline="Bread from our own oven.",
        address="1 Mill Lane\nOld Town\nAB1 2CD",
        phone="(0123) 456 789",
        phone_link="+440123456789",
        email="hello@example.com",
        map_url="https://maps.example.com/crumb",
        logo=upload("logo.jpg", 200, 80),
    )
    OpeningHours.objects.create(site=site, days="Mon to Fri", times="7:00 to 18:00", order=0)
    OpeningHours.objects.create(site=site, days="Saturday", times="8am - 1pm", order=1)
    OpeningHours.objects.create(site=site, days="Sunday", times="Closed", order=2)
    SocialLink.objects.create(site=site, name="Instagram", url="https://instagram.com/crumb")
    return site


def test_the_json_ld_describes_the_business(business: SiteSettings) -> None:
    page = render("{% karni_seo %}<title>x</title>{% endkarni_seo %}")
    assert "</script> Co" not in page.split("application/ld+json", 1)[1].split("</script>", 1)[0]
    data = script(page)
    assert data["@context"] == "https://schema.org"
    website, who = data["@graph"]
    assert website["@type"] == "WebSite" and website["publisher"] == {"@id": who["@id"]}
    assert who["@type"] == "LocalBusiness"
    assert who["name"] == "Crumb </script> Co"
    assert who["url"] == "http://testserver/"
    assert who["telephone"] == "+440123456789"
    assert who["email"] == "hello@example.com"
    assert who["address"] == {
        "@type": "PostalAddress",
        "streetAddress": "1 Mill Lane, Old Town, AB1 2CD",
    }
    assert who["hasMap"] == "https://maps.example.com/crumb"
    assert who["sameAs"] == ["https://instagram.com/crumb"]
    assert who["logo"].startswith("http://testserver/media/") and who["image"] == who["logo"]
    assert who["openingHoursSpecification"] == [
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "07:00",
            "closes": "18:00",
        },
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": "Saturday",
            "opens": "08:00",
            "closes": "13:00",
        },
    ]


def test_the_schema_type_is_a_setting(business: SiteSettings, settings: Settings) -> None:
    settings.KARNI_SITE_SCHEMA_TYPE = "Bakery"
    who = script(render("{% karni_seo %}{% endkarni_seo %}"))["@graph"][1]
    assert who["@type"] == "Bakery" and "openingHoursSpecification" in who
    settings.KARNI_SITE_SCHEMA_TYPE = "Organization"
    who = script(render("{% karni_seo %}{% endkarni_seo %}"))["@graph"][1]
    assert who["@type"] == "Organization" and "openingHoursSpecification" not in who
    settings.KARNI_SITE_SCHEMA_TYPE = None
    assert "ld+json" not in render("{% karni_seo %}{% endkarni_seo %}")


def test_without_a_name_there_is_no_json_ld() -> None:
    assert jsonld.build(None, SiteSettings()) is None


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ("Mon to Fri", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]),
        ("Monday - Wednesday", ["Monday", "Tuesday", "Wednesday"]),
        ("Sat, Sun", ["Saturday", "Sunday"]),
        ("Fri–Mon", ["Friday", "Saturday", "Sunday", "Monday"]),
        ("Daily", list(jsonld._DAY_NAMES)),
        ("weekends", ["Saturday", "Sunday"]),
        ("Lundi", None),
    ],
)
def test_days_are_read(days: str, expected: list[str] | None) -> None:
    assert jsonld.parse_days(days) == expected


@pytest.mark.parametrize(
    ("times", "expected"),
    [
        ("9:00 to 17:00", [("09:00", "17:00")]),
        ("9am - 5.30pm", [("09:00", "17:30")]),
        ("09.00–12.00, 13.00–18.00", [("09:00", "12:00"), ("13:00", "18:00")]),
        ("noon to midnight", [("12:00", "00:00")]),
        ("Closed", []),
        ("by appointment", None),
    ],
)
def test_times_are_read(times: str, expected: list[tuple[str, str]] | None) -> None:
    assert jsonld.parse_times(times) == expected


# <meta name="generator">: tools that list a site's technologies see Karni


def test_every_page_says_it_runs_on_karni() -> None:
    page = Client().get("/").content.decode()
    assert head(page).count('name="generator"') == 1
    assert meta(page, "generator") == "Karni"


def test_the_generator_names_no_version() -> None:
    page = render("{% karni_seo %}<title>Shop</title>{% endkarni_seo %}")
    assert meta(page, "generator") == "Karni"
    assert not re.search(r'name="generator" content="[^"]*\d', page)


def test_a_designs_own_generator_is_replaced(settings: Settings) -> None:
    source = (
        "{% karni_seo %}<title>Shop</title>"
        '<meta name="generator" content="Site Builder 7">{% endkarni_seo %}'
    )
    page = render(source)
    assert page.count('name="generator"') == 1 and meta(page, "generator") == "Karni"
    settings.KARNI_GENERATOR = "Karni, the Acme build"
    assert meta(render(source), "generator") == "Karni, the Acme build"


def test_an_empty_setting_leaves_the_designs_tag_alone(settings: Settings) -> None:
    settings.KARNI_GENERATOR = ""
    source = (
        "{% karni_seo %}<title>Shop</title>"
        '<meta name="generator" content="Site Builder 7">{% endkarni_seo %}'
    )
    page = render(source)
    assert meta(page, "generator") == "Site Builder 7"
    assert 'content="Karni"' not in page
    settings.KARNI_GENERATOR = None
    assert 'name="generator"' not in render("{% karni_seo %}<title>Shop</title>{% endkarni_seo %}")
