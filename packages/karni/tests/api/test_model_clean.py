"""Model.clean() runs through the generated serializer: a 400 keyed by field, not a crash."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from karni.testing import client_as
from karni.testing.factories import create
from tests.testapp.models import LooseSlot, Slot

pytestmark = pytest.mark.django_db

NOW = timezone.now()


def payload(hours: int) -> dict[str, str]:
    return {"starts_at": NOW.isoformat(), "ends_at": (NOW + timedelta(hours=hours)).isoformat()}


def test_create_runs_clean_and_answers_400_on_its_field() -> None:
    client = client_as()
    response = client.post("/api/slots/", payload(-1), format="json")
    assert response.status_code == 400
    assert response.json() == {"ends_at": ["ends_at must be after starts_at."]}
    assert Slot.objects.count() == 0
    assert client.post("/api/slots/", payload(2), format="json").status_code == 201


def test_update_runs_clean_on_the_merged_row() -> None:
    slot = create(Slot, starts_at=NOW, ends_at=NOW + timedelta(hours=2))
    client = client_as()
    bad = client.patch(f"/api/slots/{slot.pk}/", {"ends_at": NOW.isoformat()}, format="json")
    assert bad.status_code == 400 and "ends_at" in bad.json()
    slot.refresh_from_db()
    assert slot.ends_at == NOW + timedelta(hours=2)
    good = client.patch(
        f"/api/slots/{slot.pk}/", {"ends_at": (NOW + timedelta(hours=3)).isoformat()}, format="json"
    )
    assert good.status_code == 200


def test_apimeta_validate_false_skips_clean() -> None:
    response = client_as().post("/api/loose-slots/", payload(-1), format="json")
    assert response.status_code == 201
    assert LooseSlot.objects.count() == 1
