"""The portal's rules: analysts read the regions granted to them, and only those."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from karni.accounts import grants
from karni.accounts.models import UserGrant
from karni.testing.factories import create

from portal.models import Dataset, Indicator, Region, Sector

pytestmark = pytest.mark.django_db


class World:
    """Europe (France, Spain) and Asia (Japan), a dataset across both, one in Asia."""

    def __init__(self) -> None:
        self.europe = create(Region, name="Europe", slug="europe", parent=None)
        self.france = create(Region, name="France", slug="france", parent=self.europe)
        self.spain = create(Region, name="Spain", slug="spain", parent=self.europe)
        self.asia = create(Region, name="Asia", slug="asia", parent=None)
        self.japan = create(Region, name="Japan", slug="japan", parent=self.asia)
        self.health = create(Sector, name="Health", slug="health", parent=None)
        self.life = self.dataset("Life expectancy", self.france, self.japan)
        self.beds = self.dataset("Hospital beds", self.japan)
        self.rows = {
            "france": self.indicator(self.life, self.france, 2020, "82.5"),
            "spain": self.indicator(self.life, self.spain, 2020, "83.0"),
            "japan": self.indicator(self.life, self.japan, 2020, "84.5"),
            "beds": self.indicator(self.beds, self.japan, 2021, "13.0"),
        }

    def dataset(self, title: str, *regions: Region) -> Dataset:
        dataset = create(Dataset, title=title, slug=title.lower().replace(" ", "-"))
        dataset.region.set(regions)
        dataset.sector.set([self.health])
        return dataset

    def indicator(
        self, dataset: Dataset, region: Region, year: int, value: str
    ) -> Indicator:
        return create(
            Indicator,
            dataset=dataset,
            region=region,
            sector=self.health,
            year=year,
            value=Decimal(value),
            label=f"{dataset.title}, {region.name}, {year}",
        )


def analyst_of(client_as: Any, *regions: Region) -> Any:
    """An analyst who holds ``regions`` and the regions below them, by user grants."""
    client = client_as("analyst")
    for permission in ("portal.dataset:view", "portal.indicator:view"):
        grants.grant(
            None,
            client.user,
            permission,
            "tree:region",
            targets=[region.pk for region in regions],
            reason="a test",
        )
    return client


def labels(response: Any) -> set[str]:
    assert response.status_code == 200, response.content
    return {row["label"] for row in response.json()["results"]}


def test_an_analyst_reads_the_indicators_and_datasets_under_the_regions_granted(
    client_as: Any,
) -> None:
    world = World()
    client = analyst_of(client_as, world.europe)
    assert labels(client.get("/api/indicators/")) == {
        "Life expectancy, France, 2020",
        "Life expectancy, Spain, 2020",
    }
    datasets = client.get("/api/datasets/").json()["results"]
    assert [row["title"] for row in datasets] == [
        "Life expectancy"
    ]  # tagged France: in Europe
    hidden = client.get(f"/api/indicators/{world.rows['japan'].pk}/")
    assert hidden.status_code == 404


def test_an_analyst_without_a_grant_reads_nothing_and_a_grant_ends(
    client_as: Any,
) -> None:
    world = World()
    client = client_as("analyst")
    assert client.get("/api/indicators/").json()["results"] == []
    granted = analyst_of(client_as, world.japan)
    assert len(granted.get("/api/indicators/").json()["results"]) == 2
    for grant in UserGrant.objects.filter(user=granted.user):
        grants.expire(None, grant)
    grants.forget(
        granted.user
    )  # a request loads the user afresh: this one keeps its object
    assert granted.get("/api/indicators/").json()["results"] == []


def test_staff_and_editors_read_every_region(client_as: Any) -> None:
    World()
    assert len(client_as("staff").get("/api/indicators/").json()["results"]) == 4
    assert len(client_as("editor").get("/api/indicators/").json()["results"]) == 4
    assert (
        client_as("staff").post("/api/indicators/", {}, format="json").status_code
        == 403
    )


def test_the_access_forest_names_the_granted_regions(client_as: Any) -> None:
    world = World()
    client = analyst_of(client_as, world.europe)
    forest = client.get("/api/regions/access/?permission=portal.indicator:view").json()
    granted = {node["label"] for node in forest["results"] if node["granted"]}
    assert granted == {"Europe"} and forest["all"] is False


def test_the_aggregate_sums_only_the_rows_of_the_scope(client_as: Any) -> None:
    world = World()
    url = "/api/indicators/aggregate/?group_by=year&metric=sum&value=value"
    mine = analyst_of(client_as, world.europe).get(url).json()
    assert [c["key"] for c in mine["categories"]] == [2020]
    assert mine["series"][0]["values"] == [165.5]  # France and Spain, not Japan
    every = client_as("staff").get(url).json()
    assert [c["key"] for c in every["categories"]] == [2020, 2021]
    assert every["series"][0]["values"] == [250.0, 13.0]


def test_the_aggregate_groups_countries_by_their_continent(client_as: Any) -> None:
    world = World()
    url = "/api/indicators/aggregate/?group_by=region__parent&metric=count"
    asia = analyst_of(client_as, world.asia).get(url).json()
    assert [
        (c["label"], v) for c, v in zip(asia["categories"], asia["series"][0]["values"])
    ] == [("Asia", 2)]
    every = client_as("staff").get(url).json()
    assert dict(
        zip([c["label"] for c in every["categories"]], every["series"][0]["values"])
    ) == {
        "Asia": 2,
        "Europe": 2,
    }


def test_the_saved_chart_draws_the_same_scope(client_as: Any) -> None:
    from portal.seeds import saved_chart

    world = World()
    chart = saved_chart()
    client = analyst_of(client_as, world.europe)
    data = client.get(f"/api/charts/{chart.slug}/data/").json()["data"]
    assert data["group_by"] == "year" and data["stacked"] is True
    assert [s["label"] for s in data["series"]] == ["Europe"]  # no Asia in this scope
    assert data["series"][0]["values"] == [2]


def test_the_dashboard_counts_what_the_user_may_read(client_as: Any) -> None:
    world = World()
    routes = (Path(__file__).parents[2] / "frontend/src/routes.tsx").read_text()
    assert (
        'path: "/overview"' in routes
    )  # the page karni build writes for `overview: dashboard`
    for resource, expected in (("indicators", 2), ("datasets", 1), ("regions", 5)):
        # useResourceCounts asks each resource for one row and reads the count
        analyst = analyst_of(client_as, world.europe)
        counted = analyst.get(f"/api/{resource}/?page_size=1").json()["count"]
        assert counted == expected, resource


def test_search_finds_datasets_and_indicators_inside_the_scope(client_as: Any) -> None:
    world = World()
    client = analyst_of(client_as, world.europe)
    found = client.get("/api/search/?q=life").json()["groups"]
    assert {g["resource"]: [h["title"] for h in g["hits"]] for g in found} == {
        "datasets": ["Life expectancy"],
        "indicators": ["Life expectancy, France, 2020", "Life expectancy, Spain, 2020"],
    }
    assert client.get("/api/search/?q=beds").json()["groups"] == []
    assert len(client_as("staff").get("/api/search/?q=beds").json()["groups"]) == 2


def run_import(client: Any, url: str, text: str, tmp_path: Path) -> dict[str, Any]:
    upload = SimpleUploadedFile("rows.csv", text.encode(), content_type="text/csv")
    job = client.post(f"{url}import/", {"file": upload}, format="multipart").json()
    preview = client.post(
        f"{url}import/{job['id']}/preview/", {"mapping": job["mapping"]}, format="json"
    ).json()
    committed = client.post(
        f"{url}import/{job['id']}/commit/", {}, format="json"
    ).json()
    assert committed["status"] == "done", committed
    return preview["result"]


def test_an_import_updates_rows_by_their_natural_key(
    client_as: Any, settings: Any, tmp_path: Path
) -> None:
    settings.MEDIA_ROOT = str(
        tmp_path
    )  # the uploaded file is kept until the import is done
    world = World()
    editor = client_as("editor")
    rows = (
        "label,dataset,region,sector,year,value\n"
        '"Life expectancy, France, 2020",life-expectancy,france,health,2020,90.5\n'
        '"Life expectancy, France, 2021",life-expectancy,france,health,2021,91.0\n'
    )
    result = run_import(editor, "/api/indicators/", rows, tmp_path)
    assert result["updated"] == 1 and result["created"] == 1
    assert Indicator.objects.get(
        label="Life expectancy, France, 2020"
    ).value == Decimal("90.5")
    assert Indicator.objects.filter(region=world.france).count() == 2
    datasets = "slug,title\nlife-expectancy,Life expectancy at birth\n"
    assert run_import(editor, "/api/datasets/", datasets, tmp_path)["updated"] == 1
    assert (
        Dataset.objects.get(slug="life-expectancy").title == "Life expectancy at birth"
    )
    exported = client_as("staff").get("/api/indicators/export/?format=csv")
    assert exported.status_code == 200 and b"2021" in b"".join(exported)


def test_an_analyst_cannot_import(client_as: Any) -> None:
    world = World()
    client = analyst_of(client_as, world.europe)
    upload = SimpleUploadedFile("rows.csv", b"label\nx\n", content_type="text/csv")
    response = client.post(
        "/api/indicators/import/", {"file": upload}, format="multipart"
    )
    assert response.status_code == 403
