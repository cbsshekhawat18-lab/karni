"""SiteSettings: `site` in every template, {% site_defaults %}, {% site_image %}, the cache."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.template import Context, Template, TemplateSyntaxError
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from pytest_django import Settings

from karni_site import sitesettings
from karni_site.context_processors import site
from karni_site.models import OpeningHours, SiteSettings, SocialLink

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def render(source: str, **context: Any) -> str:
    request = RequestFactory().get("/")
    template = Template("{% load static karni_site %}" + source)
    return template.render(Context({"request": request, **site(request), **context}))


def test_site_is_empty_but_safe_before_anything_is_stored() -> None:
    assert (
        render("[{{ site.name }}][{{ site.phone_href }}][{% for r in site.hours %}x{% endfor %}]")
        == "[][][]"
    )


def test_the_contact_page_seeds_the_details_and_shows_them(client: Client) -> None:
    page = client.get("/contact/").content.decode()
    row = SiteSettings.objects.get()
    assert (row.name, row.phone, row.phone_link, row.email) == (
        "Crumb & Co",
        "(0123) 456 789",
        "+440123456789",
        "hello@example.com",
    )
    assert '<a href="tel:+440123456789">(0123) 456 789</a>' in page
    assert '<a href="mailto:hello@example.com">hello@example.com</a>' in page
    assert '<a class="social" href="https://instagram.com/crumb">Instagram</a>' in page
    assert [(link.name, link.url) for link in SocialLink.objects.all()] == [
        ("Instagram", "https://instagram.com/crumb")
    ]
    # The client changes the phone, adds opening hours, removes Instagram.
    row.phone, row.phone_link = "0123 999", ""
    row.save()
    OpeningHours.objects.create(site=row, days="Tue to Sat", times="7:00 to 15:00")
    SocialLink.objects.get().delete()
    page = client.get("/contact/").content.decode()
    assert '<a href="tel:0123999">0123 999</a>' in page
    assert "<li>Tue to Sat: 7:00 to 15:00</li>" in page
    assert "Instagram" not in page  # removed, and the template does not bring it back
    assert not SocialLink.objects.exists()


def test_a_default_follows_the_template_until_someone_changes_it() -> None:
    render('{% site_defaults name="Elm Clinic" tagline="Family care" %}{{ site.name }}')
    shown = render(
        '{% site_defaults name="Elm Street Clinic" tagline="Care" %}'
        "{{ site.name }}|{{ site.tagline }}"
    )
    assert shown == "Elm Street Clinic|Care"
    row = SiteSettings.objects.get()
    row.tagline = "Care for the whole family"
    row.save()
    assert render(
        '{% site_defaults name="Elm Street Clinic" tagline="Other" %}{{ site.tagline }}'
    ) == ("Care for the whole family")
    assert row.seeded["name"] == "Elm Street Clinic"


def test_an_address_default_keeps_its_lines() -> None:
    template = Template(
        '{% load karni_site %}{% site_defaults address="12 Harbour Street\\nEaston EA1 2BD" %}'
        '<p>{{ site.address_lines|join:", " }}</p><p>{{ site.address|linebreaksbr }}</p>'
    )
    html = template.render(Context({}))
    assert sitesettings.get_site_settings().address == "12 Harbour Street\nEaston EA1 2BD"
    assert "<p>12 Harbour Street, Easton EA1 2BD</p>" in html
    assert "<p>12 Harbour Street<br>Easton EA1 2BD</p>" in html


def test_a_field_the_client_cleared_stays_cleared() -> None:
    render('{% site_defaults email="hi@example.com" %}')
    row = SiteSettings.objects.get()
    row.email = ""
    row.save()
    assert render('{% site_defaults email="hi@example.com" %}[{{ site.email }}]') == "[]"


def test_the_templates_opening_hours_seed_site_hours_once() -> None:
    loop = "{% for row in site.hours %}[{{ row.days }}|{{ row.times }}]{% endfor %}"
    first = (
        '{% site_defaults hours="Mon to Fri=8:00 to 18:00|Saturday=9:00 to 13:00|Sunday=Closed" %}'
    )
    assert render(first + loop) == (
        "[Mon to Fri|8:00 to 18:00][Saturday|9:00 to 13:00][Sunday|Closed]"
    )
    # Unchanged in the admin, the hours follow the template.
    later = '{% site_defaults hours="Mon to Fri=8:00 to 17:00|Sunday=Closed" %}'
    assert render(later + loop) == "[Mon to Fri|8:00 to 17:00][Sunday|Closed]"
    # Changed by the client, theirs stay; and hours they deleted are not added again.
    row = OpeningHours.objects.get(days="Sunday")
    row.times = "10:00 to 12:00"
    row.save()
    assert render(first + loop) == "[Mon to Fri|8:00 to 17:00][Sunday|10:00 to 12:00]"
    OpeningHours.objects.all().delete()
    sitesettings.forget()
    assert render(later + loop) == ""
    assert sitesettings.hours_rows(" Mon =9-5 | | Sun ") == [("Mon", "9-5"), ("Sun", "")]


def test_settings_are_one_cache_read_and_a_save_clears_them() -> None:
    render('{% site_defaults name="Studio" %}')
    render("{{ site.name }}")
    with CaptureQueriesContext(connection) as queries:
        assert (
            render('{% site_defaults name="Studio" %}{{ site.name }} {{ site.hours|length }}')
            == "Studio 0"
        )
    assert len(queries) == 0
    row = SiteSettings.objects.get()
    OpeningHours.objects.create(site=row, days="Mon", times="9 to 5")
    assert render("{% for r in site.hours %}{{ r }}{% endfor %}") == "Mon: 9 to 5"


def test_site_image_shows_the_design_until_a_file_is_uploaded() -> None:
    source = (
        '{% site_image "logo" %}<img class="logo" src="/static/logo.svg" alt="Studio">'
        "{% endsite_image %}"
    )
    assert render(source) == '<img class="logo" src="/static/logo.svg" alt="Studio">'
    row = SiteSettings.objects.get()
    assert row.seeded["images"] == {"logo": "/static/logo.svg"}
    row.logo = SimpleUploadedFile("logo.png", PNG)
    row.save()
    assert render(source) == f'<img class="logo" src="{row.logo.url}" alt="Studio">'
    favicon = (
        '<link rel="icon" href="{% site_image "favicon" url %}/static/i.png{% endsite_image %}">'
    )
    assert render(favicon) == '<link rel="icon" href="/static/i.png">'
    row.logo.delete(save=False)


def test_the_tags_are_checked_when_the_template_compiles() -> None:
    for bad in (
        '{% site_image "name" %}x{% endsite_image %}',
        "{% site_image logo %}x{% endsite_image %}",
        '{% site_defaults colour="red" %}',
        "{% site_defaults %}",
    ):
        with pytest.raises(TemplateSyntaxError, match="SITE003"):
            render(bad)


def test_the_phone_link_is_built_from_the_number() -> None:
    row = SiteSettings(phone="+44 (0)20 7946 0000")
    assert row.phone_href == "tel:+440207946000" + "0"
    assert SiteSettings(phone="020 7946 0000").phone_href == "tel:02079460000"
    assert SiteSettings(phone="x", phone_link="+1 831").phone_href == "tel:+1831"
    assert SiteSettings().phone_href == "" and SiteSettings().email_href == ""
    assert SiteSettings(address="1 Elm St\n\n  Springfield ").address_lines == [
        "1 Elm St",
        "Springfield",
    ]


def test_a_project_can_swap_the_model_name_through_the_setting(settings: Settings) -> None:
    settings.KARNI_SITE_SETTINGS_MODEL = "karni_site.Nowhere"
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="KARNI_SITE_SETTINGS_MODEL") as failed:
        sitesettings.settings_model()
    assert getattr(failed.value, "code", "") == "SITE009"
