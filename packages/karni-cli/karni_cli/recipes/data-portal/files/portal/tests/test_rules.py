"""The data rules of karni.yaml: one value per dataset, place, topic and year."""

from typing import Any

import pytest
from karni.testing.factories import create

from portal.models import Dataset, Indicator, Region, Sector

pytestmark = pytest.mark.django_db


def _code(response: Any, field: str) -> str:
    return str(response.json()[field][0])[:4]


@pytest.fixture
def body() -> dict[str, Any]:
    region = create(Region, parent=None)
    sector = create(Sector, parent=None)
    dataset = create(Dataset)
    return {
        "dataset": str(dataset.pk),
        "region": str(region.pk),
        "sector": str(sector.pk),
        "year": 2024,
        "value": "12.500",
        "label": "Beds, Lyon, 2024",
    }


def test_one_indicator_per_dataset_region_sector_and_year(
    client_as: Any, body: dict[str, Any]
) -> None:
    editor = client_as("editor")
    assert editor.post("/api/indicators/", body, format="json").status_code == 201
    same_label = editor.post("/api/indicators/", {**body, "year": 2023}, format="json")
    assert same_label.status_code == 400 and _code(same_label, "label") == "E991"
    same_cell = editor.post(
        "/api/indicators/", {**body, "label": "Other"}, format="json"
    )
    assert same_cell.status_code == 400 and _code(same_cell, "dataset") == "E991"


def test_a_year_stays_in_its_range(client_as: Any, body: dict[str, Any]) -> None:
    editor = client_as("editor")
    for year in (1066, 3000):
        refused = editor.post("/api/indicators/", {**body, "year": year}, format="json")
        assert refused.status_code == 400 and _code(refused, "year") == "E990"


def test_a_dataset_with_indicators_is_not_deleted(client_as: Any) -> None:
    indicator = create(Indicator, year=2020)
    editor = client_as("editor")
    refused = editor.delete(f"/api/datasets/{indicator.dataset.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
    assert Dataset.objects.filter(pk=indicator.dataset.pk).exists()
    editor.delete(f"/api/indicators/{indicator.pk}/")
    assert editor.delete(f"/api/datasets/{indicator.dataset.pk}/").status_code == 204
