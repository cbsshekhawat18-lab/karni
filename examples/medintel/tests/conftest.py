"""Demo data once per session, and clients that sign in the way a customer does."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from intel.seeds import CUSTOMERS
from karni.seeding import seed
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """The seeded app (karni seed --seed 42): trees, trials, deals, customers and their grants."""
    logins = {email: ["customer"] for email in CUSTOMERS}
    with django_db_blocker.unblock(), override_settings(KARNI_SEED_LOGINS=logins):
        seed(seed=42)
        cache.clear()


@pytest.fixture
def client_for(db):
    """``client_for(email)``: a JWT client for a seeded login, with the terms accepted."""

    def make(email: str, *, accept_terms: bool = True) -> APIClient:
        user = get_user_model().objects.get(email=email)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        if accept_terms:
            version = settings.KARNI_TERMS["version"]
            assert client.post(
                "/api/auth/terms/accept/", {"version": version}, format="json"
            ).status_code in (200, 201)
        return client

    return make
