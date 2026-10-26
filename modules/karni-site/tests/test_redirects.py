"""Redirects from the admin: 301 and 302, query strings, loops refused, the cache."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from pytest_django import Settings

from karni_site.models import Redirect

pytestmark = pytest.mark.django_db


def test_a_permanent_and_a_temporary_redirect(client: Client) -> None:
    Redirect.objects.create(old_path="/old-menu/", new_url="/about/")
    Redirect.objects.create(old_path="/sale/", new_url="https://shop.example.com/", status=302)
    moved = client.get("/old-menu/")
    assert (moved.status_code, moved["Location"]) == (301, "/about/")
    sale = client.get("/sale/")
    assert (sale.status_code, sale["Location"]) == (302, "https://shop.example.com/")
    assert client.get("/never-was/").status_code == 404


def test_the_query_string_is_passed_on_or_matched_exactly(client: Client) -> None:
    Redirect.objects.create(old_path="/old/", new_url="/about/")
    Redirect.objects.create(old_path="/list/", new_url="/about/?view=all#top")
    Redirect.objects.create(old_path="/index.php?page=contact", new_url="/contact/")
    assert client.get("/old/?utm_source=mail").headers["Location"] == "/about/?utm_source=mail"
    assert client.get("/list/?page=2").headers["Location"] == "/about/?view=all&page=2#top"
    assert client.get("/index.php?page=contact").headers["Location"] == "/contact/"
    assert client.get("/index.php?page=other").status_code == 404


def test_a_page_that_exists_is_not_redirected_unless_asked(
    client: Client, settings: Settings
) -> None:
    Redirect.objects.create(old_path="/about/", new_url="/contact/", status=302)
    assert client.get("/about/").status_code == 200
    settings.KARNI_SITE_REDIRECTS_BEFORE_VIEWS = True
    assert client.get("/about/").headers["Location"] == "/contact/"


def test_loops_and_protected_addresses_are_refused() -> None:
    Redirect.objects.create(old_path="/a/", new_url="/b/")
    Redirect.objects.create(old_path="/b/", new_url="https://www.example.com/c/")
    with pytest.raises(ValidationError, match=r"in a circle: /c/ -> /a/ -> /b/ -> /c/") as loop:
        Redirect(old_path="/c/", new_url="/a/").full_clean()
    assert "SITE006" in str(loop.value)
    with pytest.raises(ValidationError, match="in a circle: /d/ -> /d/"):
        Redirect(old_path="d/", new_url="/d/?x=1").full_clean()
    # Another site's address ends the chain.
    Redirect(old_path="/e/", new_url="https://other.example.org/a/").full_clean()
    for old in ("/admin/login/", "/api/events/", "/static/site.css"):
        with pytest.raises(ValidationError, match="cannot be redirected"):
            Redirect(old_path=old, new_url="/").full_clean()
    with pytest.raises(ValidationError, match="new address"):
        Redirect(old_path="/f/", new_url="javascript:alert(1)").full_clean()


def test_old_addresses_are_kept_as_paths() -> None:
    redirect = Redirect.objects.create(
        old_path=" https://www.example.com/old/page/?x=1#frag", new_url=" /new/ "
    )
    assert (redirect.old_path, redirect.new_url) == ("/old/page/?x=1", "/new/")
    assert Redirect.objects.create(old_path="no-slash", new_url="/").old_path == "/no-slash"


def test_a_lookup_is_cached_and_a_save_clears_it(client: Client) -> None:
    redirect = Redirect.objects.create(old_path="/old/", new_url="/about/")
    client.get("/old/")
    with CaptureQueriesContext(connection) as queries:
        assert client.get("/old/").status_code == 301
    assert not any("karni_site_redirect" in q["sql"] for q in queries.captured_queries)
    redirect.new_url = "/contact/"
    redirect.save()
    assert client.get("/old/").headers["Location"] == "/contact/"
    redirect.delete()
    assert client.get("/old/").status_code == 404
