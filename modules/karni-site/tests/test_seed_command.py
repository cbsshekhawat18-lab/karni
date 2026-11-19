"""manage.py karni_site_seed, and seeding without change-history entries.

A template's defaults are nobody's edit: storing them, on a visit or in a deploy, leaves
no entry in the change history, and an edit in the admin still does.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from karni.audit.models import ChangeLog
from karni.exceptions import KarniCommandError

from karni_site.models import Block, Menu, MenuItem, SiteSettings
from tests import seed_urls

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _site(settings: Any) -> Iterator[None]:
    settings.ROOT_URLCONF = "tests.seed_urls"
    yield
    seed_urls.FAIL = False


def seed(*args: str) -> str:
    out = StringIO()
    call_command("karni_site_seed", *args, stdout=out, stderr=out)
    return out.getvalue()


def entries_for(*models: Any) -> int:
    types = [ContentType.objects.get_for_model(model) for model in models]
    return ChangeLog.objects.filter(content_type__in=types).count()


def test_a_visit_stores_the_defaults_without_history_entries() -> None:
    response = Client().get("/")
    assert response.status_code == 200
    assert Block.objects.count() == 3
    assert Menu.objects.filter(name="main").exists()
    assert SiteSettings.objects.get().name == "Harbour Notes"
    assert entries_for(Block, Menu, MenuItem, SiteSettings) == 0


def test_an_edit_is_still_recorded() -> None:
    # The admin, the API and a shell all save the model: the change history sees each save.
    Client().get("/")
    block = Block.objects.get(key="home.title")
    block.html = "Notes from the quay"
    block.save()
    item = MenuItem.objects.get(title="About")
    item.title = "Who we are"
    item.save()
    site = SiteSettings.objects.get()
    site.phone = "09876 543210"
    site.save()
    entry = ChangeLog.objects.get(content_type=ContentType.objects.get_for_model(Block))
    assert entry.action == "update"
    assert entry.diff["html"] == ["Notes from the harbour", "Notes from the quay"]
    assert entries_for(MenuItem) == 1 and entries_for(SiteSettings) == 1


def test_the_command_stores_every_pages_defaults_before_a_visit(settings: Any) -> None:
    settings.KARNI_SITE_SEED_ON_RENDER = False
    out = seed()
    assert "rendered 3 page(s)" in out
    assert "New: 4 blocks, 1 menus, 2 menu items, 1 site settings." in out
    assert set(Block.objects.values_list("key", flat=True)) == {
        "shared.footer",
        "home.title",
        "home.intro",
        "about.title",
    }
    assert [item.title for item in MenuItem.objects.order_by("order")] == ["Home", "About"]
    assert entries_for(Block, Menu, MenuItem, SiteSettings) == 0
    # The first visitor's request writes nothing.
    with CaptureQueriesContext(connection) as queries:
        assert Client().get("/about/").status_code == 200
    writes = [q["sql"] for q in queries.captured_queries if not q["sql"].startswith("SELECT")]
    assert writes == []
    again = seed()
    assert "New: nothing." in again


def test_the_command_follows_a_changed_default() -> None:
    seed()
    block = Block.objects.get(key="home.intro")
    Block.objects.filter(pk=block.pk).update(html="Old text", default_html="Old text")
    from karni_site import blocks

    blocks.forget("home")
    seed()
    block.refresh_from_db()
    assert block.html == "What the tide brings in."


def test_a_page_that_fails_stops_the_command() -> None:
    seed_urls.FAIL = True
    with pytest.raises(KarniCommandError, match="SITE024") as failed:
        seed()
    assert "/broken/" in str(failed.value)
    assert Block.objects.filter(key="home.title").exists(), "the other pages are seeded"
    out = seed("--keep-going")
    assert "SITE024" in out and "/broken/" in out
