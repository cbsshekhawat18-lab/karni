"""The admin's export actions and import page (ADR 0002, P6)."""

from __future__ import annotations

import csv
import io
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.middleware import current_user
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db


def _staff(email: str, *roles: str, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="a-strong-password-123")
    user = model.objects.create_user(email=email, password="a-strong-password-123", is_staff=True)
    for role in roles:
        assign_role(user, role)
    user.user_permissions.add(
        *DjangoPermission.objects.filter(content_type=ContentType.objects.get_for_model(Venue))
    )
    return user


def _client(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture(autouse=True)
def _registered() -> None:
    if Venue not in admin.site._registry:
        pytest.skip("Venue is not registered on the default admin site")


def test_export_selected_as_csv_and_xlsx() -> None:
    root = _staff("root@example.com", superuser=True)
    with current_user(root):
        a = Venue.objects.create(name="Arena", city="Berlin")
        Venue.objects.create(name="Hall", city="Paris")
    client = _client(root)
    url = reverse("admin:testapp_venue_changelist")
    response = client.post(url, {"action": "export_csv", "_selected_action": [str(a.pk)]})
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    content = b"".join(response.streaming_content).decode()
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0][:1] == ["id"] and "name" in rows[0]
    assert [row[rows[0].index("name")] for row in rows[1:]] == ["Arena"]
    everything = client.post(
        url, {"action": "export_xlsx", "select_across": "1", "_selected_action": [str(a.pk)]}
    )
    assert everything.status_code == 200 and everything["Content-Type"].endswith(
        "spreadsheetml.sheet"
    )
    assert everything["X-Karni-Export-Rows"] == "2"


def test_the_import_page_uploads_maps_previews_and_commits() -> None:
    root = _staff("root@example.com", superuser=True)
    client = _client(root)
    changelist = client.get(reverse("admin:testapp_venue_changelist"))
    import_url = reverse("admin:testapp_venue_import")
    assert import_url in changelist.content.decode()
    page = client.get(import_url)
    assert page.status_code == 200 and "Download the template" in page.content.decode()
    template = client.get(reverse("admin:testapp_venue_import_template"))
    assert template.status_code == 200 and template["Content-Type"].endswith("spreadsheetml.sheet")

    upload = io.BytesIO(b"Name,City\nArena,Berlin\n,Nowhere\n")
    upload.name = "venues.csv"
    response = client.post(import_url, {"file": upload})
    assert response.status_code == 302
    job_url = response["Location"]
    mapping_page = client.get(job_url)
    body = mapping_page.content.decode()
    assert "Map columns to fields" in body and 'name="map:0"' in body
    previewed = client.post(job_url, {"step": "map", "map:0": "name", "map:1": "city"}, follow=True)
    body = previewed.content.decode()
    assert "Rows with errors" in body and "Commit" in body
    assert Venue.objects.count() == 0
    committed = client.post(job_url, {"step": "commit"}, follow=True)
    assert "1 created, 0 updated, 1 skipped" in committed.content.decode()
    assert Venue.objects.get(name="Arena").city == "Berlin" and Venue.objects.count() == 1
    state = client.get(
        reverse("admin:testapp_venue_import_state", args=[job_url.rstrip("/").rsplit("/", 1)[1]])
    )
    assert state.status_code == 200 and state.json()["status"] == "done"


def test_the_import_page_needs_add_or_change() -> None:
    # Django's model permissions decide which screens exist: a viewer may not import.
    viewer = get_user_model().objects.create_user(
        email="viewer@example.com", password="a-strong-password-123", is_staff=True
    )
    viewer.user_permissions.add(DjangoPermission.objects.get(codename="view_venue"))
    assert _client(viewer).get(reverse("admin:testapp_venue_import")).status_code == 403
    assert (
        "export_csv"
        in _client(viewer).get(reverse("admin:testapp_venue_changelist")).content.decode()
    )


def test_an_admin_can_opt_out() -> None:
    from karni.admin.base import KarniModelAdmin

    class QuietAdmin(KarniModelAdmin):
        karni_transfer = False

    quiet = QuietAdmin(Venue, admin.site)
    assert "export_csv" not in quiet.actions
    assert not any("import" in str(pattern.pattern) for pattern in quiet.get_urls())
