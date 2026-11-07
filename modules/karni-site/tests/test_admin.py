"""The admin and the editor role: content only, no enquiries, users or settings."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse
from karni.accounts.models import Role
from karni.accounts.roles import declared_roles
from pytest_django import Settings

from karni_site.models import Block, Menu, MenuItem, PageSeo, Redirect, SiteSettings
from tests.testapp.models import Enquiry, Service

pytestmark = pytest.mark.django_db


def signed_in(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


def url(model: type[Any], view: str, *args: Any) -> str:
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


def test_the_module_declares_the_editor_role(roles: None, settings: Settings) -> None:
    editor = next(spec for spec in declared_roles() if spec.slug == "editor")
    assert editor.grants["karni_site.block:change"] == "all"
    assert "karni_site.redirect:*" not in editor.grants
    assert Role.objects.filter(slug="editor").exists()
    settings.KARNI_SITE_EDITOR_ROLE = "content"
    assert "content" in {spec.slug for spec in declared_roles()}
    settings.KARNI_SITE_EDITOR_ROLE = None
    assert "editor" not in {spec.slug for spec in declared_roles()}
    settings.KARNI_ROLES = {
        "editor": {"name": "Copy editor", "grants": {"karni_site.block:view": "all"}}
    }
    settings.KARNI_SITE_EDITOR_ROLE = "editor"
    assert next(s for s in declared_roles() if s.slug == "editor").name == "Copy editor"


def test_the_editor_sees_the_content_and_nothing_else(editor: Any, client: Client) -> None:
    client.get("/contact/")  # stores the page's blocks and the site's details
    Enquiry.objects.create(name="Ada", message="A cake, please")
    admin = signed_in(editor)
    index = admin.get(reverse("admin:index")).content.decode()
    for model in (Block, Menu, PageSeo, SiteSettings):
        assert url(model, "changelist") in index, model
    assert url(Enquiry, "changelist") not in index
    assert url(Redirect, "changelist") not in index
    assert "karni_accounts" not in index
    assert admin.get(url(Enquiry, "changelist")).status_code == 403
    from django.contrib.auth import get_user_model

    assert admin.get(url(get_user_model(), "changelist")).status_code == 403
    assert admin.get(url(Redirect, "changelist")).status_code == 403
    assert admin.get(url(Block, "changelist")).status_code == 200


def test_the_editor_edits_a_block_as_text(editor: Any, client: Client) -> None:
    client.get("/contact/")
    block = Block.objects.get(key="contact.hero.text")
    admin = signed_in(editor)
    page = admin.get(url(Block, "change", block.pk)).content.decode()
    assert "Open &lt;b&gt;every&lt;/b&gt; morning.\nClosed on Mondays." in page
    response = admin.post(
        url(Block, "change", block.pk),
        {"text": "Open ==every== day.\nEven Sundays.<script>x()</script>"},
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    block.refresh_from_db()
    assert block.html == "Open <mark>every</mark> day.<br>\nEven Sundays."
    assert (
        "Open <mark>every</mark> day.<br>\nEven Sundays."
        in client.get("/contact/").content.decode()
    )
    # Saving the template's text unchanged keeps the block following the template.
    title = Block.objects.get(key="contact.hero.title")
    admin.post(
        url(Block, "change", title.pk), {"text": 'Visit <span class="highlight">the bakery</span>'}
    )
    title.refresh_from_db()
    assert not title.edited
    history = admin.get(url(Block, "history", block.pk)).content.decode()
    assert "Even Sundays" in history
    # Reset hands the block back to the template.
    admin.post(
        url(Block, "changelist"),
        {"action": "reset_to_template", "_selected_action": [str(block.pk)]},
    )
    block.refresh_from_db()
    assert block.html == block.default_html and not block.edited


def test_the_editor_changes_the_site_details_but_cannot_add_or_delete_them(
    editor: Any, client: Client
) -> None:
    client.get("/contact/")
    row = SiteSettings.objects.get()
    admin = signed_in(editor)
    listing = admin.get(url(SiteSettings, "changelist"))
    assert listing.status_code == 302 and listing["Location"] == url(SiteSettings, "change", row.pk)
    form = admin.get(url(SiteSettings, "change", row.pk)).content.decode()
    assert 'name="phone"' in form and "opening_hours_rows-TOTAL_FORMS" in form
    data = {
        "name": "Crumb & Co Bakery",
        "tagline": "",
        "address": "1 Mill Lane",
        "phone": "0123 999",
        "phone_link": "",
        "email": "orders@example.com",
        "map_url": "",
        "opening_hours_rows-TOTAL_FORMS": "1",
        "opening_hours_rows-INITIAL_FORMS": "0",
        "opening_hours_rows-0-days": "Tue to Sat",
        "opening_hours_rows-0-times": "7:00 to 15:00",
        "opening_hours_rows-0-order": "0",
        "social_link_rows-TOTAL_FORMS": "1",
        "social_link_rows-INITIAL_FORMS": "1",
        "social_link_rows-0-id": str(row.social_link_rows.get().pk),
        "social_link_rows-0-site": str(row.pk),
        "social_link_rows-0-name": "Instagram",
        "social_link_rows-0-url": "https://instagram.com/crumbandco",
        "social_link_rows-0-order": "0",
    }
    response = admin.post(url(SiteSettings, "change", row.pk), data)
    assert response.status_code == 302, response.content.decode()[:3000]
    page = client.get("/contact/").content.decode()
    assert "0123 999" in page and "orders@example.com" in page
    assert "<li>Tue to Sat: 7:00 to 15:00</li>" in page
    assert "https://instagram.com/crumbandco" in page
    assert admin.get(url(SiteSettings, "add")).status_code == 403
    assert admin.get(url(SiteSettings, "delete", row.pk)).status_code == 403


def test_the_editor_builds_a_menu(editor: Any) -> None:
    service = Service.objects.create(title="Websites", slug="websites")
    admin = signed_in(editor)
    form = admin.get(url(Menu, "add")).content.decode()
    assert "/about/  (website:about)" in form and "Websites" in form
    content_type = ContentType.objects.get_for_model(Service)
    response = admin.post(
        url(Menu, "add"),
        {
            "name": "footer",
            "title": "Footer",
            "items-TOTAL_FORMS": "3",
            "items-INITIAL_FORMS": "0",
            "items-0-title": "About",
            "items-0-goes_to": "route:website:about",
            "items-0-order": "0",
            "items-0-enabled": "on",
            "items-1-title": "",
            "items-1-goes_to": f"object:{content_type.pk}:{service.pk}",
            "items-1-order": "1",
            "items-1-enabled": "on",
            "items-2-title": "Shop",
            "items-2-goes_to": "url",
            "items-2-url": "https://shop.example.com/",
            "items-2-children": str(content_type.pk),
            "items-2-order": "2",
            "items-2-enabled": "on",
        },
    )
    assert response.status_code == 302, response.content.decode()[:3000]
    items = {item.order: item for item in MenuItem.objects.filter(menu__name="footer")}
    assert items[0].route == "website:about" and items[0].url == ""
    assert (items[1].content_type, items[1].object_id) == (content_type, str(service.pk))
    assert items[2].url == "https://shop.example.com/" and items[2].children_from == content_type
    refused = admin.post(
        url(Menu, "add"),
        {
            "name": "broken",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-0-title": "Nowhere",
            "items-0-goes_to": "",
            "items-0-order": "0",
            "items-0-enabled": "on",
        },
    )
    assert refused.status_code == 200 and "SITE007" in refused.content.decode()


def test_the_editor_sets_a_page_title(editor: Any) -> None:
    admin = signed_in(editor)
    response = admin.post(
        url(PageSeo, "add"),
        {
            "route": "website:about",
            "path": "",
            "title": "About the bakery",
            "description": "Who bakes.",
        },
    )
    assert response.status_code == 302, response.content.decode()[:3000]
    assert PageSeo.objects.get(route="website:about").title == "About the bakery"


def test_a_superuser_manages_redirects(owner: Any, client: Client) -> None:
    admin = signed_in(owner)
    response = admin.post(
        url(Redirect, "add"), {"old_path": "/old/", "new_url": "/about/", "status": "301"}
    )
    assert response.status_code == 302
    assert client.get("/old/").headers["Location"] == "/about/"
    looped = admin.post(
        url(Redirect, "add"), {"old_path": "/about/", "new_url": "/old/", "status": "301"}
    )
    assert looped.status_code == 200 and "SITE006" in looped.content.decode()


def test_a_staff_user_without_the_role_sees_nothing(roles: None) -> None:
    from tests.conftest import make_user

    staff = make_user("staff@example.com", staff=True)
    admin = signed_in(staff)
    assert admin.get(url(Block, "changelist")).status_code == 403
    assert url(Block, "changelist") not in admin.get(reverse("admin:index")).content.decode()


def test_the_staff_role_opens_the_projects_own_pages_and_the_sites(roles: None) -> None:
    """The staff role (every grant) with no Django permission ticked: every Karni page opens."""
    from tests.conftest import make_user

    manager = make_user("manager@example.com", "staff", staff=True)
    assert not manager.user_permissions.exists()
    enquiry = Enquiry.objects.create(name="Ada", message="A cake, please")
    admin = signed_in(manager)
    index = admin.get(reverse("admin:index")).content.decode()
    for model in (Enquiry, Service, Block, Menu, Redirect, PageSeo):
        assert url(model, "changelist") in index, model
        assert admin.get(url(model, "changelist")).status_code == 200, model
    assert admin.get(url(Enquiry, "change", enquiry.pk)).status_code == 200
    assert admin.get(url(Service, "add")).status_code == 200


def test_a_project_role_opens_its_own_pages_only(settings: Settings) -> None:
    from karni.accounts.roles import sync_roles

    from tests.conftest import make_user

    settings.KARNI_ROLES = {
        **settings.KARNI_ROLES,
        "front_desk": {"name": "Front desk", "grants": {"testapp.enquiry:*": "all"}},
    }
    sync_roles()
    desk = make_user("desk@example.com", "front_desk", staff=True)
    admin = signed_in(desk)
    index = admin.get(reverse("admin:index")).content.decode()
    assert url(Enquiry, "changelist") in index
    assert url(Service, "changelist") not in index and url(Block, "changelist") not in index
    assert admin.get(url(Enquiry, "add")).status_code == 200
    assert admin.get(url(Service, "changelist")).status_code == 403
    # The escape hatch: Django's model permissions only, for this module's pages too.
    settings.KARNI_ADMIN_GRANTS_OPEN_PAGES = False
    assert admin.get(url(Enquiry, "changelist")).status_code == 403


def test_the_editor_needs_django_permissions_once_grants_stop_opening_pages(
    editor: Any, settings: Settings
) -> None:
    admin = signed_in(editor)
    assert admin.get(url(Block, "changelist")).status_code == 200
    settings.KARNI_ADMIN_GRANTS_OPEN_PAGES = False
    assert admin.get(url(Block, "changelist")).status_code == 403
