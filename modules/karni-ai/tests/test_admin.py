"""The usage log in the admin: listed, never added, changed or deleted."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from karni_ai.models import AICall


@pytest.fixture
def admin_client(db: None) -> Client:
    root = get_user_model().objects.create_superuser(email="root@example.com", password="x")
    client = Client()
    client.force_login(root)
    return client


def test_the_log_is_listed_and_read_only(admin_client: Client) -> None:
    call = AICall.objects.create(
        provider="test",
        model="test",
        resource="products",
        source="text",
        input_tokens=10,
        output_tokens=2,
    )
    listing = admin_client.get("/admin/karni_ai/aicall/")
    assert listing.status_code == 200 and b"products" in listing.content
    assert admin_client.get("/admin/karni_ai/aicall/add/").status_code == 403
    detail = admin_client.get(f"/admin/karni_ai/aicall/{call.pk}/change/")
    assert detail.status_code == 200 and b'name="_save"' not in detail.content
    assert (
        admin_client.post(f"/admin/karni_ai/aicall/{call.pk}/delete/", {"post": "yes"}).status_code
        == 403
    )
    assert AICall.objects.filter(pk=call.pk).exists()
