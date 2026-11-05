"""The admin: every model has its screens, an import page and export actions."""

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory

pytestmark = pytest.mark.django_db

MODELS = ["condition", "intervention", "company", "person", "trial", "brand", "deal"]


def login(email: str) -> Client:
    client = Client()
    client.force_login(get_user_model().objects.get(email=email))
    return client


@pytest.mark.parametrize("name", MODELS)
def test_each_model_has_a_full_admin(name):
    model = apps.get_model("intel", name)
    staff = login("demo@example.com")
    base = f"/{settings.KARNI_ADMIN_PATH}intel/{name}"
    row = model.objects.order_by("pk").first()
    for path in (f"{base}/", f"{base}/add/", f"{base}/{row.pk}/change/", f"{base}/import/"):
        assert staff.get(path).status_code == 200, path
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.get(email="demo@example.com")
    assert {"export_csv", "export_xlsx"} <= set(admin.site._registry[model].get_actions(request))


def test_a_customer_has_no_admin():
    response = login("oncology@example.com").get(f"/{settings.KARNI_ADMIN_PATH}intel/trial/")
    assert response.status_code in (302, 403)
