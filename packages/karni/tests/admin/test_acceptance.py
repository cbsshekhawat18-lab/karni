"""Contract acceptance: a model with zero admin code appears fully configured.

``KitchenSink`` ships no ``admin.py``, no admin class and no ``AdminMeta`` —
everything the changelist and change form need is derived at startup, and the
real views render through django-unfold's templates as a superuser.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from karni.admin.soft_delete import SoftDeleteListFilter
from tests.adminapp.models import Category, KitchenSink, Note

CHANGELIST_URL = reverse("admin:adminapp_kitchensink_changelist")


def test_kitchen_sink_is_fully_configured_with_zero_admin_code(
    site: admin.AdminSite,
) -> None:
    model_admin = site._registry[KitchenSink]
    assert type(model_admin)._karni_generated

    assert list(model_admin.list_display) == ["name", "slug", "email", "url", "count", "price"]
    # A BaseModel is soft-deletable, so the "deleted" filter leads.
    assert list(model_admin.list_filter) == [
        SoftDeleteListFilter,
        "featured",
        "status",
        ("category", admin.RelatedOnlyFieldListFilter),
        "published_on",
        "released_at",
    ]
    assert list(model_admin.search_fields) == ["name", "slug", "email", "url", "blurb"]
    assert model_admin.date_hierarchy == "published_on"
    assert list(model_admin.readonly_fields) == [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
    ]
    assert list(model_admin.autocomplete_fields) == ["category", "tags"]
    (inline,) = model_admin.inlines
    assert inline.model is Note


@pytest.mark.django_db
def test_changelist_renders_through_the_real_unfold_template(admin_client: Client) -> None:
    category = Category.objects.create(name="Reference")
    KitchenSink.objects.create(
        name="Sink one",
        slug="sink-one",
        email="sink@example.com",
        url="https://example.com/sink",
        blurb="Long text that stays out of the changelist.",
        count=3,
        price=Decimal("19.99"),
        rating=4.5,
        featured=True,
        published_on=datetime.date(2026, 1, 15),
        released_at=timezone.now(),
        payload={"key": "value"},
        status=KitchenSink.Status.LIVE,
        category=category,
    )

    response = admin_client.get(CHANGELIST_URL)
    assert response.status_code == 200
    assert b"Sink one" in response.content
    # The page really rendered through django-unfold's admin override, not
    # Django's stock changelist template.
    origins = [
        template.origin.name
        for template in response.templates
        if template.origin is not None and template.origin.name
    ]
    assert any("unfold" in str(origin) for origin in origins)


@pytest.mark.django_db
def test_searching_and_filtering_work_out_of_the_box(admin_client: Client) -> None:
    KitchenSink.objects.create(name="Findable", blurb="needle in the blurb")
    KitchenSink.objects.create(name="Other", featured=True)

    searched = admin_client.get(CHANGELIST_URL, {"q": "needle"})
    assert searched.status_code == 200
    results = list(searched.context["cl"].queryset)
    assert [sink.name for sink in results] == ["Findable"]

    filtered = admin_client.get(CHANGELIST_URL, {"featured__exact": "1"})
    assert filtered.status_code == 200
    assert [sink.name for sink in filtered.context["cl"].queryset] == ["Other"]


@pytest.mark.django_db
def test_add_and_change_forms_render(admin_client: Client) -> None:
    assert admin_client.get(reverse("admin:adminapp_kitchensink_add")).status_code == 200
    sink = KitchenSink.objects.create(name="Editable")
    url = reverse("admin:adminapp_kitchensink_change", args=[sink.pk])
    assert admin_client.get(url).status_code == 200
