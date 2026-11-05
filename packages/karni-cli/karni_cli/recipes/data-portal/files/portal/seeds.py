"""portal demo data for karni seed. Each seeder extends the one karni build writes in
portal/karni/seeds.py: steer a field's values here.

The trees, datasets and indicators are synthetic. Replace the names and the numbers with
your own, or load real rows with an import.
"""

from datetime import date
from itertools import product
from typing import Any

from karni.seeding import SeedContext
from karni_charts.models import Chart
from portal.karni import seeds as karni

from portal.models import Dataset, Indicator, Region, Sector

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
SECTORS = {
    "Economy": ["Trade", "Employment"],
    "Health": ["Mortality", "Care"],
    "Education": ["Schools", "Literacy"],
    "Environment": ["Air", "Water"],
    "Energy": ["Production", "Use"],
}
UNITS = ["percent", "index", "thousand", "per 1,000", "tonnes"]
KINDS = ["by year", "annual survey", "census"]
PUBLISHERS = [
    "Statistics Office",
    "Research Institute",
    "Public Registry",
    "Survey Unit",
]
YEARS = range(2014, 2025)
CHART = "indicators-per-year"


class RegionSeeder(karni.RegionSeeder):
    """Continents with their countries: a tree two levels deep."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for continent, countries in REGIONS.items():
            parent = context.create(1, name=continent, parent=None)[0]
            rows.append(parent)
            for country in countries:
                rows += context.create(1, name=country, parent=parent)
        return rows


class SectorSeeder(karni.SectorSeeder):
    """Five sectors with two topics each."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for sector, topics in SECTORS.items():
            parent = context.create(1, name=sector, parent=None)[0]
            rows.append(parent)
            for topic in topics:
                rows += context.create(1, name=topic, parent=parent)
        return rows


def _countries(continent: Region) -> list[Region]:
    return list(Region.objects.filter(parent=continent).order_by("name"))


class DatasetSeeder(karni.DatasetSeeder):
    """A dataset per topic and kind, each covering the countries of two continents."""

    def seed(self, context: SeedContext) -> list[Any]:
        continents = list(Region.objects.filter(parent=None).order_by("name"))
        topics = list(Sector.objects.exclude(parent=None).order_by("name"))
        rows: list[Any] = []
        for number, (topic, kind) in enumerate(product(topics, KINDS)):
            if number >= context.count:
                break
            dataset = context.create(
                1,
                title=f"{topic.name} {kind}",
                summary=f"**{topic.name}** figures, {kind}, per country and year.",
                method="Counted from registers and surveys. See each row's *note*.",
                publisher=PUBLISHERS[number % len(PUBLISHERS)],
                published_on=date(2025, 1 + number % 12, 1),
            )[0]
            covered = _countries(continents[number % 6]) + _countries(
                continents[(number + 1) % 6]
            )
            dataset.region.set(covered)
            dataset.sector.set([topic])
            rows.append(dataset)
        return rows


class IndicatorSeeder(karni.IndicatorSeeder):
    """A value per dataset, country covered and year, and the saved chart over them."""

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Indicator] = []
        for dataset in Dataset.objects.order_by("title"):
            topic = dataset.sector.get()
            base = context.random.uniform(5, 500)
            unit = UNITS[sum(map(ord, topic.name)) % len(UNITS)]
            for country, year in product(dataset.region.order_by("name"), YEARS):
                if len(rows) >= context.count:
                    break
                trend = 1 + 0.03 * (year - YEARS[0])
                rows.append(
                    Indicator(
                        dataset=dataset,
                        region=country,
                        sector=topic,
                        year=year,
                        value=round(base * trend * context.random.uniform(0.8, 1.2), 3),
                        unit=unit,
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
