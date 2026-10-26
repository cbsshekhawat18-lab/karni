"""Per-page SEO entries: the lookup {% karni_seo %} calls."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import resolve

from karni_site.models import PageSeo
from karni_site.seo import lookup, page_seo

pytestmark = pytest.mark.django_db


def request_for(path: str) -> object:
    request = RequestFactory().get(path)
    request.resolver_match = resolve(path)
    return request


def test_a_path_entry_wins_over_its_routes_entry() -> None:
    every = PageSeo.objects.create(route="website:service", title="A service", noindex=True)
    one = PageSeo.objects.create(path="/services/shops/", title="Shops", description="Our shops.")
    assert page_seo(request_for("/services/shops/")) == one
    assert page_seo(request_for("/services/apps/")) == every
    assert page_seo(request_for("/about/")) is None
    assert page_seo(None) is None
    entry = lookup(route="website:service")
    assert entry is not None and entry.noindex is True


def test_an_answer_is_cached_and_a_save_clears_it() -> None:
    entry = PageSeo.objects.create(route="website:about", title="About")
    page_seo(request_for("/about/"))
    with CaptureQueriesContext(connection) as queries:
        found = page_seo(request_for("/about/"))
    assert found is not None and found.title == "About"
    assert len(queries) == 0
    entry.title = "About the bakery"
    entry.save()
    found = page_seo(request_for("/about/"))
    assert found is not None and found.title == "About the bakery"
    entry.delete()
    assert page_seo(request_for("/about/")) is None


def test_an_entry_names_a_route_or_a_path() -> None:
    with pytest.raises(ValidationError, match="not both"):
        PageSeo(route="website:about", path="/about/").full_clean()
    with pytest.raises(ValidationError, match="not both"):
        PageSeo(title="Nothing").full_clean()
    entry = PageSeo(path="about/?x=1")
    entry.full_clean()
    assert entry.path == "/about/"
    PageSeo.objects.create(route="website:home")
    with pytest.raises(IntegrityError), transaction.atomic():
        PageSeo.objects.create(route="website:home")
