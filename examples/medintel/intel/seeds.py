"""intel demo data for karni seed. Each seeder extends the one karni build writes in
intel/karni/seeds.py: steer a field's values here.

Every name below is invented. The same --seed gives the same rows on every machine.
"""

from typing import Any

import factory
from django.contrib.auth import get_user_model
from karni.accounts import grants
from karni.accounts.models import UserGrant
from karni.seeding import SeedContext, Seeder
from karni_charts.models import Chart

from intel.karni import seeds as karni
from intel.models import Company, Condition, Intervention, Trial

_STEMS = ["Veltra", "Marrin", "Orlund", "Pellan", "Kestrel", "Doran", "Sable", "Quint"]
_KINDS = {
    "Oncology": "tumour",
    "Respiratory": "airway disease",
    "Metabolic": "metabolic disorder",
    "Neurological": "nerve disorder",
    "Immune": "immune disorder",
    "Cardiac": "heart disease",
}
# Six areas, two groups, two kinds and two invented conditions each: 90 nodes.
CONDITIONS = {
    area: {
        onset: {
            kind: [f"{_STEMS[(i + j) % 8]} {suffix}" for j in range(2)]
            for i, kind in enumerate(("Common", "Rare"))
        }
        for onset in ("Early onset", "Late onset")
    }
    for area, suffix in _KINDS.items()
}
# Five categories, two groups and two invented products each: 35 nodes.
INTERVENTIONS = {
    "Biologics": {
        "Antibody drug": ["Veltrimab", "Orlanumab"],
        "Protein drug": ["Pellaceptor", "Kestrelase"],
    },
    "Small molecules": {
        "Kinase blocker": ["Doranib", "Sablenib"],
        "Enzyme blocker": ["Quintostat", "Marrinostat"],
    },
    "Cell and gene": {
        "Cell therapy": ["Veltra-T", "Orlund-NK"],
        "Gene therapy": ["Pellavec", "Kestrelgene"],
    },
    "Vaccines": {
        "Protein vaccine": ["Doravax", "Sablevax"],
        "Nucleic acid": ["Quintvax", "Marrinvax"],
    },
    "Devices": {
        "Implant device": ["Veltra stent", "Orlund valve"],
        "Monitor device": ["Pellan patch", "Kestrel sensor"],
    },
}
_PREFIXES = [
    "Alder",
    "Brook",
    "Cinder",
    "Dawn",
    "Ember",
    "Fenn",
    "Garnet",
    "Heron",
    "Iris",
    "Juniper",
]
_SUFFIXES = ["Therapeutics", "Biosciences", "Pharma", "Medical"]
_GIVEN = ["Asha", "Bruno", "Cleo", "Dario", "Esme", "Farid", "Greta", "Hugo", "Ines", "Jonas"]
_FAMILY = [
    "Ashdown",
    "Bellweather",
    "Corrigan",
    "Dunmore",
    "Eastwick",
    "Fairbairn",
    "Grafton",
    "Hollis",
]
_ENDINGS = ["ra", "ex", "on", "ix", "al", "um", "is", "or"]
#: Customer logins (KARNI_SEED_LOGINS): the nodes of each tree they are granted.
CUSTOMERS = {
    "analyst@example.com": {"conditions": ["Oncology"], "interventions": ["Biologics"]},
    "oncology@example.com": {"conditions": ["Oncology"]},
    "vaccines@example.com": {"interventions": ["Vaccines"]},
}


REASON = "demo customer"
FILTERS = ["interventions", "interventions_descendants"]


def _plant(context: SeedContext, code: str, spec: Any, parent: Any = None) -> list[Any]:
    """Create a nested dict (or a list of leaf names) as tree nodes, parents first.

    A node's code is its prefix and its place (C1.2.1): the codes stay unique and short.
    """
    rows: list[Any] = []
    for place, (name, below) in enumerate(
        spec.items() if isinstance(spec, dict) else ((n, []) for n in spec), 1
    ):
        row = context.create(1, code=f"{code}{place}", name=name, parent=parent)[0]
        rows += [row, *_plant(context, f"{row.code}.", below, row)]
    return rows


def _leaves(model: Any) -> list[Any]:
    parents = set(model.objects.values_list("parent_id", flat=True))
    return [node for node in model.objects.order_by("code") if node.pk not in parents]


class ConditionSeeder(karni.ConditionSeeder):
    def seed(self, context: SeedContext) -> list[Any]:
        return _plant(context, "C", CONDITIONS)


class InterventionSeeder(karni.InterventionSeeder):
    def seed(self, context: SeedContext) -> list[Any]:
        return _plant(context, "I", INTERVENTIONS)


class CompanySeeder(karni.CompanySeeder):
    name = factory.Sequence(lambda n: f"{_PREFIXES[n % 10]} {_SUFFIXES[n // 10 % 4]}")


class PersonSeeder(karni.PersonSeeder):
    name = factory.Sequence(lambda n: f"{_GIVEN[n % 10]} {_FAMILY[n // 10 % 8]}")
    email = factory.Sequence(
        lambda n: f"{_GIVEN[n % 10]}.{_FAMILY[n // 10 % 8]}{n}@example.com".lower()
    )


class BrandSeeder(karni.BrandSeeder):
    name = factory.Sequence(lambda n: f"{_STEMS[n % 8]}{_ENDINGS[n // 8 % 8]}")


class TrialSeeder(karni.TrialSeeder):
    def seed(self, context: SeedContext) -> list[Any]:
        rng, conditions, interventions = context.random, _leaves(Condition), _leaves(Intervention)
        rows = []
        for n in range(context.count):
            year = rng.randint(2012, 2025)
            tags = rng.sample(conditions, 2), rng.sample(interventions, 2)
            row = context.create(
                1,
                code=f"MT-{n + 1:04}",
                title=f"{tags[1][0].name} in {tags[0][0].name}",
                phase=rng.choices(Trial.Phase.values, weights=[3, 4, 2, 1])[0],
                status=rng.choice(Trial.Status.values[2:] if year < 2020 else Trial.Status.values),
                start_year=year,
                enrollment=rng.randint(20, 900),
                sponsor=context.pick(Company),
            )[0]
            row.conditions.set(tags[0])
            row.interventions.set(tags[1])
            rows.append(row)
        return rows


class DealSeeder(karni.DealSeeder):
    def seed(self, context: SeedContext) -> list[Any]:
        rng, companies, interventions = (
            context.random,
            list(Company.objects.order_by("name")),
            _leaves(Intervention),
        )
        rows = []
        for n in range(context.count):
            buyer, seller = rng.sample(companies, 2)
            row = context.create(
                1,
                title=f"{buyer.name} and {seller.name}, deal {n + 1}",
                year=rng.randint(2012, 2025),
                acquirer=buyer,
                seller=seller,
            )[0]
            row.interventions.set(rng.sample(interventions, 2))
            rows.append(row)
        return rows


class UserGrantSeeder(Seeder):
    """Each customer login sees the rows under the nodes it is granted, and nothing else."""

    class Meta:
        model = UserGrant
        count = 1

    def seed(self, context: SeedContext) -> list[Any]:
        UserGrant.objects.filter(reason=REASON).delete()  # --reset does not wipe it
        rows = []
        for email, nodes in CUSTOMERS.items():
            user = get_user_model().objects.get(email=email)
            for scope, tree, patterns in (
                ("tree:conditions", Condition, ["intel.trial:view"]),
                ("tree:interventions", Intervention, ["intel.*:view"]),
                ("tree:company__interventions", Intervention, ["intel.person:view"]),
            ):
                targets = [
                    tree.objects.get(name=name).pk
                    for name in nodes.get(scope.split(":")[1].split("__")[-1], [])
                ]
                rows += [
                    grants.grant(None, user, p, scope, targets=targets, reason=REASON)
                    for p in patterns
                    if targets
                ]
        return rows


class ChartSeeder(Seeder):
    """The saved charts: rows, drawn by SavedChart, read through Deal's aggregation.

    --reset does not wipe a module's table, so a re-run updates the charts by slug.
    """

    class Meta:
        model = Chart
        count = 1

    def seed(self, context: SeedContext) -> list[Any]:
        sum_by_year = {
            "kind": "bar",
            "y_metric": "sum",
            "y_value": "value",
            "y_label": "Value (USD)",
        }
        count_by_year = {"kind": "line", "y_metric": "count", "y_label": "Deals"}
        return [
            Chart.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "source": "deals",
                    "x_field": "year",
                    "x_label": "Year",
                    "allowed_filters": FILTERS,
                    **fields,
                },
            )[0]
            for slug, name, fields in (
                ("deal-value-by-year", "Deal value by year", sum_by_year),
                ("deals-by-year", "Deals by year", count_by_year),
            )
        ]
