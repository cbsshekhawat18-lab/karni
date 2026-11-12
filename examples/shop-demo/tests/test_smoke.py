"""Project test suite. Karni's architecture rules run separately in CI:

    pytest --pyargs karni.testing.architecture
"""

import pytest


@pytest.mark.django_db
def test_health_liveness(client):
    assert client.get("/health/").status_code == 200


@pytest.mark.django_db
def test_healthz(client):
    assert client.get("/healthz").status_code == 200
