"""portal demo data for karni seed. Each seeder extends the one karni build writes in
portal/karni/seeds.py: steer a field's values here.

The trees, datasets and indicators are synthetic. Replace the names and the numbers with
your own, or load real rows with an import.
"""

"""portal demo data for karni seed. Each seeder extends the one karni build writes in
portal/karni/seeds.py: steer a field's values here.

The trees, datasets and indicators are synthetic: the publishers are invented and the
values only look like the measures they are named for. Replace the names and the numbers
with your own, or load real rows with an import.
"""

import math
import uuid
from datetime import date
from itertools import product
from typing import Any, NamedTuple

from django.utils.text import slugify
from karni.seeding import SeedContext, cycled
from karni_charts.models import Chart
from portal.karni import seeds as karni

from portal.models import Dataset, Indicator, Region, Sector


class Measure(NamedTuple):
    """A dataset: what it measures, in what unit, and the range its values fall in."""

    title: str
    unit: str
    low: float
    high: float


REGIONS = {
    "Africa": ["Algeria", "Ghana", "Kenya", "Morocco", "Nigeria", "Senegal"],
    "Asia": [
        "India",
        "Indonesia",
        "Japan",
        "Kazakhstan",
        "Thailand",
        "Vietnam",
        "Nepal",
    ],
    "Europe": ["France", "Germany", "Italy", "Poland", "Portugal", "Spain", "Sweden"],
    "North America": ["Canada", "Costa Rica", "Mexico", "Panama", "United States"],
    "South America": ["Argentina", "Brazil", "Chile", "Colombia", "Peru"],
    "Oceania": ["Australia", "Fiji", "New Zealand", "Samoa"],
}
# sector -> topic -> the datasets on that topic
SECTORS: dict[str, dict[str, list[Measure]]] = {
    "Economy": {
        "Trade and Prices": [
            Measure("Consumer price inflation", "percent", 0.5, 9),
            Measure("Merchandise exports", "million USD", 200, 40000),
            Measure("Foreign direct investment inflows", "million USD", 50, 15000),
        ],
        "Labour and Earnings": [
            Measure("Unemployment rate", "percent", 2, 15),
            Measure("Labour force participation", "percent", 45, 80),
            Measure("Average monthly earnings", "USD", 250, 4500),
        ],
    },
    "Health": {
        "Mortality and Life Expectancy": [
            Measure("Life expectancy at birth", "years", 55, 84),
            Measure("Infant mortality rate", "per 1,000 births", 2, 60),
            Measure("Road traffic deaths", "per 100,000 people", 3, 30),
        ],
        "Health Services": [
            Measure("Physicians per 1,000 people", "per 1,000", 0.1, 5),
            Measure("Hospital beds per 1,000 people", "per 1,000", 0.3, 12),
            Measure("Childhood immunisation coverage", "percent", 55, 99),
        ],
    },
    "Education": {
        "Schools and Enrolment": [
            Measure("Primary school enrolment", "percent", 70, 100),
            Measure("Secondary school completion", "percent", 30, 98),
            Measure("Pupils per teacher, primary", "pupils", 10, 55),
        ],
        "Adult Literacy": [
            Measure("Adult literacy rate", "percent", 50, 99),
            Measure("Youth literacy rate", "percent", 60, 100),
            Measure("Adults in training programmes", "thousand", 5, 900),
        ],
    },
    "Environment": {
        "Air Quality": [
            Measure("Fine particle concentration", "micrograms per m3", 5, 80),
            Measure("Urban population exposed to poor air", "percent", 5, 90),
            Measure("Greenhouse gas emissions per person", "tonnes CO2e", 0.5, 20),
        ],
        "Water and Sanitation": [
            Measure("Access to safe drinking water", "percent", 60, 100),
            Measure("Access to basic sanitation", "percent", 40, 100),
            Measure("Freshwater withdrawals", "cubic km", 0.5, 300),
        ],
    },
    "Energy": {
        "Electricity Supply": [
            Measure("Population with electricity access", "percent", 40, 100),
            Measure("Electricity generated", "TWh", 1, 800),
            Measure("Renewables share of generation", "percent", 3, 85),
        ],
        "Energy Use": [
            Measure("Energy use per person", "GJ", 10, 250),
            Measure("Household energy spending", "USD", 80, 2800),
            Measure("Energy imports as a share of supply", "percent", 0, 90),
        ],
    },
}
PUBLISHERS = {
    "Economy": "Bureau of Economic Statistics",
    "Health": "Health Information Unit",
    "Education": "Education Data Service",
    "Environment": "Environment Monitoring Agency",
    "Energy": "Energy Statistics Division",
}
METHODS = {
    "Economy": "Compiled from national accounts, customs records and surveys.",
    "Health": "Compiled from civil registration, clinic reports and household surveys.",
    "Education": "Compiled from school censuses and national household surveys.",
    "Environment": "Compiled from monitoring stations, satellite data and utilities.",
    "Energy": "Compiled from utility returns, fuel balances and household surveys.",
}
LICENSES = ["open", "attribution"]
YEARS = range(2014, 2025)
CHART = "indicators-per-year"
CONTINENTS_PER_DATASET = 3


def _tree(branches: dict[str, list[str]]) -> list[tuple[str, str | None]]:
    """Each root followed by its children: (name, parent's name)."""
    flat: list[tuple[str, str | None]] = []
    for root, children in branches.items():
        flat.append((root, None))
        flat += [(child, root) for child in children]
    return flat


def _plant(context: SeedContext, flat: list[tuple[str, str | None]]) -> list[Any]:
    """Create ``context.count`` nodes of a tree, a parent before its children.

    Past the end of the list the names come round again with a number.
    """
    names = [name for name, _ in flat]
    made: dict[str, Any] = {}
    rows: list[Any] = []
    for number in range(context.count):
        _, parent = flat[number % len(flat)]
        full = cycled(names, number)
        parent_name = None if parent is None else cycled([parent], number // len(flat))
        row = context.create(1, name=full, parent=made.get(parent_name or ""))[0]
        made[full] = row
        rows.append(row)
    return rows


# the datasets in the order they are made: one from each topic, then the second of each
FLAT: list[tuple[str, str, Measure]] = [
    (sector, topic, measures[turn])
    for turn in range(3)
    for sector, topics in SECTORS.items()
    for topic, measures in topics.items()
]


def _measure(dataset: Dataset) -> Measure:
    """The measure a dataset row was made from (also with a round suffix)."""
    for _, _, measure in FLAT:
        if dataset.title.startswith(measure.title):
            return measure
    return Measure(dataset.title, "index", 0, 100)


class RegionSeeder(karni.RegionSeeder):
    """Continents with their countries: a tree two levels deep."""

    def seed(self, context: SeedContext) -> list[Any]:
        return _plant(context, _tree(REGIONS))


class SectorSeeder(karni.SectorSeeder):
    """Five sectors with two topics each."""

    def seed(self, context: SeedContext) -> list[Any]:
        return _plant(context, _tree({s: list(t) for s, t in SECTORS.items()}))


def _countries(continent: Region) -> list[Region]:
    return list(Region.objects.filter(parent=continent).order_by("name"))


class DatasetSeeder(karni.DatasetSeeder):
    """A dataset per measure, filed under its topic, on three continents."""

    def seed(self, context: SeedContext) -> list[Any]:
        continents = list(Region.objects.filter(parent=None).order_by("name"))
        topics = {row.name: row for row in Sector.objects.exclude(parent=None)}
        rows: list[Any] = []
        for number in range(context.count):
            sector, topic_name, measure = FLAT[number % len(FLAT)]
            topic = topics.get(topic_name) or (
                list(topics.values())[number % len(topics)] if topics else None
            )
            dataset = context.create(
                1,
                title=cycled([measure.title], number // len(FLAT)),
                summary=f"**{measure.title}**, in {measure.unit}, by country and year.",
                method=METHODS[sector],
                publisher=PUBLISHERS[sector],
                source_url=f"https://data.example.org/{slugify(measure.title)}",
                frequency="annual",
                license=LICENSES[number % len(LICENSES)],
                published_on=date(2025, 1 + number % 12, 1),
            )[0]
            if continents:
                first = number % len(continents)
                covered = [
                    country
                    for step in range(CONTINENTS_PER_DATASET)
                    for country in _countries(
                        continents[(first + step) % len(continents)]
                    )
                ]
                dataset.region.set(covered)
            if topic is not None:
                dataset.sector.set([topic])
            rows.append(dataset)
        return rows


class IndicatorSeeder(karni.IndicatorSeeder):
    """A value per dataset, country covered and year, and the saved chart over them.

    The rows are shared out evenly between the datasets. Each value sits in its
    range, differs by country and drifts upward with the years.
    """

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Indicator] = []
        datasets = list(Dataset.objects.order_by("title"))
        for position, dataset in enumerate(datasets):
            budget = math.ceil((context.count - len(rows)) / (len(datasets) - position))
            topic = dataset.sector.get()
            measure = _measure(dataset)
            span = measure.high - measure.low
            level: dict[int, float] = {}
            combos = product(dataset.region.order_by("name"), YEARS)
            for country, year in list(combos)[:budget]:
                level.setdefault(country.pk, context.random.random())
                share = level[country.pk] * 0.85 + 0.01 * (year - YEARS[0])
                share = min(1.0, max(0.0, share + context.random.uniform(-0.03, 0.03)))
                rows.append(
                    Indicator(
                        id=uuid.UUID(int=context.random.getrandbits(128), version=4),
                        dataset=dataset,
                        region=country,
                        sector=topic,
                        year=year,
                        value=round(measure.low + span * share, 3),
                        unit=measure.unit,
                        label=f"{dataset.title}, {country.name}, {year}",
                    )
                )
        created = Indicator.objects.bulk_create(rows, batch_size=1000)
        saved_chart()
        return created


def saved_chart() -> Chart:
    """The chart the dashboard draws: indicator rows per year, stacked by continent."""
    chart, _ = Chart.objects.update_or_create(
        slug=CHART,
        defaults={
            "name": "Indicators per year",
            "description": "Indicator values published each year, by continent.",
            "source": "indicators",
            "kind": "bar",
            "x_field": "year",
            "x_label": "Year",
            "y_metric": "count",
            "y_label": "Values",
            "z_field": "region__parent",
            "z_mode": "stack",
            "allowed_filters": ["dataset", "region", "sector"],
        },
    )
    return chart
