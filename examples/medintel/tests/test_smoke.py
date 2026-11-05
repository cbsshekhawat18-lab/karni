"""Project test suite. Karni's architecture rules run separately in CI:

    pytest --pyargs karni.testing.architecture
"""

import pytest


@pytest.mark.django_db
def test_health_liveness(client):
    assert client.get("/health/").status_code == 200
