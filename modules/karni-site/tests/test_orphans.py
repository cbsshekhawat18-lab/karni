"""Blocks no template shows any more: the admin marks and filters them, a command lists and
removes them, and karni check warns (SITE025). A key the scan cannot read is never an orphan."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.template import engines
from django.test import Client, RequestFactory
from django.urls import reverse
from pytest_django import Settings

from karni_site import checks, orphans
from karni_site.models import Block

pytestmark = pytest.mark.django_db


@pytest.fixture
def folder(settings: Settings, tmp_path: Path) -> Iterator[Path]:
    """The project's templates: one folder, empty until a test writes in it."""
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["DIRS"] = [tmp_path]
    settings.TEMPLATES = templates
    orphans.forget()
    yield tmp_path
    orphans.forget()


def write(folder: Path, name: str, source: str) -> None:
    (folder / name).write_text("{% load karni_site %}" + source, encoding="utf-8")
    orphans.forget()  # the same second, the same size: a test is faster than a file's clock


def render(name: str) -> str:
    request = RequestFactory().get("/")
    return str(engines["django"].get_template(name).render({}, request))


def block(key: str, text: str = "Text", default: str | None = None) -> Block:
    """A stored block. With ``default``, someone edited it: it shows ``text`` instead."""
    return Block.objects.create(
        key=key, html=text, default_html=text if default is None else default
    )


def statuses(*keys: str) -> dict[str, bool | None]:
    return orphans.classify(keys)


def test_a_block_whose_tag_left_the_template_is_an_orphan_in_the_admin(
    folder: Path, owner: Any
) -> None:
    write(
        folder,
        "page.html",
        '<h1>{% editable "home.title" %}Old heading{% endeditable %}</h1>'
        '<p>{% editable "home.intro" %}Kept text{% endeditable %}</p>',
    )
    render("page.html")
    write(folder, "page.html", '<p>{% editable "home.intro" %}Kept text{% endeditable %}</p>')
    assert statuses("home.title", "home.intro") == {"home.title": False, "home.intro": True}

    admin = Client()
    admin.force_login(owner)
    listing = reverse("admin:karni_site_block_changelist")
    response = admin.get(listing)
    assert response.status_code == 200
    shown = {row.key: row.in_template for row in response.context["cl"].result_list}
    assert shown == {"home.title": False, "home.intro": True}
    assert "in a template" in response.content.decode()
    orphan_rows = admin.get(listing, {"in_template": "no"}).context["cl"].result_list
    assert [row.key for row in orphan_rows] == ["home.title"]
    live_rows = admin.get(listing, {"in_template": "yes"}).context["cl"].result_list
    assert [row.key for row in live_rows] == ["home.intro"]

    gone = Block.objects.get(key="home.title")
    page = admin.get(reverse("admin:karni_site_block_change", args=[gone.pk])).content.decode()
    assert "No page shows this block" in page
    kept = Block.objects.get(key="home.intro")
    page = admin.get(reverse("admin:karni_site_block_change", args=[kept.pk])).content.decode()
    assert "No page shows this block" not in page


def test_a_key_named_anywhere_in_a_tag_is_in_a_template_and_a_comment_is_not(
    folder: Path, settings: Settings
) -> None:
    write(
        folder,
        "page.html",
        '{% load karni_forms %}{% editable "home.title" %}Hi{% endeditable %}\n'
        # A tag of the project's own around blocks.text(), and keys handed to a partial.
        '{% story_block "about.story" %}\n'
        '{% include "partials/cta.html" with key="about.cta" %}\n'
        # The form's labels, button and sent message are blocks under its editable= key.
        '{% karni_form "subscriber" editable="home.signup" %}\n'
        '{# {% editable "home.old" %}Gone{% endeditable %} #}\n'
        '{% comment %}{% editable "home.older" %}Gone{% endeditable %}{% endcomment %}\n',
    )
    assert statuses(
        "home.title",
        "about.story",
        "about.cta",
        "home.signup.button",
        "home.signup.email.label",
        "home.old",
        "home.older",
        "promo.banner",
    ) == {
        "home.title": True,
        "about.story": True,
        "about.cta": True,
        "home.signup.button": True,
        "home.signup.email.label": True,
        "home.old": False,
        "home.older": False,
        "promo.banner": False,
    }
    # A key code of the project's own stores (karni_site.blocks.text() in a view).
    settings.KARNI_SITE_CODE_BLOCKS = ["promo.*"]
    assert statuses("promo.banner", "home.old") == {"promo.banner": True, "home.old": False}


def test_a_key_built_when_the_page_renders_is_not_seen_never_an_orphan(folder: Path) -> None:
    write(
        folder,
        "team.html",
        '{% for member in team %}{% editable "team."|add:member %}A bio{% endeditable %}'
        "{% endfor %}"
        '{% karni_form "subscriber" editable=form_key %}',
    )
    write(folder, "home.html", '{% editable "home.title" %}Hi{% endeditable %}')
    found = orphans.scan()
    assert [unread.prefix for unread in found.unread] == ["team.", ""]
    assert found.unread[0].where == f"{folder / 'team.html'}:1"
    # The form's key is a variable: any key could be one of its blocks.
    assert statuses("team.ada", "home.gone") == {"team.ada": None, "home.gone": None}

    write(
        folder,
        "team.html",
        '{% for member in team %}{% editable "team."|add:member %}A bio{% endeditable %}'
        "{% endfor %}",
    )
    # Only the keys under the quoted start are unsure now.
    assert statuses("team.ada", "home.gone") == {"team.ada": None, "home.gone": False}

    write(folder, "team.html", "{% editable block_key %}Any{% endeditable %}")
    assert statuses("team.ada", "home.gone", "home.title") == {
        "team.ada": None,
        "home.gone": None,
        "home.title": True,
    }


def test_without_any_block_tag_nothing_can_be_judged(folder: Path) -> None:
    write(folder, "page.html", "<p>{{ site.name }}</p>")
    assert orphans.scan().tags == 0
    assert statuses("home.title") == {"home.title": None}


def run(*args: str) -> str:
    out = StringIO()
    call_command("karni_site_orphans", *args, stdout=out, stderr=out)
    return out.getvalue()


def test_the_command_lists_by_default_and_deletes_only_with_a_flag(folder: Path) -> None:
    write(
        folder,
        "page.html",
        '{% editable "home.title" %}Hi{% endeditable %}'
        '{% editable "team."|add:member %}A bio{% endeditable %}',
    )
    block("home.title")
    block("home.gone", "Old text")
    block("home.changed", "A client's text", default="The template's text")
    block("team.ada")

    listed = run()
    assert "2 block(s) are in no template" in listed
    assert "home.gone" in listed and "text, follows the template" in listed
    assert "home.changed" in listed and "text, edited" in listed
    assert "Not seen: 1 block(s)" in listed and "team.ada" in listed
    assert f"{folder / 'page.html'}:1" in listed
    assert "Nothing deleted: a dry run. --delete removes the 1 nobody edited." in listed
    assert "The 1 someone edited need --include-edited too" in listed
    assert Block.objects.count() == 4

    alone = run("--include-edited")
    assert "Nothing deleted: a dry run (--include-edited acts only with --delete)." in alone
    assert Block.objects.count() == 4

    deleted = run("--delete")
    assert "Deleted 1 block(s): home.gone." in deleted
    assert "Kept 1 that someone edited: home.changed." in deleted
    assert sorted(Block.objects.values_list("key", flat=True)) == [
        "home.changed",
        "home.title",
        "team.ada",
    ]
    # A soft delete, as the admin's: the row and its history stay.
    assert Block.objects.without("soft_delete", reason="the test").filter(key="home.gone").exists()

    assert "Deleted 1 block(s): home.changed." in run("--delete", "--include-edited")
    assert sorted(Block.objects.values_list("key", flat=True)) == ["home.title", "team.ada"]
    assert "no orphans" in run()


def test_karni_check_warns_and_never_fails(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(folder, "page.html", '{% editable "home.title" %}Hi{% endeditable %}')
    block("home.title")
    assert checks.run_checks() == []
    assert "SITE025" not in capsys.readouterr().out

    block("home.gone")
    assert checks.run_checks() == []
    printed = capsys.readouterr().out
    assert printed.startswith("site: SITE025: 1 block(s) are in no template, so no page shows")
    assert "home.gone" in printed and "manage.py karni_site_orphans" in printed
