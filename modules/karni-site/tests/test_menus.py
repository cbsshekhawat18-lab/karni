"""Menus: routes, model pages, URLs, nesting, the current page, seeding, validation, the cache."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection
from django.template import Context, Template, TemplateSyntaxError
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import resolve

from karni_site import menus
from karni_site.models import Menu, MenuItem
from tests.testapp.models import Service

pytestmark = pytest.mark.django_db

LOOP = (
    "{% load karni_site %}{% get_menu name as items %}"
    "{% for item in items %}[{{ item.title }}|{{ item.url }}"
    "{% if item.current %}|current{% endif %}{% if item.active %}|active{% endif %}"
    "{% if item.new_tab %}|new tab{% endif %}"
    "{% for child in item.children %}({{ child.title }}|{{ child.url }}"
    "{% if child.current %}|current{% endif %}){% endfor %}]{% endfor %}"
)


def request_for(path: str) -> Any:
    request = RequestFactory().get(path)
    request.resolver_match = resolve(path.split("?")[0].split("#")[0])
    return request


def render(path: str = "/", name: str = "header", source: str = LOOP) -> str:
    return Template(source).render(Context({"request": request_for(path), "name": name}))


@pytest.fixture
def services() -> list[Service]:
    return [
        Service.objects.create(title="Websites", slug="websites", order=1),
        Service.objects.create(title="Shops", slug="shops", order=2),
    ]


def test_items_point_at_routes_rows_and_addresses(services: list[Service]) -> None:
    menu = Menu.objects.create(name="header")
    home = MenuItem.objects.create(menu=menu, title="Home", route="website:home", order=0)
    shops = ContentType.objects.get_for_model(Service)
    MenuItem.objects.create(
        menu=menu, content_type=shops, object_id=str(services[1].pk), order=1, new_tab=True
    )
    MenuItem.objects.create(menu=menu, title="Map", url="https://maps.example.com/x", order=2)
    MenuItem.objects.create(
        menu=menu, title="Cakes", route="website:about", suffix="#cakes", order=3
    )
    MenuItem.objects.create(menu=menu, title="Hidden", url="/x/", enabled=False, order=4)
    MenuItem.objects.create(menu=menu, title="Web", route="website:service_web", parent=home)
    assert render("/about/") == (
        "[Home|/(Web|/services/web/)]"
        "[Shops|/services/shops/|new tab]"
        "[Map|https://maps.example.com/x]"
        "[Cakes|/about/#cakes|current|active]"
    )


def test_the_current_page_marks_the_item_and_its_parents(services: list[Service]) -> None:
    menu = Menu.objects.create(name="header")
    parent = MenuItem.objects.create(menu=menu, title="Services", url="/services/", order=0)
    parent.children_from = ContentType.objects.get_for_model(Service)
    parent.save()
    MenuItem.objects.create(menu=menu, title="Home", route="website:home", order=1)
    assert render("/services/shops/") == (
        "[Services|/services/|active(Websites|/services/websites/)(Shops|/services/shops/|current)]"
        "[Home|/]"
    )
    assert render("/") == (
        "[Services|/services/(Websites|/services/websites/)(Shops|/services/shops/)]"
        "[Home|/|current|active]"
    )


def test_an_item_stays_active_on_the_pages_under_its_path(
    services: list[Service], settings: Any
) -> None:
    # A list page's item, with its rows' pages under it and no children in the menu: a
    # model's detail pages that became one view keep their section marked.
    menu = Menu.objects.create(name="header")
    MenuItem.objects.create(menu=menu, title="Home", route="website:home", order=0)
    MenuItem.objects.create(menu=menu, title="Services", url="/services/", order=1)
    MenuItem.objects.create(menu=menu, title="About", route="website:about", order=2)
    assert render("/services/shops/") == "[Home|/][Services|/services/|active][About|/about/]"
    assert render("/services/web/") == "[Home|/][Services|/services/|active][About|/about/]"
    # The home page stands for no section: it is current on / only.
    assert render("/about/") == "[Home|/][Services|/services/][About|/about/|current|active]"
    settings.KARNI_SITE_MENU_SECTIONS = False
    assert render("/services/shops/") == "[Home|/][Services|/services/][About|/about/]"


def test_rows_from_a_model_follow_the_rows(services: list[Service]) -> None:
    menu = Menu.objects.create(name="footer")
    MenuItem.objects.create(
        menu=menu,
        title="All",
        route="website:home",
        children_from=ContentType.objects.get_for_model(Service),
    )
    assert "(Websites|/services/websites/)(Shops|/services/shops/)" in render(name="footer")
    services[0].title = "Web design"
    services[0].save()
    Service.objects.create(title="Apps", slug="apps", order=3)
    services[1].delete()
    assert "(Web design|/services/websites/)(Apps|/services/apps/)]" in render(name="footer")


def test_a_menu_is_built_once_and_a_save_clears_it() -> None:
    menu = Menu.objects.create(name="header")
    item = MenuItem.objects.create(menu=menu, title="Home", route="website:home")
    render()
    with CaptureQueriesContext(connection) as queries:
        assert render() == "[Home|/|current|active]"
    assert len(queries) == 0
    item.title = "Start"
    item.save()
    assert render() == "[Start|/|current|active]"


def test_a_menu_is_seeded_from_the_designs_navigation() -> None:
    source = (
        '{% load karni_site %}{% get_menu "main" seed="website/menus/header.html" as items %}'
        + LOOP.removeprefix("{% load karni_site %}{% get_menu name as items %}")
    )
    shown = render("/about/", source=source)
    assert shown == (
        "[Home|/]"
        "[About us|/about/|current|active(Web|/services/web/)(Order|/contact/?topic=order)"
        "(Team|/about/#team|current)]"
        "[Find us|https://maps.example.com/shop]"
        "[Bottom|#footer]"
    )
    menu = Menu.objects.get(name="main")
    assert menu.seed == "website/menus/header.html" and menu.title == "Main"
    order = MenuItem.objects.get(title="Order")
    assert (order.route, order.suffix, order.parent.title) == (
        "website:contact",
        "?topic=order",
        "About us",
    )
    assert MenuItem.objects.get(title="Find us").url == "https://maps.example.com/shop"
    # The client's menu is never replaced by the seed again.
    MenuItem.objects.filter(title="Bottom").get().delete()
    assert "Bottom" not in render("/", source=source)
    assert MenuItem.objects.filter(menu=menu).count() == 6


def test_parse_links_reads_flat_and_nested_navigation() -> None:
    flat = menus.parse_links(
        '<nav><a href="/">Home</a> <a href="/about/">About <b>us</b></a></nav>'
    )
    assert [(link.title, link.href) for link in flat] == [("Home", "/"), ("About us", "/about/")]
    nested = menus.parse_links(
        "<ul><li><span>Group</span><ul><li><a href='/a/'>A</a></li></ul></li></ul>"
    )
    assert [(link.title, link.href) for link in nested] == [("A", "/a/")]


def test_items_that_point_nowhere_are_refused() -> None:
    menu = Menu.objects.create(name="header")
    other = Menu.objects.create(name="footer")
    for fields, message in (
        ({}, "Choose where the link goes"),
        ({"route": "website:nowhere"}, "No page is named website:nowhere"),
        ({"route": "website:home", "url": "/x/"}, "Choose one place"),
        ({"url": "javascript:alert(1)"}, "cannot be a link"),
        (
            {"content_type": ContentType.objects.get_for_model(Service), "object_id": "0"},
            "does not exist",
        ),
    ):
        with pytest.raises(ValidationError, match=message) as refused:
            MenuItem(menu=menu, **fields).full_clean()
        assert "SITE007" in str(refused.value)
    stranger = MenuItem.objects.create(menu=other, url="/x/")
    with pytest.raises(ValidationError, match="same menu"):
        MenuItem(menu=menu, url="/y/", parent=stranger).full_clean()
    top = MenuItem.objects.create(menu=menu, url="/a/")
    child = MenuItem.objects.create(menu=menu, url="/b/", parent=top)
    top.parent = child
    with pytest.raises(ValidationError, match="under itself"):
        top.full_clean()


def test_get_menu_is_written_rightly() -> None:
    for bad in (
        '{% get_menu "x" %}',
        '{% get_menu "x" items %}',
        '{% get_menu "x" from="y" as i %}',
    ):
        with pytest.raises(TemplateSyntaxError, match="SITE003"):
            Template("{% load karni_site %}" + bad)
    assert render(name="missing") == ""


# A seed's list marked as a model's rows (karni import design marks one whose links
# are that model's detail pages): the menu follows the rows.


def _seeded(name: str, markup: str) -> str:
    assert menus.seed_menu(name, markup)
    return render(name=name)


def test_a_marked_list_is_the_models_rows_in_its_place(services: list[Service]) -> None:
    markup = (
        '<ul data-karni-children-from="testapp.Service">'
        '<li><a href="/services/websites/">Websites</a></li>'
        '<li><a href="/services/shops/">Shops</a></li></ul>'
    )
    assert _seeded("footer", markup) == ("[Websites|/services/websites/][Shops|/services/shops/]")
    item = MenuItem.objects.get(menu__name="footer")
    assert menus.in_place(item) and item.children_from.model_class() is Service
    Service.objects.create(title="Apps", slug="apps", order=3)
    assert render(name="footer").endswith("[Apps|/services/apps/]")


def test_a_marked_submenu_is_a_parent_with_children_from_the_model(
    services: list[Service],
) -> None:
    markup = (
        '<ul><li><a href="/">Home</a></li><li><a href="/about/">Services</a>'
        '<ul data-karni-children-from="testapp.Service">'
        '<li><a href="/services/websites/">Websites</a></li></ul></li></ul>'
    )
    assert _seeded("header", markup) == (
        "[Home|/|current|active]"
        "[Services|/about/(Websites|/services/websites/)(Shops|/services/shops/)]"
    )
    parent = MenuItem.objects.get(title="Services")
    assert parent.children_from is not None and not parent.children.exists()


def test_a_marked_list_without_its_model_keeps_the_designs_links() -> None:
    markup = (
        '<ul data-karni-children-from="testapp.Nothing">'
        '<li><a href="/about/">About</a></li><li><a href="/contact/">Contact</a></li></ul>'
    )
    assert _seeded("footer", markup) == "[About|/about/][Contact|/contact/]"
    assert list(MenuItem.objects.values_list("order", flat=True).order_by("order")) == [0, 1]


def test_an_item_with_a_title_keeps_its_own_entry(services: list[Service]) -> None:
    menu = Menu.objects.create(name="footer")
    MenuItem.objects.create(
        menu=menu, title="Our services", children_from=ContentType.objects.get_for_model(Service)
    )
    assert render(name="footer").startswith("[Our services|(Websites|")


# A seeded menu follows its seed template while nobody changes it.

FOLLOW = (
    '{% load karni_site %}{% get_menu "main" seed="menus/seed.html" as items %}'
    "{% for item in items %}[{{ item.title }}|{{ item.url }}"
    "{% for child in item.children %}({{ child.title }}|{{ child.url }}){% endfor %}]{% endfor %}"
)
V1 = (
    '<ul><li><a href="/">Home</a></li><li><a href="/about/">About</a>'
    '<ul><li><a href="/about/#team">Team</a></li></ul></li>'
    '<li><a href="/services/web/">Web</a></li></ul>'
)


@pytest.fixture
def seed_dir(settings: Any, tmp_path: Any) -> Any:
    """A template folder holding menus/seed.html, which a test rewrites."""
    folder = tmp_path / "seeds"
    (folder / "menus").mkdir(parents=True)
    engine = dict(settings.TEMPLATES[0])
    engine["DIRS"] = [folder, *engine["DIRS"]]
    settings.TEMPLATES = [engine, *settings.TEMPLATES[1:]]
    return folder


def write_seed(folder: Any, markup: str) -> None:
    """A new version of the seed, as a deploy brings one (the cached templates are read again)."""
    from django.template import engines

    (folder / "menus" / "seed.html").write_text(markup)
    for engine in engines.all():
        for loader in getattr(engine, "engine", engine).template_loaders:
            if hasattr(loader, "reset"):
                loader.reset()


def shown(path: str = "/") -> str:
    return render(path, source=FOLLOW)


def test_a_menu_follows_its_seed_while_nobody_changes_it(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    assert shown() == "[Home|/][About|/about/(Team|/about/#team)][Web|/services/web/]"
    # The designer renames a link, drops one, adds one and points one elsewhere (the
    # view it named was renamed): the menu follows.
    write_seed(
        seed_dir,
        '<ul><li><a href="/">Home</a></li><li><a href="/about/">About us</a></li>'
        '<li><a href="/contact/">Web</a></li><li><a href="/book/">Book</a></li></ul>',
    )
    assert shown() == "[Home|/][About us|/about/][Web|/contact/][Book|/book/]"
    web = MenuItem.objects.get(title="Web")
    assert (web.route, web.url) == ("website:contact", "")
    assert not MenuItem.objects.filter(title="Team").exists()
    assert MenuItem.objects.filter(menu__name="main").count() == 4


def test_an_item_changed_in_the_admin_keeps_its_change(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    shown()
    about = MenuItem.objects.get(title="About")
    about.title = "Who we are"
    about.save()
    web = MenuItem.objects.get(title="Web")
    web.enabled = False
    web.save()
    added = MenuItem.objects.create(menu=about.menu, title="Jobs", url="/jobs/", order=9)
    write_seed(
        seed_dir,
        '<ul><li><a href="/">Start</a></li><li><a href="/about/">About</a>'
        '<ul><li><a href="/about/#team">Our team</a></li></ul></li>'
        '<li><a href="/services/web/">Websites</a></li><li><a href="/book/">Book</a></li></ul>',
    )
    assert shown() == (
        "[Start|/][Who we are|/about/(Our team|/about/#team)][Book|/book/][Jobs|/jobs/]"
    )
    assert MenuItem.objects.filter(title="Who we are").count() == 1
    assert not MenuItem.objects.filter(title="About").exists()
    web.refresh_from_db()
    assert (web.title, web.enabled) == ("Web", False), "hidden in the admin: kept as it was"
    added.refresh_from_db()
    assert added.title == "Jobs" and not added.is_deleted


def test_an_item_deleted_in_the_admin_stays_deleted(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    shown()
    MenuItem.objects.get(title="Team").delete()
    MenuItem.objects.get(title="Web").delete()
    write_seed(
        seed_dir, V1.replace("</ul></li>", '<li><a href="/contact/">Write</a></li></ul></li>')
    )
    assert shown() == "[Home|/][About|/about/(Write|/contact/)]"


def test_a_changed_item_is_kept_when_its_link_leaves_the_seed(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    shown()
    team = MenuItem.objects.get(title="Team")
    team.suffix = "#people"
    team.save()
    write_seed(seed_dir, '<ul><li><a href="/">Home</a></li></ul>')
    assert shown() == "[Home|/][About|/about/(Team|/about/#people)]", (
        "About stays for the changed child under it, Web goes"
    )


def test_an_unchanged_seed_costs_no_query(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    shown()
    with CaptureQueriesContext(connection) as queries:
        assert shown().startswith("[Home|/]")
    assert len(queries) == 0


def test_following_off_seeds_the_menu_once(seed_dir: Any, settings: Any) -> None:
    settings.KARNI_SITE_MENU_FOLLOW_SEED = False
    write_seed(seed_dir, V1)
    first = shown()
    write_seed(seed_dir, '<ul><li><a href="/book/">Book</a></li></ul>')
    assert shown() == first


def test_a_menu_made_in_the_admin_never_follows_a_seed(seed_dir: Any) -> None:
    menu = Menu.objects.create(name="main")
    MenuItem.objects.create(menu=menu, title="Mine", url="/mine/")
    write_seed(seed_dir, V1)
    assert shown() == "[Mine|/mine/]"
    assert not menus.sync_menu("main", V1, source="menus/seed.html")


def test_a_menu_seeded_before_seeds_were_followed_is_adopted(seed_dir: Any) -> None:
    from datetime import timedelta

    from django.utils import timezone

    # As 0.5.1 left it: items from the seed in the menu's moment, no record of the seed.
    write_seed(seed_dir, V1)
    shown()
    menu = Menu.objects.get(name="main")
    Menu.objects.filter(pk=menu.pk).update(seeded={})
    MenuItem.objects.without("soft_delete", reason="the test").filter(menu=menu).update(seed_key="")
    later = timezone.now() + timedelta(minutes=5)
    MenuItem.objects.filter(title="About").update(title="Who we are", updated_at=later)
    team = MenuItem.objects.get(title="Team")
    team.delete()
    MenuItem.objects.create(menu=menu, title="Jobs", url="/jobs/", order=9)
    MenuItem.objects.filter(title="Jobs").update(created_at=later, updated_at=later)
    from karni_site import caching

    caching.bump("menus")
    write_seed(
        seed_dir,
        V1.replace(">Home<", ">Start<").replace(
            "</ul></li>", '<li><a href="/book/">Book</a></li></ul></li>'
        ),
    )
    assert shown() == (
        "[Start|/][Who we are|/about/(Book|/book/)][Web|/services/web/][Jobs|/jobs/]"
    )
    assert MenuItem.objects.filter(menu=menu).count() == 5


def test_a_seed_that_stops_rendering_keeps_the_menu(seed_dir: Any) -> None:
    write_seed(seed_dir, V1)
    first = shown()
    write_seed(seed_dir, "{% url 'website:gone' %}")
    assert shown() == first
